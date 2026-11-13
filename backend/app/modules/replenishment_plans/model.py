"""供应商补货数据模型。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ReplenishmentRequest(Base):
    """供应商补货申请主单。"""

    __tablename__ = "replenishment_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    replenishment_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    source_po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    source_delivery_id: Mapped[int | None] = mapped_column(ForeignKey("deliveries.id"), nullable=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    fulfillment_po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))
    items: Mapped[list["ReplenishmentItem"]] = relationship(back_populates="request", cascade="all, delete-orphan", order_by="ReplenishmentItem.line_no")


class ReplenishmentItem(Base):
    """供应商补货申请明细。"""

    __tablename__ = "replenishment_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    replenishment_request_id: Mapped[int] = mapped_column(ForeignKey("replenishment_requests.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))
    request: Mapped[ReplenishmentRequest] = relationship(back_populates="items")
