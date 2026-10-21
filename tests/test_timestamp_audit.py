"""历史时间审计只读取元数据；有证据的行区间才产生转换预演。"""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text


def audit_module():
    path = Path(__file__).resolve().parents[1] / "scripts/audit_legacy_timestamps.py"
    assert path.exists(), "缺少只读历史时间审计与有来源的预演工具"
    spec = importlib.util.spec_from_file_location("timestamp_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CATALOG = [
    {"table_name": "purchase_orders", "column_name": "id", "data_type": "bigint", "column_key": "PRI", "column_default": None},
    {"table_name": "purchase_orders", "column_name": "created_at", "data_type": "datetime", "column_key": "", "column_default": "CURRENT_TIMESTAMP(3)"},
]


def test_unknown_column_never_generates_guessed_timezone_conversion():
    report = audit_module().build_report(CATALOG)
    assert report["mode"] == "read_only_preview"
    assert report["automatic_migration_allowed"] is False
    assert report["conversion_previews"] == []
    assert report["unknown_columns"] == ["purchase_orders.created_at"]


def test_catalog_reader_issues_only_selects_against_real_connection():
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS information_schema")
        conn.exec_driver_sql("CREATE TABLE information_schema.COLUMNS (TABLE_SCHEMA TEXT, TABLE_NAME TEXT, COLUMN_NAME TEXT, DATA_TYPE TEXT, COLUMN_KEY TEXT, COLUMN_DEFAULT TEXT)")
        conn.exec_driver_sql("INSERT INTO information_schema.COLUMNS VALUES ('main','purchase_orders','created_at','datetime','','CURRENT_TIMESTAMP(3)')")
        conn.connection.driver_connection.create_function("DATABASE", 0, lambda: "main")
        statements = []
        event.listen(conn, "before_cursor_execute", lambda _, __, statement, *rest: statements.append(statement))
        catalog = audit_module().read_catalog(conn)
        assert catalog[0]["column_name"] == "created_at"
        assert statements and all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
        assert conn.scalar(text("SELECT COUNT(*) FROM information_schema.COLUMNS")) == 1


def test_only_verified_range_generates_before_after_preview():
    provenance = [{"table": "purchase_orders", "column": "created_at", "primary_key": "id", "min_id": 1, "max_id": 10,
                   "source_timezone": "Asia/Shanghai", "evidence": "isolated writer log with fixed session +08:00",
                   "reviewed": True, "sample": "2026-10-21T08:00:00"}]
    report = audit_module().build_report(CATALOG, provenance)
    preview = report["conversion_previews"][0]
    assert preview["before"] == "2026-10-21T08:00:00"
    assert preview["after_utc"] == "2026-10-21T00:00:00Z"
    assert report["automatic_migration_allowed"] is False
    assert "purchase_orders.created_at" in report["unknown_columns"]


@pytest.mark.parametrize("change", [{"source_timezone": "unknown"}, {"reviewed": False}, {"evidence": ""},
                                    {"primary_key": "id;DROP TABLE"}, {"max_id": 0}])
def test_unverified_or_unsafe_range_is_rejected(change):
    item = {"table": "purchase_orders", "column": "created_at", "primary_key": "id", "min_id": 1, "max_id": 10,
            "source_timezone": "UTC", "evidence": "verified log", "reviewed": True, "sample": "2026-10-21T08:00:00"}
    with pytest.raises(ValueError):
        audit_module().build_report(CATALOG, [{**item, **change}])
