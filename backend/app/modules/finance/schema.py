"""财务模块请求和响应模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReconciliationCreate(BaseModel):
    """创建对账单时提交的字段。"""

    po_id: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


class ReconciliationAction(BaseModel):
    """对账确认、取消或争议处理时提交的说明。"""

    reason: str | None = Field(default=None, max_length=1000)


class ReconciliationRead(BaseModel):
    """对账单响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    reconciliation_no: str
    po_id: int
    supplier_id: int
    currency_code: str
    items_version: int
    amount_precision: int
    total_amount: Decimal
    status: str
    created_by: int
    confirmed_by: int | None
    confirmed_at: datetime | None
    closed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class ReconciliationPage(BaseModel):
    """对账单分页响应。"""

    items: list[ReconciliationRead]
    total: int
    page: int
    page_size: int


class InvoiceCreate(BaseModel):
    """录入发票时提交的字段。"""

    reconciliation_id: int = Field(gt=0)
    invoice_code: str | None = Field(default=None, max_length=32)
    invoice_number: str = Field(min_length=1, max_length=64)
    invoice_date: date
    amount_excl_tax: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    tax_amount: Decimal = Field(default=0, ge=0, max_digits=18, decimal_places=6)
    amount_incl_tax: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    source_file_id: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)


class InvoiceReject(BaseModel):
    """驳回发票时提交的原因。"""

    reason: str = Field(min_length=1, max_length=1000)


class InvoiceRead(BaseModel):
    """发票响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_no: str
    reconciliation_id: int
    po_id: int
    supplier_id: int
    invoice_code: str | None
    invoice_number: str
    invoice_date: date
    amount_excl_tax: Decimal
    tax_amount: Decimal
    amount_incl_tax: Decimal
    currency_code: str
    status: str
    source_file_id: int | None
    submitted_by: int
    verified_by: int | None
    verified_at: datetime | None
    reject_reason: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class InvoicePage(BaseModel):
    """发票分页响应。"""

    items: list[InvoiceRead]
    total: int
    page: int
    page_size: int


class PaymentCreate(BaseModel):
    """发起付款申请时提交的字段。"""

    reconciliation_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0)
    payment_method: str = Field(pattern="^(BANK_TRANSFER|CASH|OTHER)$")
    note: str | None = Field(default=None, max_length=1000)


class PaymentReject(BaseModel):
    """驳回付款申请时提交的原因。"""

    reason: str = Field(min_length=1, max_length=1000)


class PaymentPaid(BaseModel):
    """人工登记付款结果时提交的外部流水号或凭证号。"""

    transaction_ref: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=1000)


class PaymentRead(BaseModel):
    """付款响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_no: str
    reconciliation_id: int
    po_id: int
    supplier_id: int
    amount: Decimal
    currency_code: str
    payment_method: str
    status: str
    requested_by: int
    approved_by: int | None
    paid_by: int | None
    approved_at: datetime | None
    paid_at: datetime | None
    transaction_ref: str | None
    reject_reason: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class PaymentPage(BaseModel):
    """付款分页响应。"""

    items: list[PaymentRead]
    total: int
    page: int
    page_size: int


class SettlementCreate(BaseModel):
    """创建结算单时提交的字段。"""

    reconciliation_id: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


class SettlementCancel(BaseModel):
    """取消结算单时提交的原因。"""

    reason: str = Field(min_length=1, max_length=1000)


class SettlementRead(BaseModel):
    """结算单响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    settlement_no: str
    reconciliation_id: int
    po_id: int
    supplier_id: int
    settlement_amount: Decimal
    currency_code: str
    status: str
    created_by: int
    confirmed_by: int | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class SettlementPage(BaseModel):
    """结算单分页响应。"""

    items: list[SettlementRead]
    total: int
    page: int
    page_size: int


class ReconciliationItemDecision(BaseModel):
    po_item_id: int = Field(gt=0)
    return_treatment: str = Field(pattern="^(NONE|PENDING|DEDUCT|REPLACEMENT)$")
    treatment_note: str | None = Field(default=None, max_length=1000)


class ReconciliationItemsRefresh(BaseModel):
    amount_precision: int = Field(default=2, ge=0, le=6)
    decisions: list[ReconciliationItemDecision] = Field(default_factory=list, max_length=100)


class ReconciliationItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version_no: int
    po_item_id: int
    line_no: int
    product_name: str
    unit_name: str
    ordered_quantity: Decimal
    received_quantity: Decimal
    accepted_quantity: Decimal
    returned_quantity: Decimal
    reconciliation_quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    amount_excl_tax: Decimal
    tax_amount: Decimal
    amount_incl_tax: Decimal
    return_treatment: str
    treatment_note: str | None
    basis_json: dict
    warnings: list[str]
    created_by: int
    created_at: datetime


class ReconciliationItemsRead(BaseModel):
    reconciliation_id: int
    version_no: int
    available_versions: list[int]
    amount_precision: int
    currency_code: str
    total_amount: Decimal
    source_changed: bool
    warnings: list[str]
    items: list[ReconciliationItemRead]


class InvoiceAllocation(BaseModel):
    reconciliation_item_id: int = Field(gt=0)
    amount_excl_tax: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    tax_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    difference_note: str | None = Field(default=None, max_length=1000)


class InvoiceMatchSave(BaseModel):
    reconciliation_version: int = Field(gt=0)
    allocations: list[InvoiceAllocation] = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=1000)


class InvoiceMatchVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version_no: int
    reconciliation_version: int
    allocations: list[dict]
    note: str | None
    created_by: int
    created_at: datetime


class InvoiceMatchRead(BaseModel):
    invoice_id: int
    reconciliation_version: int
    source_changed: bool
    legacy: bool
    warnings: list[str]
    items: list[dict]
    versions: list[InvoiceMatchVersionRead]
