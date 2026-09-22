"""文档知识库检索：CAS/中文名桥接 + Qdrant 向量近邻，供 chat 注入上下文。

策略（hybrid）：
- 问题里能解析出 CAS 或库内化学品名称 → 桥接该物质的质检通过章节（保底必中）
  并在其范围内做向量近邻排序；
- 解析不出目标物质 → 全库向量近邻（依赖 multilingual embedding 做中文→英文匹配）；
- embedding 或 Qdrant 不可用 → 只要桥接有结果仍可回答（降级不中断）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.ai.intent import extract_valid_cas
from app.modules.doc_kb import vector_store
from app.modules.doc_kb.embedding import embed_texts
from app.modules.doc_kb.model import AiDocumentSection

LOGGER = logging.getLogger("chemicalops.ai.doc_kb")

MIN_NAME_LENGTH = 2
MAX_TARGET_CAS = 5
BRIDGE_SECTIONS_PER_CAS = 8
CONTEXT_MAX_CHARS = 12_000
SECTION_CONTENT_MAX_CHARS = 1_500


@dataclass
class DocSectionHit:
    """一条可注入的章节命中。"""

    id: int
    cas_no: str
    doc_type: str
    section_no: int | None
    section_key: str
    title: str | None
    name_zh: str | None
    content: str
    score: float
    source: str  # vector | bridge


async def resolve_doc_targets(db: Session, question: str) -> list[str]:
    """从问题中解析目标物质的 CAS 列表：合法 CAS + 库内中英文名匹配。"""

    from app.modules.chemicals.model import Chemical

    targets: list[str] = list(extract_valid_cas(question))
    lowered = question.lower()
    rows = db.execute(
        select(Chemical.cas_no, Chemical.chemical_name, Chemical.english_name, Chemical.alias_text)
    ).all()
    name_hits: list[tuple[int, str]] = []
    for cas_no, chemical_name, english_name, alias_text in rows:
        if not cas_no:
            continue
        for name in (chemical_name, english_name, alias_text):
            if not name:
                continue
            cleaned = str(name).strip()
            # 过短名字（如"酸"）会误命中，中英文都要求最小长度
            if len(cleaned) >= MIN_NAME_LENGTH and cleaned.lower() in lowered:
                name_hits.append((len(cleaned), cas_no))
                break
    # 名称长的更具体，优先；每个 CAS 只保留一次
    for _length, cas_no in sorted(name_hits, key=lambda item: -item[0]):
        if cas_no not in targets:
            targets.append(cas_no)
        if len(targets) >= MAX_TARGET_CAS:
            break
    return targets


async def retrieve_sections(
    db: Session, question: str, *, top_k: int = 6, settings: Settings | None = None
) -> list[DocSectionHit]:
    """混合检索：向量近邻 + 名称桥接，按分数合并去重，返回 top_k。"""

    targets = await resolve_doc_targets(db, question)

    vector_hits: list[dict] = []
    try:
        query_vector = (await embed_texts([question], settings))[0]
        client = vector_store.get_client()
        vector_hits = vector_store.search_sections(
            client, query_vector, top_k=top_k * 3, cas_list=targets or None
        )
    except Exception as exc:  # 向量链路故障不能阻断桥接兜底
        LOGGER.warning("文档向量检索失败，回退桥接 error_type=%s", type(exc).__name__)

    merged: dict[int, DocSectionHit] = {}
    for hit in vector_hits:
        payload = hit.get("payload") or {}
        if not payload.get("content"):
            continue
        section_id = int(hit["id"])
        merged[section_id] = DocSectionHit(
            id=section_id,
            cas_no=str(payload.get("cas_no") or ""),
            doc_type=str(payload.get("doc_type") or ""),
            section_no=payload.get("section_no"),
            section_key=str(payload.get("section_key") or ""),
            title=payload.get("title"),
            name_zh=payload.get("name_zh"),
            content=str(payload["content"]),
            score=float(hit["score"]),
            source="vector",
        )

    # 桥接保底：目标物质的质检章节即使向量没排进来也并入（一次 JOIN 带出中文名）
    if targets:
        from app.modules.doc_kb.model import AiDocument

        statement = (
            select(AiDocumentSection, AiDocument.name_zh)
            .join(AiDocument, AiDocument.id == AiDocumentSection.document_id)
            .where(
                AiDocument.parse_status == "PARSED",
                AiDocumentSection.cas_no.in_(targets),
            )
            .order_by(AiDocumentSection.cas_no, AiDocumentSection.doc_type, AiDocumentSection.section_no)
        )
        per_cas_seen: dict[str, int] = {}
        for section, name_zh in db.execute(statement).all():
            seen = per_cas_seen.get(section.cas_no, 0)
            if seen >= BRIDGE_SECTIONS_PER_CAS:
                continue
            per_cas_seen[section.cas_no] = seen + 1
            if section.id in merged:
                continue
            merged[section.id] = DocSectionHit(
                id=section.id,
                cas_no=section.cas_no,
                doc_type=section.doc_type,
                section_no=section.section_no,
                section_key=section.section_key,
                title=section.title,
                name_zh=name_zh,
                content=section.content,
                score=0.5,  # 桥接命中给中性分：弱于向量命中、强于未命中
                source="bridge",
            )

    ordered = sorted(merged.values(), key=lambda item: -item.score)
    return ordered[:top_k]


def build_doc_context(hits: list[DocSectionHit], *, max_chars: int = CONTEXT_MAX_CHARS) -> tuple[str, list[dict]]:
    """把命中章节拼成 system 上下文 + citations 元数据。"""

    header = (
        "以下是来自 ChemicalOps 化学品知识库的已校验文档摘录（MSDS/TDS/物性页）。"
        "只能依据摘录回答，禁止编造摘录中没有的数据；回答末尾用括号注明来源"
        "（物质名 + 章节，如：来源：乙醇 MSDS SECTION 9）。"
        "如果摘录不足以回答，请明确说明知识库未收录该信息。\n"
    )
    parts: list[str] = []
    citations: list[dict] = []
    used = 0
    for hit in hits:
        label = hit.name_zh or hit.title or hit.cas_no
        section_no = f" SECTION {hit.section_no}" if hit.section_no is not None else ""
        block = f"### {label}（{hit.cas_no} · {hit.doc_type}{section_no} · {hit.section_key}）\n{hit.content[:SECTION_CONTENT_MAX_CHARS]}"
        if used + len(block) > max_chars and parts:
            break
        parts.append(block)
        used += len(block)
        citations.append(
            {
                "type": "doc_kb",
                "cas_no": hit.cas_no,
                "doc_type": hit.doc_type,
                "section_no": hit.section_no,
                "section_key": hit.section_key,
                "title": hit.title,
                "name_zh": hit.name_zh,
                "score": round(hit.score, 4),
            }
        )
    return header + "\n\n".join(parts), citations
