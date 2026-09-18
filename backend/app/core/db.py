"""SQLAlchemy 引擎和请求级数据库会话依赖。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


settings = get_settings()
engine = create_engine(
    settings.resolved_database_url,
    pool_pre_ping=True,
    pool_recycle=settings.db_pool_recycle,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    echo=settings.db_echo,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """每个 HTTP 请求创建一个 SQLAlchemy 会话，并在请求结束后关闭。"""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
