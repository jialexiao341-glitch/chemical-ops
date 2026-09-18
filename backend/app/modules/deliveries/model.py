"""到货记录和到货明细的数据模型。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Delivery(Base):
    """供应商到货记录。"""

    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    shipment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    logistics_company: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="IN_TRANSIT")
    received_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    items: Mapped[list["DeliveryItem"]] = relationship(
        back_populates="delivery", cascade="all, delete-orphan", order_by="DeliveryItem.line_no"
    )


class DeliveryItem(Base):
    """到货明细。"""

    __tablename__ = "delivery_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"), nullable=False)
    po_item_id: Mapped[int] = mapped_column(ForeignKey("purchase_order_items.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    batch_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_spec: Mapped[str | None] = mapped_column(String(255), nullable=True)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    actual_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    short_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    production_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_complete: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    delivery: Mapped[Delivery] = relationship(back_populates="items")
