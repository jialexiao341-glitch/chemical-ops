from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import Boolean
from sqlalchemy.dialects.mysql import TINYINT

from scripts import migrate_database


ROOT = Path(__file__).resolve().parents[1]


class _Connection:
    dialect = SimpleNamespace(name="mysql")

    def __init__(self):
        self.statements = []
        self.commits = 0

    def exec_driver_sql(self, statement):
        self.statements.append(statement)

    def commit(self):
        self.commits += 1


def _column(nullable=False, default="0", data_type=None):
    return {
        "name": "pinned",
        "type": data_type or TINYINT(display_width=1),
        "nullable": nullable,
        "default": default,
    }


def _inspect_columns(monkeypatch, columns):
    monkeypatch.setattr(
        migrate_database,
        "inspect",
        lambda _connection: SimpleNamespace(
            has_table=lambda _table: True,
            get_columns=lambda _table: columns,
        ),
    )


def test_025_adds_pinned_for_legacy_database(monkeypatch):
    _inspect_columns(monkeypatch, [])
    connection = _Connection()
    migration = next(item for item in migrate_database._migration_files() if item.version == "025")

    migrate_database._apply_migration(connection, migration)

    assert len(connection.statements) == 1
    assert "ADD COLUMN pinned TINYINT(1) NOT NULL DEFAULT 0" in connection.statements[0]
    assert connection.commits == 1


def test_025_accepts_matching_pinned_from_fresh_schema(monkeypatch):
    _inspect_columns(monkeypatch, [_column()])
    connection = _Connection()
    migration = next(item for item in migrate_database._migration_files() if item.version == "025")

    migrate_database._apply_migration(connection, migration)

    assert connection.statements == []
    assert connection.commits == 0


def test_fresh_schema_and_orm_define_the_migration_contract():
    from app.modules.ai.model import AIConversation

    schema = (ROOT / "database/schema.sql").read_text(encoding="utf-8")
    conversation_table = schema.split("CREATE TABLE ai_conversations (", 1)[1].split(
        ") ENGINE=InnoDB", 1
    )[0]
    assert "pinned TINYINT(1) NOT NULL DEFAULT 0" in conversation_table

    pinned = AIConversation.__table__.c.pinned
    assert isinstance(pinned.type, Boolean)
    assert not pinned.nullable
    assert str(pinned.server_default.arg) == "0"


@pytest.mark.parametrize(
    "column",
    [
        _column(nullable=True),
        _column(default="1"),
        _column(data_type=TINYINT(display_width=2)),
    ],
)
def test_025_rejects_conflicting_existing_pinned_schema(monkeypatch, column):
    _inspect_columns(monkeypatch, [column])
    connection = _Connection()
    migration = next(item for item in migrate_database._migration_files() if item.version == "025")

    with pytest.raises(RuntimeError, match="Schema conflict"):
        migrate_database._apply_migration(connection, migration)

    assert connection.statements == []


def test_ci_audit_uses_npm_registry_and_keeps_high_threshold():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "pnpm audit --audit-level high --registry=https://registry.npmjs.org/" in workflow
    assert "pnpm/action-setup@v4" in workflow
    assert "version: 11.16.0" in workflow
