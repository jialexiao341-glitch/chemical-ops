"""文件元数据表的最小模型，供业务表建立外键关联。"""

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SysFile(Base):
    """文件元数据，不包含文件二进制内容。"""

    __tablename__ = "sys_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_category: Mapped[str] = mapped_column(String(32), nullable=False)
    access_level: Mapped[str] = mapped_column(String(20), nullable=False, default="INTERNAL")
    uploader_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_STARTED")
    parse_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    expires_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )


class SysFileAttachment(Base):
    """业务对象与文件的关联记录。"""

    __tablename__ = "sys_file_attachments"
    __table_args__ = (UniqueConstraint("resource_type", "resource_id", "file_id", name="uk_file_attachment_resource"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("sys_files.id"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[int] = mapped_column(nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
