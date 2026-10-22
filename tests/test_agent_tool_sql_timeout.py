"""Agent tool SQL deadlines must interrupt database execution itself."""

from pathlib import Path
from types import SimpleNamespace
from time import monotonic

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.modules.ai import tool_sql_timeout
from app.modules.ai.tool_sql_timeout import (
    ToolExecutionTimeout,
    install_tool_sql_timeout_listeners,
    tool_deadline_context,
)


@pytest.fixture
def timeout_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    install_tool_sql_timeout_listeners(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def mysql8_engine():
    config = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    password = config.get("MYSQL_ROOT_PASSWORD")
    if not password:
        pytest.skip("MySQL 8.0 timeout integration credentials unavailable")
    engine = create_engine(URL.create(
        "mysql+pymysql", username="root", password=password,
        host=config.get("MYSQL_HOST", "127.0.0.1"),
        port=int(config.get("MYSQL_PORT", "3306")),
    ), connect_args={"connect_timeout": 2})
    install_tool_sql_timeout_listeners(engine)
    try:
        with engine.connect() as connection:
            version = connection.exec_driver_sql("SELECT VERSION()").scalar_one()
            if not str(version).startswith("8.0."):
                pytest.skip("MySQL 8.0 timeout integration server unavailable")
        yield engine
    except OperationalError as exc:
        if getattr(exc.orig, "args", (None,))[0] == 2003:
            pytest.skip("MySQL 8.0 timeout integration server unavailable")
        raise
    finally:
        engine.dispose()


def test_sqlite_short_query_completes_with_tool_deadline(timeout_engine):
    with tool_deadline_context(1.0), timeout_engine.connect() as connection:
        assert connection.execute(text("SELECT 7")).scalar_one() == 7


def test_agent_tool_timeout_setting_has_bounded_default():
    assert Settings(_env_file=None).agent_tool_timeout_seconds == 15
    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_tool_timeout_seconds=0)
    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_tool_timeout_seconds=61)


def test_expired_deadline_rejects_before_cursor_execute(timeout_engine):
    statements = []
    event.listen(
        timeout_engine,
        "before_cursor_execute",
        lambda _conn, _cursor, statement, *_args: statements.append(statement),
    )
    with tool_deadline_context(0.0), timeout_engine.connect() as connection:
        with pytest.raises(ToolExecutionTimeout):
            connection.execute(text("SELECT 7"))
    assert statements == []


def test_sqlite_tool_deadline_interrupts_long_query(timeout_engine):
    statement = text(
        "WITH RECURSIVE numbers(n) AS ("
        "SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < 100000000"
        ") SELECT sum(n) FROM numbers"
    )
    with tool_deadline_context(0.02), timeout_engine.connect() as connection:
        with pytest.raises(ToolExecutionTimeout):
            connection.execute(statement).scalar_one()


def test_queries_without_tool_context_are_unchanged(timeout_engine):
    with timeout_engine.connect() as connection:
        assert connection.execute(text("SELECT 11")).scalar_one() == 11


def test_mysql_hint_is_inserted_after_main_select_for_select_and_cte():
    context = SimpleNamespace(dialect=SimpleNamespace(name="mysql", driver="pymysql"))
    with tool_deadline_context(4.0):
        for statement in (
            "SELECT 1",
            "/* prefix */ WITH sample AS (SELECT 1) SELECT * FROM sample",
        ):
            rewritten, _parameters = tool_sql_timeout._before_cursor_execute(
                None, None, statement, None, context, False
            )
            assert "SELECT /*+ MAX_EXECUTION_TIME(" in rewritten
        assert rewritten.endswith("*/ * FROM sample")


def test_mysql_queries_share_one_tool_deadline(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(tool_sql_timeout, "monotonic", lambda: now[0])
    context = SimpleNamespace(dialect=SimpleNamespace(name="mysql", driver="pymysql"))

    with tool_deadline_context(10.0):
        first, _ = tool_sql_timeout._before_cursor_execute(
            None, None, "SELECT 1", None, context, False
        )
        now[0] += 3.0
        second, _ = tool_sql_timeout._before_cursor_execute(
            None, None, "SELECT 2", None, context, False
        )

    assert "MAX_EXECUTION_TIME(10000)" in first
    assert "MAX_EXECUTION_TIME(7000)" in second


def test_submillisecond_budget_rejects_before_execute(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(tool_sql_timeout, "monotonic", lambda: now[0])
    context = SimpleNamespace(dialect=SimpleNamespace(name="mysql", driver="pymysql"))
    with tool_deadline_context(0.0005):
        with pytest.raises(ToolExecutionTimeout):
            tool_sql_timeout._before_cursor_execute(
                None, None, "SELECT 1", None, context, False
            )


def test_unsupported_dialect_fails_closed():
    context = SimpleNamespace(dialect=SimpleNamespace(name="postgresql", driver="psycopg"))
    with tool_deadline_context(1.0):
        with pytest.raises(tool_sql_timeout.ToolTimeoutUnsupported):
            tool_sql_timeout._before_cursor_execute(
                None, None, "SELECT 1", None, context, False
            )


def test_mysql_unrecognized_statement_fails_closed():
    context = SimpleNamespace(dialect=SimpleNamespace(name="mysql", driver="pymysql"))
    with tool_deadline_context(1.0):
        with pytest.raises(tool_sql_timeout.ToolTimeoutUnsupported):
            tool_sql_timeout._before_cursor_execute(
                None, None, "UPDATE inventory SET quantity = 0", None, context, False
            )


def test_mysql_timeout_error_mapping_requires_deadline_and_server_timeout_code():
    deadline = tool_sql_timeout.monotonic() - 1
    context = SimpleNamespace(_chemicalops_timeout_mysql_deadline=deadline)
    timed_out = SimpleNamespace(
        execution_context=context,
        original_exception=RuntimeError(3024, "server interrupted"),
    )
    unrelated = SimpleNamespace(
        execution_context=context,
        original_exception=RuntimeError(2013, "connection lost"),
    )

    assert isinstance(tool_sql_timeout._handle_error(timed_out), ToolExecutionTimeout)
    assert tool_sql_timeout._handle_error(unrelated) is None


def test_mysql8_server_interrupts_over_budget_select(mysql8_engine):
    statement = text("SELECT BENCHMARK(500000000, SHA2('chemicalops', 256))")
    with mysql8_engine.connect() as connection:
        started = monotonic()
        with tool_deadline_context(1.0), pytest.raises(ToolExecutionTimeout):
            connection.execute(statement).scalar_one()
    assert monotonic() - started < 5.0


def test_sqlite_progress_handler_cleared_after_success_error_and_timeout(timeout_engine):
    long_query = text(
        "WITH RECURSIVE numbers(n) AS ("
        "SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < 100000000"
        ") SELECT sum(n) FROM numbers"
    )
    with timeout_engine.connect() as connection:
        with tool_deadline_context(1.0):
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
        with tool_deadline_context(1.0), pytest.raises(SQLAlchemyError):
            connection.execute(text("SELECT missing_column"))
        with tool_deadline_context(0.01), pytest.raises(ToolExecutionTimeout):
            connection.execute(long_query).scalar_one()
        assert connection.execute(text("SELECT 13")).scalar_one() == 13
