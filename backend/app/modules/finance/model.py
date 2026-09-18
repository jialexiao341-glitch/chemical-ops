"""财务对账、发票、付款和结算的数据模型。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FinanceReconciliation(Base):
    """采购订单财务对账主单。"""

    __tablename__ = "finance_reconciliations"

    id: Mapped[int] = mapped_column(primary_key=True)
    reconciliation_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False, unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    created_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))


class FinanceInvoice(Base):
    """供应商发票记录。"""

    __tablename__ = "finance_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("finance_reconciliations.id"), nullable=False)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    invoice_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_excl_tax: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    amount_incl_tax: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("sys_files.id"), nullable=True)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))


class FinancePayment(Base):
    """付款申请和付款结果记录。"""

    __tablename__ = "finance_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("finance_reconciliations.id"), nullable=False)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="REQUESTED")
    requested_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    paid_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    transaction_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    reject_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))


class FinanceSettlement(Base):
    """采购结算单。"""

    __tablename__ = "finance_settlements"

    id: Mapped[int] = mapped_column(primary_key=True)
    settlement_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("finance_reconciliations.id"), nullable=False, unique=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    settlement_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    created_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))
