"""财务对账、发票、付款和结算的数据模型。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Computed, JSON, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
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
    items_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_precision: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
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
    __table_args__ = (UniqueConstraint("active_reconciliation_id", name="uk_finance_settlement_reconciliation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    settlement_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("finance_reconciliations.id"), nullable=False)
    active_reconciliation_id: Mapped[int | None] = mapped_column(
        Computed("CASE WHEN status <> 'CANCELLED' THEN reconciliation_id ELSE NULL END", persisted=True),
    )
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


class FinanceReconciliationItem(Base):
    """按版本追加保存的订单行对账依据，不改写旧版本。"""
    __tablename__ = "finance_reconciliation_items"
    __table_args__ = (UniqueConstraint("reconciliation_id", "version_no", "po_item_id", name="uk_finance_rec_item_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("finance_reconciliations.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    po_item_id: Mapped[int] = mapped_column(ForeignKey("purchase_order_items.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_name: Mapped[str] = mapped_column(String(64), nullable=False)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    accepted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    reconciliation_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    amount_excl_tax: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    amount_incl_tax: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    return_treatment: Mapped[str] = mapped_column(String(20), nullable=False)
    treatment_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    basis_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class FinanceInvoiceMatch(Base):
    """人工匹配的追加式版本；正式发票状态负责提交和双人复核。"""
    __tablename__ = "finance_invoice_matches"
    __table_args__ = (UniqueConstraint("invoice_id", "version_no", name="uk_invoice_match_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("finance_invoices.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    reconciliation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    allocations: Mapped[list] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
