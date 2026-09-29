"""到货质量验收的数据模型。"""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.modules.system.file_model import SysFile


class QualityAcceptance(Base):
    """一张到货单对应的质量验收记录。"""

    __tablename__ = "quality_acceptances"
    __table_args__ = (UniqueConstraint("delivery_id", name="uk_acceptance_delivery"),)

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


class QualityInspectionStandard(Base):
    """产品检测标准的不可变版本。"""

    __tablename__ = "quality_inspection_standards"
    __table_args__ = (UniqueConstraint("product_id", "version_no", name="uk_quality_standard_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    criteria: Mapped[list] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class QualityReportReviewRecord(Base):
    """一次报告核对的结果快照与人工复核意见。"""

    __tablename__ = "quality_report_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    acceptance_id: Mapped[int] = mapped_column(ForeignKey("quality_acceptances.id"), nullable=False)
    delivery_item_id: Mapped[int] = mapped_column(ForeignKey("delivery_items.id"), nullable=False)
    file_id: Mapped[int] = mapped_column(ForeignKey("sys_files.id"), nullable=False)
    standard_id: Mapped[int | None] = mapped_column(ForeignKey("quality_inspection_standards.id"), nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    reviewer_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)


class QualityReviewCorrection(Base):
    """检测项修正过程中的追加式处理记录。"""

    __tablename__ = "quality_review_corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("quality_report_reviews.id"), nullable=False)
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str] = mapped_column(String(2000), nullable=False)
    actor_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
