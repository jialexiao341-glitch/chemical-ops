"""供应商可供产品关系的最小模型，供报价明细建立外键关联。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SupplierProduct(Base):
    """供应商可供产品关系。"""

    __tablename__ = "supplier_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    supplier_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    supplied_purity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    moq_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    moq_unit_id: Mapped[int | None] = mapped_column(ForeignKey("md_units.id"), nullable=True)
    standard_lead_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capacity_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )
