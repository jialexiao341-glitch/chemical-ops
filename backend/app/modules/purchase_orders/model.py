"""采购订单、审批记录和订单事件的数据模型。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class PurchaseOrder(Base):
    """采购订单主单。"""

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    source_comparison_id: Mapped[int | None] = mapped_column(ForeignKey("quote_comparisons.id"), nullable=True)
    source_quote_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_quotes.id"), nullable=True)
    source_request_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_requests.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("sys_departments.id"), nullable=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    order_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    delivery_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    supplier_confirmed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="PurchaseOrderItem.line_no"
    )
    approvals: Mapped[list["PurchaseOrderApproval"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="PurchaseOrderApproval.sequence_no"
    )
    events: Mapped[list["PurchaseOrderEvent"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="PurchaseOrderEvent.id"
    )


class PurchaseOrderItem(Base):
    """采购订单明细。"""

    __tablename__ = "purchase_order_items"
    __table_args__ = (UniqueConstraint("po_id", "line_no", name="uk_po_item_line"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    supplier_product_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_products.id"), nullable=True)
    source_quote_item_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_quote_items.id"), nullable=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    supplier_model_snapshot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    planned_arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    order: Mapped[PurchaseOrder] = relationship(back_populates="items")


class PurchaseOrderApproval(Base):
    """采购订单审批节点。"""

    __tablename__ = "purchase_order_approvals"
    __table_args__ = (UniqueConstraint("po_id", "sequence_no", name="uk_po_approval_sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    sequence_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    node_code: Mapped[str] = mapped_column(String(64), nullable=False)
    node_name: Mapped[str] = mapped_column(String(128), nullable=False)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    opinion: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    order: Mapped[PurchaseOrder] = relationship(back_populates="approvals")


class PurchaseOrderEvent(Base):
    """采购订单状态事件。"""

    __tablename__ = "purchase_order_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    event_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))

    order: Mapped[PurchaseOrder] = relationship(back_populates="events")
