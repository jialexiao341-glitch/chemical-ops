"""把知识库章节向量化并写入 Qdrant（幂等，按 section id 覆盖更新）。

前置：
- MySQL 中已跑过 scripts/parse_tds_msds.py（有 PARSED 章节）
- Qdrant 已启动（默认 127.0.0.1:6333，Docker: chemicalops-qdrant）
- LM Studio 已加载 embedding 模型（默认 text-embedding-qwen3-embedding-0.6b）

示例：
    python scripts/embed_sections.py                     # 全量
    python scripts/embed_sections.py --cas 64-17-5       # 指定 CAS
    python scripts/embed_sections.py --recreate          # 换模型后重建集合
    python scripts/embed_sections.py --batch 32
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.errors import BusinessValidationError  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.modules.doc_kb import vector_store  # noqa: E402
from app.modules.doc_kb.embedding import embed_texts  # noqa: E402
from app.modules.doc_kb.model import AiDocument, AiDocumentSection  # noqa: E402
from app.modules.task_queue import context, service  # noqa: E402


def load_parsed_sections(cas_list: list[str] | None = None, doc_type: str | None = None) -> list[dict[str, Any]]:
    """读取质检通过的章节（含中文名），供向量化。"""

    db = SessionLocal()
    try:
        statement = (
            select(
                AiDocumentSection.id,
                AiDocumentSection.document_id,
                AiDocumentSection.cas_no,
                AiDocumentSection.doc_type,
                AiDocumentSection.section_no,
                AiDocumentSection.section_key,
                AiDocumentSection.title,
                AiDocumentSection.content,
                AiDocumentSection.char_count,
                AiDocument.name_zh,
            )
            .join(AiDocument, AiDocument.id == AiDocumentSection.document_id)
            .where(AiDocument.parse_status == "PARSED")
            .order_by(AiDocumentSection.id)
        )
        if cas_list:
            statement = statement.where(AiDocumentSection.cas_no.in_(cas_list))
        if doc_type:
            statement = statement.where(AiDocumentSection.doc_type == doc_type)
        rows = db.execute(statement).all()
        return [
            {
                "id": row.id,
                "document_id": row.document_id,
                "cas_no": row.cas_no,
                "doc_type": row.doc_type,
                "section_no": row.section_no,
                "section_key": row.section_key,
                "title": row.title,
                "content": row.content,
                "char_count": row.char_count,
                "name_zh": row.name_zh,
            }
            for row in rows
        ]
    finally:
        db.close()


@contextmanager
def protected_write(document_id, generation, source_hash):
    with SessionLocal() as db:
        context.guard(db)
        document = db.scalar(select(AiDocument).where(AiDocument.id == document_id).with_for_update())
        if not document or (document.meta_json or {}).get("vector_generation") != generation or document.sha256 != source_hash:
            raise service.ExecutionLost("Document generation changed")
        yield
        context.guard(db)
        db.commit()


async def run(args: argparse.Namespace) -> None:
    if context.identity() and args.recreate:
        raise ValueError("队列任务禁止重建整个集合")
    sections = load_parsed_sections(args.cas or None, args.doc_type)
    settings = get_settings()
    print(
        f"sections={len(sections)} model={settings.embedding_model} "
        f"endpoint={settings.embedding_base_url} batch={args.batch}"
    )

    client = vector_store.get_client()
    vector_store.require_conditional_writes(client)
    started = time.perf_counter()
    total_points = 0
    with SessionLocal() as db:
        statement = select(AiDocument.id)
        if args.cas:
            statement = statement.where(AiDocument.cas_no.in_(args.cas))
        if args.doc_type:
            statement = statement.where(AiDocument.doc_type == args.doc_type)
        document_ids = list(db.scalars(statement).all())
    recreate = args.recreate
    for document_id in document_ids:
        with SessionLocal() as db:
            context.guard(db)
            document = db.scalar(select(AiDocument).where(AiDocument.id == document_id).with_for_update())
            generation = (document.meta_json or {}).get("vector_generation", 0) + 1
            document.meta_json = {**(document.meta_json or {}), "vector_generation": generation}
            cas, doc_type, source_hash = document.cas_no, document.doc_type, document.sha256
            db.commit()
        selected = [item for item in sections if item["document_id"] == document_id]
        for offset in range(0, len(selected), args.batch):
            batch = selected[offset : offset + args.batch]
            vectors = await embed_texts([item["content"] for item in batch], settings)
            with protected_write(document_id, generation, source_hash):
                vector_store.ensure_collection(client, len(vectors[0]), recreate=recreate)
            recreate = False
            rows = [
                {
                    "id": item["id"],
                    "vector": vector,
                    "payload": {
                        "cas_no": item["cas_no"],
                        "doc_type": item["doc_type"],
                        "section_no": item["section_no"],
                        "section_key": item["section_key"],
                        "title": item["title"],
                        "name_zh": item["name_zh"],
                        "content": item["content"],
                        "char_count": item["char_count"],
                        "model": settings.embedding_model,
                    },
                }
                for item, vector in zip(batch, vectors)
            ]
            with protected_write(document_id, generation, source_hash):
                vector_store.prepare_document_points(client, rows, cas=cas, doc_type=doc_type, generation=generation)
            with protected_write(document_id, generation, source_hash):
                total_points += vector_store.conditional_upsert_sections(client, rows, cas=cas, doc_type=doc_type, generation=generation)
        with protected_write(document_id, generation, source_hash):
            if client.collection_exists(vector_store.collection_name()):
                vector_store.cleanup_document_points(client, [item["id"] for item in selected],
                    cas=cas, doc_type=doc_type, generation=generation)

    elapsed = time.perf_counter() - started
    print(
        f"done: points={total_points} collection={vector_store.collection_name()} "
        f"elapsed={elapsed:.1f}s model={settings.embedding_model}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="知识库章节向量化并写入 Qdrant")
    parser.add_argument("--cas", nargs="*", help="只向量化指定 CAS 的章节")
    parser.add_argument("--doc-type", choices=("msds", "tds"), help="只向量化指定类型")
    parser.add_argument("--batch", type=int, default=32, help="每批文本数，默认 32")
    parser.add_argument("--recreate", action="store_true", help="删除并重建集合（换 embedding 模型后使用）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.batch < 1:
        raise SystemExit("--batch 必须大于 0")
    try:
        asyncio.run(run(args))
    except BusinessValidationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(78) from None


if __name__ == "__main__":
    main()
