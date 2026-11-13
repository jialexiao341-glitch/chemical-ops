"""数据库级 Agent 工具 SQL 截止时间。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from math import ceil
import sqlite3
from time import monotonic
from typing import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine


_task_deadline: ContextVar[float | None] = ContextVar("agent_task_deadline", default=None)
_tool_deadline: ContextVar[float | None] = ContextVar("agent_tool_deadline", default=None)


class ToolExecutionTimeout(TimeoutError):
    """Agent 工具的数据库截止时间已到。"""


class ToolTimeoutUnsupported(RuntimeError):
    """当前 SQLAlchemy 方言没有安全的工具 SQL 中断机制。"""


def current_task_deadline() -> float | None:
    return _task_deadline.get()


def current_tool_deadline() -> float | None:
    return _tool_deadline.get()


@contextmanager
def agent_task_deadline_context(timeout_seconds: float) -> Iterator[float]:
    """建立可由线程卸载中的工具继承的任务级绝对截止时间。"""

    deadline = monotonic() + max(0.0, timeout_seconds)
    parent = current_task_deadline()
    if parent is not None:
        deadline = min(deadline, parent)
    token = _task_deadline.set(deadline)
    try:
        yield deadline
    finally:
        _task_deadline.reset(token)


@contextmanager
def tool_deadline_context(
    timeout_seconds: float,
    parent_deadline: float | None = None,
) -> Iterator[float]:
    """建立单次工具调用的绝对截止时间，不随每条 SQL 重置。"""

    deadline = monotonic() + max(0.0, timeout_seconds)
    candidates = (parent_deadline, current_task_deadline())
    deadlines = [deadline, *(value for value in candidates if value is not None)]
    deadline = min(deadlines)
    token = _tool_deadline.set(deadline)
    try:
        yield deadline
    finally:
        _tool_deadline.reset(token)


def _remaining_ms(deadline: float) -> int:
    remaining_seconds = deadline - monotonic()
    if remaining_seconds < 0.001:
        raise ToolExecutionTimeout("Agent 工具 SQL 已超过执行时限")
    return ceil(remaining_seconds * 1000)


def _sqlite_connection(cursor) -> sqlite3.Connection:
    connection = getattr(cursor, "connection", None)
    if not isinstance(connection, sqlite3.Connection):
        raise ToolTimeoutUnsupported("无法取得 SQLite 原生连接以中断工具 SQL")
    return connection


def _clear_sqlite_handler(context) -> None:
    connection = getattr(context, "_chemicalops_timeout_connection", None)
    if connection is None:
        return
    try:
        connection.set_progress_handler(None, 0)
    finally:
        context._chemicalops_timeout_connection = None


def _skip_sql_trivia(statement: str, offset: int) -> int:
    """跳过空白与 SQL 注释，返回下一个有效字符的位置。"""

    length = len(statement)
    while offset < length:
        if statement[offset].isspace():
            offset += 1
        elif statement.startswith("/*", offset):
            end = statement.find("*/", offset + 2)
            if end < 0:
                return length
            offset = end + 2
        elif statement.startswith("--", offset) or statement[offset] == "#":
            newline = statement.find("\n", offset + 1)
            offset = length if newline < 0 else newline + 1
        else:
            break
    return offset


def _main_select_span(statement: str) -> tuple[int, int] | None:
    """仅接受普通 SELECT 或 WITH ... SELECT，并定位顶层 SELECT 关键字。"""

    offset = _skip_sql_trivia(statement, 0)
    first_word = None
    depth = 0
    select_span = None
    index = offset
    while index < len(statement):
        char = statement[index]
        if char in "'\"`":
            quote = char
            index += 1
            while index < len(statement):
                if statement[index] == "\\":
                    index += 2
                    continue
                if statement[index] == quote:
                    if index + 1 < len(statement) and statement[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if statement.startswith("/*", index):
            end = statement.find("*/", index + 2)
            if end < 0:
                return None
            index = end + 2
            continue
        if statement.startswith("--", index) or char == "#":
            newline = statement.find("\n", index + 1)
            index = len(statement) if newline < 0 else newline + 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        if char == ";" and depth == 0:
            if _skip_sql_trivia(statement, index + 1) != len(statement):
                return None
            break
        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(statement) and (statement[index].isalnum() or statement[index] in "_$"):
                index += 1
            word = statement[start:index].upper()
            if first_word is None:
                first_word = word
            if depth == 0 and word == "SELECT":
                select_span = (start, index)
                break
            continue
        index += 1
    if first_word not in {"SELECT", "WITH"}:
        return None
    return select_span


def _before_cursor_execute(connection, cursor, statement, parameters, context, executemany) -> tuple[str, object]:
    del connection, executemany
    deadline = current_tool_deadline()
    if deadline is None:
        return statement, parameters
    remaining_ms = _remaining_ms(deadline)
    dialect = context.dialect
    if dialect.name == "sqlite":
        dbapi_connection = _sqlite_connection(cursor)
        context._chemicalops_timeout_connection = dbapi_connection
        context._chemicalops_timeout_expired = False

        def interrupt_if_expired() -> int:
            if monotonic() >= deadline:
                context._chemicalops_timeout_expired = True
                return 1
            return 0

        dbapi_connection.set_progress_handler(interrupt_if_expired, 1000)
        return statement, parameters
    if dialect.name == "mysql" and dialect.driver == "pymysql":
        span = _main_select_span(statement)
        if span is None:
            raise ToolTimeoutUnsupported("无法安全识别 Agent 工具的 MySQL SELECT 主查询")
        context._chemicalops_timeout_mysql_deadline = deadline
        context._chemicalops_timeout_remaining_ms = remaining_ms
        select_end = span[1]
        hint = f" /*+ MAX_EXECUTION_TIME({remaining_ms}) */"
        return statement[:select_end] + hint + statement[select_end:], parameters
    raise ToolTimeoutUnsupported(f"数据库方言 {dialect.name}+{dialect.driver} 暂不支持 Agent 工具 SQL 超时")


def _after_cursor_execute(connection, cursor, statement, parameters, context, executemany) -> None:
    del connection, cursor, statement, parameters, executemany
    _clear_sqlite_handler(context)
    deadline = current_tool_deadline()
    if deadline is not None and monotonic() >= deadline:
        raise ToolExecutionTimeout("Agent 工具 SQL 已超过执行时限")


def _handle_error(exception_context):
    execution_context = exception_context.execution_context
    if execution_context is None:
        return None
    was_sqlite_timeout = getattr(execution_context, "_chemicalops_timeout_expired", False)
    deadline = getattr(execution_context, "_chemicalops_timeout_mysql_deadline", None)
    dbapi_error = exception_context.original_exception
    is_mysql_timeout = (
        deadline is not None
        and monotonic() >= deadline
        and getattr(dbapi_error, "args", ())
        and dbapi_error.args[0] == 3024
    )
    _clear_sqlite_handler(execution_context)
    if was_sqlite_timeout or is_mysql_timeout:
        return ToolExecutionTimeout("Agent 工具 SQL 已超过执行时限")
    return None


def install_tool_sql_timeout_listeners(engine: Engine) -> None:
    """为 Engine 安装只在工具截止时间上下文中启用的 SQL 中断处理器。"""

    if not event.contains(engine, "before_cursor_execute", _before_cursor_execute):
        event.listen(engine, "before_cursor_execute", _before_cursor_execute, retval=True)
    if not event.contains(engine, "after_cursor_execute", _after_cursor_execute):
        event.listen(engine, "after_cursor_execute", _after_cursor_execute)
    if not event.contains(engine, "handle_error", _handle_error):
        event.listen(engine, "handle_error", _handle_error, retval=True)
