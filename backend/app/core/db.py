"""SQLAlchemy 引擎和请求级数据库会话依赖。"""

from collections.abc import Generator
import hashlib
import logging
import re
from time import perf_counter

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


settings = get_settings()
LOGGER = logging.getLogger("chemicalops.db")
engine = create_engine(
    settings.resolved_database_url,
    pool_pre_ping=True,
    pool_recycle=settings.db_pool_recycle,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    echo=settings.db_echo,
)


@event.listens_for(engine, "before_cursor_execute")
def _before_cursor_execute(connection, cursor, statement, parameters, context, executemany) -> None:
    """记录超过阈值的 SQL 摘要，不记录参数，避免敏感数据进入日志。"""

    context._chemicalops_query_started = perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def _after_cursor_execute(connection, cursor, statement, parameters, context, executemany) -> None:
    started = getattr(context, "_chemicalops_query_started", None)
    if started is None:
        return
    duration_ms = (perf_counter() - started) * 1000
    if duration_ms < settings.db_slow_query_ms:
        return
    compact_sql = re.sub(r"\s+", " ", str(statement)).strip()
    sql_kind = compact_sql.split(" ", 1)[0].upper() if compact_sql else "UNKNOWN"
    LOGGER.warning(
        "slow database query",
        extra={"event": "db_slow_query", "duration_ms": round(duration_ms, 2), "component": sql_kind, "sql_hash": hashlib.sha256(compact_sql.encode("utf-8")).hexdigest()[:16]},
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """每个 HTTP 请求创建一个 SQLAlchemy 会话，并在请求结束后关闭。"""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
