"""采购申请及审批记录的数据模型。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Unit(Base):
    """计量单位字典的最小模型。"""

    __tablename__ = "md_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_code: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_name: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")


class PurchaseRequest(Base):
    """采购申请主单。"""

    __tablename__ = "purchase_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("sys_departments.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(1000), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    items: Mapped[list["PurchaseRequestItem"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="PurchaseRequestItem.line_no"
    )
    approvals: Mapped[list["PurchaseRequestApproval"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="PurchaseRequestApproval.sequence_no"
    )


class PurchaseRequestItem(Base):
    """采购申请明细。"""

    __tablename__ = "purchase_request_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("purchase_requests.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("md_products.id"), nullable=True)
    requested_name: Mapped[str] = mapped_column(String(255), nullable=False)
    technical_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    budget_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fulfilled_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    request: Mapped[PurchaseRequest] = relationship(back_populates="items")


class PurchaseRequestApproval(Base):
    """采购申请审批节点记录。"""

    __tablename__ = "purchase_request_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("purchase_requests.id"), nullable=False)
    sequence_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    node_code: Mapped[str] = mapped_column(String(64), nullable=False)
    node_name: Mapped[str] = mapped_column(String(128), nullable=False)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    opinion: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    request: Mapped[PurchaseRequest] = relationship(back_populates="approvals")
