"""md_products 产品表的数据库模型。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, JSON, Numeric, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Product(Base):
    """关联化学品的可采购产品规格。"""

    __tablename__ = "md_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    chemical_id: Mapped[int] = mapped_column(ForeignKey("md_chemicals.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("md_product_categories.id"), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    purity_value: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    purity_unit: Mapped[str | None] = mapped_column(String(20), nullable=True, default="%")
    packaging_spec: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    safety_stock_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    parameter_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )
