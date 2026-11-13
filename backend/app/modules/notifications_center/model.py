"""站内通知数据库模型。"""

from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Notification(Base):
    """发送给系统用户的站内通知。"""

    __tablename__ = "sys_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    related_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_id: Mapped[int | None] = mapped_column(nullable=True)
    is_read: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    read_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
