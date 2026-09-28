"""文档知识库检索：CAS/中文名桥接 + Qdrant 向量近邻，供 chat 注入上下文。

策略（hybrid）：
- 明确指定 MSDS 章节或 MSDS 物性字段 → 直接读取对应的已解析章节；
- 问题里能解析出 CAS 或库内化学品名称 → 桥接该物质的质检通过章节（保底必中）
  并在其范围内做向量近邻排序；
- 解析不出目标物质 → 全库向量近邻（依赖 multilingual embedding 做中文→英文匹配）；
- embedding 或 Qdrant 不可用 → 只要桥接有结果仍可回答（降级不中断）。
"""

from __future__ import annotations

import logging
import re
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
    source: str  # exact | vector | bridge
    document_id: int | None = None
    document_title: str | None = None
    source_url: str | None = None
    parse_status: str | None = None
    updated_at: str | None = None


async def resolve_doc_targets(db: Session, question: str) -> list[str]:
    """从问题中解析目标物质的 CAS 列表：合法 CAS + 库内中英文名匹配。"""

    from app.modules.chemicals.model import Chemical

    targets: list[str] = list(extract_valid_cas(question))
    lowered = question.lower()
    rows = db.execute(
        select(Chemical.cas_no, Chemical.chemical_name, Chemical.english_name, Chemical.alias_text)
        .where(Chemical.status == "ACTIVE")
    ).all()
    name_hits: list[tuple[int, str]] = []
    for cas_no, chemical_name, english_name, alias_text in rows:
        if not cas_no:
            continue
        names = [chemical_name, english_name]
        if alias_text:
            names.extend(re.split(r"[,;，；、|/]+", str(alias_text)))
        for name in names:
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


def requested_msds_section(question: str) -> int | None:
    """识别明确要求的 MSDS 章节；物性字段归入第 9 节。"""

    lowered = question.lower()
    if not re.search(r"(?<![a-z])(?:msds|sds)(?![a-z])|安全数据表|安全技术说明书", lowered):
        return None
    if re.search(r"(?<![a-z])tds(?![a-z])|技术数据表|物性页|物性资料", lowered):
        return None  # 比较多个来源时不强行限定为 MSDS
    matches = re.findall(r"第\s*(\d{1,2})\s*节|\bsection\s*(\d{1,2})\b", lowered)
    if matches:
        section_numbers = {int(chinese or english) for chinese, english in matches}
        if len(section_numbers) != 1:
            return None  # 多章节问题交给一般检索，避免只展示第一节
        section_no = section_numbers.pop()
        return section_no if 1 <= section_no <= 16 else None
    if any(term in lowered for term in ("闪点", "沸点", "沸程", "熔点", "密度", "蒸气压", "溶解度", "自燃温度", "flash point", "boiling point", "melting point")):
        return 9
    return None


def requested_single_doc_type(question: str) -> str | None:
    """Only constrain retrieval when exactly one document type is requested."""

    lowered = question.lower()
    mentioned = {
        doc_type for doc_type, pattern in (
            ("msds", r"(?<![a-z])(?:msds|sds)(?![a-z])|安全数据表|安全技术说明书"),
            ("tds", r"(?<![a-z])tds(?![a-z])|技术数据表"),
            ("property", r"物性页|物性资料"),
        ) if re.search(pattern, lowered)
    }
    return next(iter(mentioned)) if len(mentioned) == 1 else None


def no_doc_hits_reply(question: str) -> str:
    """针对明确的来源请求说明缺失范围，避免把一次召回失败说成全库缺失。"""

    section_no = requested_msds_section(question)
    if section_no is not None:
        return f"当前知识库没有匹配到该化学品已解析的 MSDS 第 {section_no} 节。请核对化学品名称或 CAS 号，或补充相应文档。"
    return "本次没有检索到可用的化学品文档摘录。请核对 CAS 号或准确的中英文名称后重试。"


async def retrieve_sections(
    db: Session, question: str, *, top_k: int = 6, settings: Settings | None = None
) -> list[DocSectionHit]:
    """混合检索：向量近邻 + 名称桥接，按分数合并去重，返回 top_k。"""

    targets = await resolve_doc_targets(db, question)

    # 来源和章节都明确时，数据库中的已解析章节就是精确证据；不让其它文档的
    # 相似向量分数把它挤出 top_k，也无需调用 embedding 服务。
    section_no = requested_msds_section(question)
    requested_type = requested_single_doc_type(question)
    exact_type = "msds" if section_no is not None else requested_type if requested_type in {"tds", "property"} else None
    if targets and exact_type is not None:
        from app.modules.doc_kb.model import AiDocument

        statement = (
            select(
                AiDocumentSection,
                AiDocument.name_zh,
                AiDocument.id,
                AiDocument.title,
                AiDocument.source_url,
                AiDocument.parse_status,
                AiDocument.updated_at,
            )
            .join(AiDocument, AiDocument.id == AiDocumentSection.document_id)
            .where(
                AiDocument.parse_status == "PARSED",
                AiDocumentSection.cas_no.in_(targets),
                AiDocumentSection.doc_type == exact_type,
            )
            .order_by(AiDocument.updated_at.desc(), AiDocumentSection.section_no.asc(), AiDocumentSection.id.desc())
        )
        if section_no is not None:
            statement = statement.where(AiDocumentSection.section_no == section_no)
        rows = db.execute(statement).all()
        if exact_type == "property":
            # Property pages split the key physical values into their first section;
            # later sections contain supplier links and unrelated navigation text.
            rows.sort(key=lambda row: (targets.index(row[0].cas_no), row[0].id))
        else:
            rows.sort(key=lambda row: targets.index(row[0].cas_no))
        return [
            DocSectionHit(
                id=section.id,
                cas_no=section.cas_no,
                doc_type=section.doc_type,
                section_no=section.section_no,
                section_key=section.section_key,
                title=section.title,
                name_zh=name_zh,
                content=section.content,
                score=1.0,
                source="exact",
                document_id=document_id,
                document_title=document_title,
                source_url=source_url,
                parse_status=parse_status,
                updated_at=updated_at.isoformat() if updated_at else None,
            )
            for section, name_zh, document_id, document_title, source_url, parse_status, updated_at in rows[:top_k]
        ]

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
            select(
                AiDocumentSection,
                AiDocument.name_zh,
                AiDocument.id,
                AiDocument.title,
                AiDocument.source_url,
                AiDocument.parse_status,
                AiDocument.updated_at,
            )
            .join(AiDocument, AiDocument.id == AiDocumentSection.document_id)
            .where(
                AiDocument.parse_status == "PARSED",
                AiDocumentSection.cas_no.in_(targets),
            )
            .order_by(AiDocumentSection.cas_no, AiDocumentSection.doc_type, AiDocumentSection.section_no)
        )
        per_cas_seen: dict[str, int] = {}
        for section, name_zh, document_id, document_title, source_url, parse_status, updated_at in db.execute(statement).all():
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
                document_id=document_id,
                document_title=document_title,
                source_url=source_url,
                parse_status=parse_status,
                updated_at=updated_at.isoformat() if updated_at else None,
            )

    # 向量命中也通过数据库补齐可核验的文档元数据，不信任向量 payload 中的来源状态。
    if merged:
        from app.modules.doc_kb.model import AiDocument

        metadata = db.execute(
            select(
                AiDocumentSection.id,
                AiDocument.id,
                AiDocument.title,
                AiDocument.name_zh,
                AiDocument.source_url,
                AiDocument.parse_status,
                AiDocument.updated_at,
            )
            .join(AiDocument, AiDocument.id == AiDocumentSection.document_id)
            .where(AiDocumentSection.id.in_(merged))
        ).all()
        for section_id, document_id, document_title, name_zh, source_url, parse_status, updated_at in metadata:
            hit = merged.get(section_id)
            if hit:
                hit.document_id = document_id
                hit.document_title = document_title
                hit.source_url = source_url
                hit.name_zh = hit.name_zh or name_zh
                hit.parse_status = parse_status
                hit.updated_at = updated_at.isoformat() if updated_at else None

    ordered = sorted(merged.values(), key=lambda item: -item.score)
    return ordered[:top_k]


def build_doc_context(hits: list[DocSectionHit], *, max_chars: int = CONTEXT_MAX_CHARS) -> tuple[str, list[dict]]:
    """把命中章节拼成 system 上下文 + citations 元数据。"""

    header = (
        "以下是来自 ChemicalOps 化学品知识库的已校验文档摘录（MSDS/TDS/物性页）。"
        "只能依据摘录回答，禁止编造摘录中没有的数据；回答末尾用括号注明来源"
        "（物质名 + 章节，如：来源：乙醇 MSDS SECTION 9）。"
        "如果摘录不足以回答，请说明本次提供的摘录不足，不能据此断言整个知识库未收录。\n"
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
                "document_id": hit.document_id,
                "section_id": hit.id,
                "document_title": hit.document_title,
                "source_url": hit.source_url,
                "cas_no": hit.cas_no,
                "doc_type": hit.doc_type,
                "section_no": hit.section_no,
                "section_key": hit.section_key,
                "title": hit.title,
                "name_zh": hit.name_zh,
                "score": round(hit.score, 4),
                "parse_status": hit.parse_status,
                "updated_at": hit.updated_at,
                "content": hit.content[:SECTION_CONTENT_MAX_CHARS],
            }
        )
    return header + "\n\n".join(parts), citations
