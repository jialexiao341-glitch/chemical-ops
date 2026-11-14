"""校验 051/055/056 增量迁移对 schema.sql 空库基线及旧库升级的幂等兼容性。"""

from types import SimpleNamespace

import pytest

from scripts import migrate_database


class _Connection:
    dialect = SimpleNamespace(name="mysql")

    def __init__(self):
        self.statements: list[str] = []
        self.commits = 0

    def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)

    def commit(self) -> None:
        self.commits += 1


def _migration(version: str):
    return next(item for item in migrate_database._migration_files() if item.version == version)


def _cols(*names: str, nullable_map: dict[str, bool] | None = None) -> list[dict]:
    nulls = nullable_map or {}
    return [{"name": name, "nullable": nulls.get(name, True)} for name in names]


def test_051_accepts_existing_table_from_fresh_schema(monkeypatch):
    """空库 schema.sql 已含完整 ai_purchase_draft_confirmations 表时应幂等跳过建表。"""

    expected_cols = _cols(
        "id", "confirmation_id", "user_id", "preview_version", "request_hash",
        "draft_payload", "object_versions", "evidence", "status", "expires_at",
        "purchase_request_id", "result", "created_at", "executed_at",
    )
    monkeypatch.setattr(
        migrate_database,
        "inspect",
        lambda _conn: SimpleNamespace(
            has_table=lambda table: table == "ai_purchase_draft_confirmations",
            get_columns=lambda _table: expected_cols,
        ),
    )
    connection = _Connection()

    migrate_database._apply_migration(connection, _migration("051"))

    assert connection.statements == []


def test_051_rejects_partial_existing_table(monkeypatch):
    """若 051 表已存在但缺少关键列，应显式报错拒绝跳过。"""

    monkeypatch.setattr(
        migrate_database,
        "inspect",
        lambda _conn: SimpleNamespace(
            has_table=lambda _table: True,
            get_columns=lambda _table: _cols("id", "confirmation_id"),
        ),
    )

    with pytest.raises(RuntimeError, match="Schema conflict"):
        migrate_database._apply_migration(_Connection(), _migration("051"))


def test_055_skips_ddl_on_fresh_schema_and_keeps_legacy_path(monkeypatch):
    """055 在 schema.sql 已具字段时跳过重复 ALTER，但在旧库缺失字段时完整执行 DDL。"""

    tables = {
        "supplier_quote_items": _cols("id", "tax_included"),
        "quote_comparison_items": _cols(
            "quoted_unit_price", "currency_code", "unit_id", "tax_rate",
            "tax_included", "comparison_status", "comparison_reasons",
            nullable_map={"quoted_unit_price": True},
        ),
    }
    monkeypatch.setattr(
        migrate_database,
        "inspect",
        lambda _conn: SimpleNamespace(get_columns=lambda table: tables[table]),
    )
    connection = _Connection()

    migrate_database._apply_migration(connection, _migration("055"))

    assert len(connection.statements) == 2
    assert all(stmt.startswith("UPDATE ") for stmt in connection.statements)

    tables["supplier_quote_items"] = _cols("id", "tax_rate")
    tables["quote_comparison_items"] = _cols("quoted_unit_price", nullable_map={"quoted_unit_price": False})
    legacy_conn = _Connection()
    migrate_database._apply_migration(legacy_conn, _migration("055"))
    assert len(legacy_conn.statements) == 4
    assert legacy_conn.statements[0].startswith("ALTER TABLE supplier_quote_items")
    assert legacy_conn.statements[1].startswith("ALTER TABLE quote_comparison_items")


def test_056_skips_matching_schema_and_repairs_missing_constraint(monkeypatch):
    """056 在 schema.sql 已完整含列和约束时跳过；若仅缺检查约束则只补约束。"""

    tables = {
        "supplier_quote_items": _cols("freight_amount", "freight_tax_rate", "freight_tax_included"),
        "quote_comparison_items": _cols("freight_amount", "freight_tax_rate", "freight_tax_included", "analysis_json"),
    }
    monkeypatch.setattr(
        migrate_database,
        "inspect",
        lambda _conn: SimpleNamespace(get_columns=lambda table: tables[table]),
    )
    constraint_clause = "(freight_amount is null or freight_amount >= 0) and (freight_tax_rate is null or freight_tax_rate between 0 and 100)"
    monkeypatch.setattr(migrate_database, "_check_constraint_clause", lambda *_args: constraint_clause)
    clean_conn = _Connection()

    migrate_database._apply_migration(clean_conn, _migration("056"))
    assert clean_conn.statements == []

    monkeypatch.setattr(migrate_database, "_check_constraint_clause", lambda *_args: None)
    repair_conn = _Connection()
    migrate_database._apply_migration(repair_conn, _migration("056"))
    assert len(repair_conn.statements) == 1
    assert "ADD CONSTRAINT chk_quote_item_freight" in repair_conn.statements[0]
