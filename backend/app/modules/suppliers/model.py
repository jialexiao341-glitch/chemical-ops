"""suppliers 供应商表的数据库模型。"""

from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Supplier(Base):
    """采购流程使用的供应商主档案。"""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unified_credit_code: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="CN")
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    business_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    cooperation_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_lead_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )
