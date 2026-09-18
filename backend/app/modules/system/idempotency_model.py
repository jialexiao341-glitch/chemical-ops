"""统一幂等请求记录模型。"""

from datetime import datetime

from sqlalchemy import JSON, SmallInteger, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IdempotencyRecord(Base):
    """保存首次请求结果，用于安全回放。"""
    __tablename__ = "sys_idempotency_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="IN_PROGRESS")
    response_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    response_body: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False)
