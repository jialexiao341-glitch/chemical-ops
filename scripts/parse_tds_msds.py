"""从 MinIO 读取已抓取的 TDS/MSDS 原件，解析清洗后写入 AI 文档知识库。

前置：已执行 scripts/apply_ai_documents_migration.py，且爬虫已入库原件
（scripts/crawl_tds_msds.py）。

流程（幂等，可重复执行；解析规则变更后重跑即可刷新）：
    MinIO 原件 → doc_kb 解析/清洗/质检 → ai_documents + ai_document_sections

示例：
    python scripts/parse_tds_msds.py                        # 解析桶内全部原件
    python scripts/parse_tds_msds.py --cas 64-17-5 67-56-1  # 指定 CAS
    python scripts/parse_tds_msds.py --doc-type msds        # 只解析 MSDS
    python scripts/parse_tds_msds.py --skip-parsed          # 跳过已 PARSED 的文档
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.modules.chemicals.model import Chemical  # noqa: E402
from app.modules.doc_kb.model import AiDocument  # noqa: E402
from app.modules.doc_kb.service import (  # noqa: E402
    document_sha256,
    parse_document,
    store_parsed,
)
from scripts.crawl_tds_msds import MSDS_BUCKET_SUFFIX, TDS_BUCKET_SUFFIX  # noqa: E402


def classify_object(bucket: str, key: str) -> tuple[str, str] | None:
    """对象键 → (cas, doc_type)；无法识别返回 None。

    - chemicalops-msds/{cas}.html            → msds
    - chemicalops-tds/{cas}.pdf              → tds
    - chemicalops-tds/{cas}-property.html    → property
    """

    name = key.rsplit("/", 1)[-1]
    if bucket == MSDS_BUCKET_SUFFIX and name.endswith(".html"):
        return name[: -len(".html")], "msds"
    if bucket == TDS_BUCKET_SUFFIX and name.endswith(".pdf"):
        return name[: -len(".pdf")], "tds"
    if bucket == TDS_BUCKET_SUFFIX and name.endswith("-property.html"):
        return name[: -len("-property.html")], "property"
    return None


def group_objects(entries: list[tuple[str, str]]) -> dict[str, dict[str, str]]:
    """[(bucket, key), ...] → {cas: {doc_type: key}}，无法识别的丢弃。"""

    grouped: dict[str, dict[str, str]] = defaultdict(dict)
    for bucket, key in entries:
        classified = classify_object(bucket, key)
        if classified is None:
            continue
        cas, doc_type = classified
        grouped[cas][doc_type] = key
    return dict(grouped)


def list_source_objects(client: Any) -> list[tuple[str, str]]:
    """列出两个来源桶的全部对象，返回 [(bucket, object_key)]。"""

    entries: list[tuple[str, str]] = []
    for bucket in (MSDS_BUCKET_SUFFIX, TDS_BUCKET_SUFFIX):
        for obj in client.list_objects(bucket, recursive=True):
            if obj.object_name:
                entries.append((bucket, obj.object_name))
    return entries


def load_name_zh_map(db) -> dict[str, str]:
    """CAS → 中文名（md_chemicals），英文文档挂上中文桥接名。"""

    pairs = db.execute(select(Chemical.cas_no, Chemical.chemical_name)).all()
    return {cas: name for cas, name in pairs if cas and name}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="解析 MinIO 中的 TDS/MSDS 原件并写入 AI 文档知识库")
    parser.add_argument("--cas", nargs="*", help="只解析指定 CAS，如 --cas 64-17-5")
    parser.add_argument("--doc-type", choices=("msds", "tds", "property"), help="只解析指定类型")
    parser.add_argument("--skip-parsed", action="store_true", help="跳过已 PARSED 的文档（增量模式）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    settings = get_settings()
    if not settings.minio_access_key or not settings.minio_secret_key:
        raise SystemExit("MinIO 访问密钥未配置")
    from minio import Minio

    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        region=settings.minio_region,
    )

    entries = list_source_objects(client)
    grouped = group_objects(entries)
    if args.cas:
        wanted = set(args.cas)
        grouped = {cas: docs for cas, docs in grouped.items() if cas in wanted}

    db = SessionLocal()
    stats: dict[str, int] = {"PARSED": 0, "THIN": 0, "REJECTED": 0, "skipped": 0}
    per_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    problems: list[str] = []
    try:
        name_map = load_name_zh_map(db)
        total = sum(len(docs) for docs in grouped.values())
        print(f"objects={len(entries)} cas_count={len(grouped)} docs_to_parse={total}")
        done = 0
        for cas in sorted(grouped):
            for doc_type, key in sorted(grouped[cas].items()):
                if args.doc_type and doc_type != args.doc_type:
                    continue
                done += 1
                bucket = MSDS_BUCKET_SUFFIX if doc_type == "msds" else TDS_BUCKET_SUFFIX
                if args.skip_parsed:
                    existing = db.scalar(
                        select(AiDocument).where(
                            AiDocument.cas_no == cas,
                            AiDocument.doc_type == doc_type,
                            AiDocument.parse_status == "PARSED",
                        )
                    )
                    if existing is not None:
                        stats["skipped"] += 1
                        continue
                try:
                    content = client.get_object(bucket, key).read()
                except Exception as exc:
                    stats["REJECTED"] += 1
                    problems.append(f"{cas}/{doc_type}: MinIO 读取失败 {type(exc).__name__}")
                    print(f"[{done}/{total}] {cas} {doc_type} read-failed: {exc}")
                    continue

                parsed = parse_document(cas, doc_type, content)
                document = store_parsed(
                    db,
                    cas=cas,
                    doc_type=doc_type,
                    bucket=bucket,
                    object_key=key,
                    parsed=parsed,
                    name_zh=name_map.get(cas),
                    sha256=document_sha256(content),
                )
                stats[document.parse_status] = stats.get(document.parse_status, 0) + 1
                per_type[doc_type][document.parse_status] += 1
                if document.parse_status != "PARSED":
                    problems.append(f"{cas}/{doc_type}: {document.parse_status} - {document.reject_reason}")
                print(
                    f"[{done}/{total}] {cas} {doc_type} -> {document.parse_status}"
                    f" sections={document.section_count} chars={document.char_count}"
                    + (f" reason={document.reject_reason}" if document.reject_reason else "")
                )
    finally:
        db.close()

    print(
        "summary: "
        + " ".join(f"{key}={value}" for key, value in sorted(stats.items()))
    )
    for doc_type in sorted(per_type):
        breakdown = " ".join(f"{status}={count}" for status, count in sorted(per_type[doc_type].items()))
        print(f"  {doc_type}: {breakdown}")
    if problems:
        print("problems:")
        for item in problems:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
