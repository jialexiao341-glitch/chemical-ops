"""到货质量验收的数据模型。"""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, SmallInteger, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.modules.system.file_model import SysFile


class QualityAcceptance(Base):
    """一张到货单对应的质量验收记录。"""

    __tablename__ = "quality_acceptances"

    id: Mapped[int] = mapped_column(primary_key=True)
    acceptance_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"), nullable=False)
    inspector_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    inspection_time: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    test_result: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    certificate_complete: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    report_file_id: Mapped[int | None] = mapped_column(ForeignKey("sys_files.id"), nullable=True)
    conclusion: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )
