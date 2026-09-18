"""供应商退货数据模型。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class InventoryReturnRequest(Base):
    """供应商退货申请主单。"""

    __tablename__ = "inventory_return_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    return_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    delivery_id: Mapped[int | None] = mapped_column(ForeignKey("deliveries.id"), nullable=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))
    items: Mapped[list["InventoryReturnItem"]] = relationship(back_populates="request", cascade="all, delete-orphan", order_by="InventoryReturnItem.line_no")


class InventoryReturnItem(Base):
    """供应商退货申请明细。"""

    __tablename__ = "inventory_return_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    return_request_id: Mapped[int] = mapped_column(ForeignKey("inventory_return_requests.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))
    request: Mapped[InventoryReturnRequest] = relationship(back_populates="items")
