"""只读列出时间列，按人工核实的行范围生成转换预演；没有写入或执行迁移选项。"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.core.time import serialize_timestamp


def read_catalog(connection) -> list[dict]:
    """仅 SELECT information_schema；不更改 session timezone，不读取业务行。"""
    if connection.dialect.name != "mysql":
        inspector = inspect(connection)
        try:
            attached = connection.execute(text("SELECT name FROM information_schema.sqlite_master WHERE type='table' AND name='COLUMNS'")).first()
        except Exception:
            attached = None
        if attached:
            rows = connection.execute(text("""
                SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name,
                       DATA_TYPE AS data_type, COLUMN_KEY AS column_key, COLUMN_DEFAULT AS column_default
                FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
            """))
            return [dict(row) for row in rows.mappings()]
        result = []
        schemas = [schema for schema in inspector.get_schema_names() if schema not in {"temp"}]
        for schema in schemas:
          for table in inspector.get_table_names(schema=schema):
            primary = set(inspector.get_pk_constraint(table, schema=schema).get("constrained_columns") or [])
            for column in inspector.get_columns(table, schema=schema):
                result.append({"table_name": table, "column_name": column["name"],
                               "data_type": str(column["type"]).lower(),
                               "column_key": "PRI" if column["name"] in primary else "",
                               "column_default": column.get("default")})
        return result
    rows = connection.execute(text("""
        SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name,
               DATA_TYPE AS data_type, COLUMN_KEY AS column_key, COLUMN_DEFAULT AS column_default
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """))
    return [dict(row) for row in rows.mappings()]


def build_report(catalog: list[dict], provenance: list[dict] | None = None) -> dict:
    temporal = [row for row in catalog if row["data_type"].lower() in {"datetime", "timestamp"}]
    by_column = {(row["table_name"], row["column_name"]): row for row in catalog}
    ranges: dict[tuple[str, str], list[tuple[int, int]]] = {}
    previews = []
    for item in provenance or []:
        key = (item["table"], item["column"])
        column = by_column.get(key)
        primary = by_column.get((item["table"], item["primary_key"]))
        if column is None or column["data_type"].lower() != "datetime":
            raise ValueError("only known DATETIME columns support explicit naive-source previews")
        table_primary = [row for row in catalog if row["table_name"] == item["table"] and row["column_key"] == "PRI"]
        if primary is None or primary["column_key"] != "PRI" or len(table_primary) != 1 or primary["data_type"].lower() not in {"int", "bigint", "smallint", "mediumint", "tinyint"}:
            raise ValueError("preview requires an actual single integer primary key")
        if item.get("reviewed") is not True or not str(item.get("evidence") or "").strip():
            raise ValueError("preview requires independently reviewed provenance evidence")
        lower, upper = item["min_id"], item["max_id"]
        if type(lower) is not int or type(upper) is not int or lower < 1 or upper < lower:
            raise ValueError("invalid primary key range")
        if any(not (upper < lo or lower > hi) for lo, hi in ranges.get(key, [])):
            raise ValueError("overlapping provenance ranges")
        ranges.setdefault(key, []).append((lower, upper))
        sample = datetime.fromisoformat(item["sample"])
        if sample.tzinfo is not None:
            raise ValueError("DATETIME preview sample must be naive")
        source = item["source_timezone"]
        if source not in {"UTC", "Asia/Shanghai"}:
            raise ValueError("unknown source timezone cannot be converted")
        previews.append({"table": key[0], "column": key[1], "primary_key": item["primary_key"],
                         "min_id": lower, "max_id": upper, "source_timezone": source,
                         "evidence": item["evidence"], "before": sample.isoformat(),
                         "after_utc": serialize_timestamp(sample, source_timezone=source),
                         "status": "preview_only_range_coverage_not_verified"})
    return {"mode": "read_only_preview", "automatic_migration_allowed": False,
            "metadata_is_not_timezone_proof": True, "temporal_columns": temporal,
            "unknown_columns": [f"{row['table_name']}.{row['column_name']}" for row in temporal],
            "conversion_previews": previews,
            "cutover_requirements": ["verified origin for each row/column range, no overlaps or gaps",
                                      "backup and isolated restore with before/after reconciliation",
                                      "deploy writer, MySQL session, API serializer and date filters together",
                                      "retain origin metadata for unconverted history; never infer from displayed value"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, help="离线元数据JSON；省略时只读查询当前数据库")
    parser.add_argument("--provenance", type=Path, help="已人工核实的列/主键范围及样本JSON；不执行更新")
    args = parser.parse_args()
    try:
        if args.catalog:
            catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        else:
            from app.core.db import engine
            with engine.connect() as connection:
                catalog = read_catalog(connection)
        provenance = json.loads(args.provenance.read_text(encoding="utf-8")) if args.provenance else []
        report = build_report(catalog, provenance)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Timestamp audit failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
