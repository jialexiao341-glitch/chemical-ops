"""迁移执行器：注释/空行过滤、分号拆分与 dry-run。"""

from scripts import apply_migration


def test_split_statements_drops_comments_and_blank_lines():
    sql = """-- 说明
CREATE TABLE a (
    id INT
);

-- 另一张表
CREATE TABLE b (
    id INT
);
"""

    statements = apply_migration.split_statements(sql)

    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE a")
    assert statements[1].startswith("CREATE TABLE b")
    assert all("说明" not in statement for statement in statements)


def test_split_handles_single_statement_without_trailing_semicolon():
    statements = apply_migration.split_statements("ALTER TABLE t ADD COLUMN c INT NULL")
    assert statements == ["ALTER TABLE t ADD COLUMN c INT NULL"]


def test_dry_run_prints_without_touching_engine(capsys):
    statements = ["CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)"]

    applied = apply_migration.apply(None, statements, dry_run=True)

    assert applied == 0
    out = capsys.readouterr().out
    assert "[1] CREATE TABLE a (id INT) ..." in out
    assert "[2] CREATE TABLE b (id INT) ..." in out