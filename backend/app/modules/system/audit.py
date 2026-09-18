"""系统审计日志的最小写入服务。"""

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """记录用户对业务资源的关键操作。"""

    __tablename__ = "sys_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(nullable=True)
    request_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_status: Mapped[str] = mapped_column(String(20), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )


def add_audit_log(
    db: Session,
    *,
    actor_id: int | None,
    action_type: str,
    resource_type: str,
    resource_id: int | None,
    request_summary: str,
    result_status: str,
) -> AuditLog:
    """向当前事务追加一条审计日志，不单独提交事务。"""

    log = AuditLog(
        actor_id=actor_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        request_summary=request_summary,
        result_status=result_status,
    )
    db.add(log)
    return log
