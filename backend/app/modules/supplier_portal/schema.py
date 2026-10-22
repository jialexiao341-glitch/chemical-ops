"""供应商门户接口响应模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SupplierOrderItemRead(BaseModel):
    """供应商可见的订单明细，不包含内部审批或来源记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    product_name_snapshot: str
    supplier_model_snapshot: str | None
    order_quantity: Decimal
    unit_id: int
    unit_price: Decimal
    tax_rate: Decimal | None
    tax_included: bool | None
    planned_arrival_date: date | None
    received_quantity: Decimal
    status: str


class SupplierOrderRead(BaseModel):
    """供应商履约所需的采购订单字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    po_no: str
    order_amount: Decimal
    currency_code: str
    delivery_address: str | None
    order_date: date | None
    expected_arrival_date: date | None
    status: str
    supplier_confirmed_at: datetime | None
    items: list[SupplierOrderItemRead]


class SupplierOrderPage(BaseModel):
    """供应商订单分页响应。"""

    items: list[SupplierOrderRead]
    total: int
    page: int
    page_size: int


class SupplierOrderReject(BaseModel):
    """供应商拒绝订单时提交的原因。"""
    reason: str = Field(min_length=1, max_length=1000)


class SupplierRFQItemRead(BaseModel):
    """供应商可见的询价明细，不暴露内部申请和产品主数据 ID。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    requested_name: str
    specification: str | None
    quantity: Decimal
    unit_id: int
    required_delivery_date: date | None
    technical_requirements: str | None


class SupplierRFQListItem(BaseModel):
    """当前供应商收到的一条询价邀请。"""

    id: int
    rfq_no: str
    item_count: int
    item_summary: str
    quote_deadline: datetime | None
    requested_delivery_date: date | None
    delivery_requirements: str | None
    status: str
    response_status: str
    invited_at: datetime
    response_at: datetime | None


class SupplierRFQPage(BaseModel):
    items: list[SupplierRFQListItem]
    total: int
    page: int
    page_size: int


class SupplierPortalQuoteItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rfq_item_id: int
    supplier_model: str | None
    quoted_quantity: Decimal
    unit_id: int
    unit_price: Decimal
    tax_rate: Decimal | None
    moq_quantity: Decimal | None
    moq_unit_id: int | None
    lead_days: int | None
    payment_terms: str | None
    note: str | None


class SupplierPortalQuoteRead(BaseModel):
    """仅返回当前供应商自己的最新报价版本。"""

    quote_no: str
    quote_version: int
    quote_date: date
    valid_until: date | None
    currency_code: str
    status: str
    note: str | None
    created_at: datetime
    items: list[SupplierPortalQuoteItemRead]


class SupplierRFQDetail(SupplierRFQListItem):
    items: list[SupplierRFQItemRead]
    latest_quote: SupplierPortalQuoteRead | None


class SupplierPortalQuoteItemCreate(BaseModel):
    rfq_item_id: int = Field(gt=0)
    supplier_model: str | None = Field(default=None, max_length=128)
    quoted_quantity: Decimal = Field(gt=0)
    unit_id: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    tax_included: bool | None = None
    moq_quantity: Decimal | None = Field(default=None, gt=0)
    moq_unit_id: int | None = Field(default=None, gt=0)
    lead_days: int | None = Field(default=None, ge=0)
    payment_terms: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=1000)


class SupplierPortalQuoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_date: date | None = None
    valid_until: date | None = None
    currency_code: str = Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    note: str | None = Field(default=None, max_length=1000)
    items: list[SupplierPortalQuoteItemCreate] = Field(min_length=1, max_length=100)


class SupplierDeliveryDateUpdate(BaseModel):
    expected_date: date
    note: str | None = Field(default=None, max_length=1000)


class SupplierDeliveryUpdateRead(BaseModel):
    id: int
    po_id: int
    po_no: str
    previous_date: date | None
    expected_date: date
    note: str | None
    submitted_at: datetime


class SupplierDeliveryUpdatePage(BaseModel):
    items: list[SupplierDeliveryUpdateRead]
    total: int
    page: int
    page_size: int


class SupplierShipmentItemCreate(BaseModel):
    po_item_id: int = Field(gt=0)
    planned_quantity: Decimal = Field(gt=0)
    batch_no: str | None = Field(default=None, max_length=128)
    package_spec: str | None = Field(default=None, max_length=255)
    production_date: date | None = None
    expiry_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class SupplierShipmentCreate(BaseModel):
    po_id: int = Field(gt=0)
    shipment_date: date | None = None
    expected_arrival_date: date | None = None
    logistics_company: str | None = Field(default=None, max_length=128)
    tracking_no: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=1000)
    items: list[SupplierShipmentItemCreate] = Field(min_length=1, max_length=100)


class SupplierShipmentItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    line_no: int
    po_item_id: int
    batch_no: str | None
    planned_quantity: Decimal
    unit_id: int


class SupplierShipmentRead(BaseModel):
    id: int
    delivery_no: str
    po_id: int
    po_no: str
    shipment_date: date | None
    expected_arrival_date: date | None
    logistics_company: str | None
    tracking_no: str | None
    status: str
    note: str | None
    created_at: datetime
    items: list[SupplierShipmentItemRead]


class SupplierShipmentPage(BaseModel):
    items: list[SupplierShipmentRead]
    total: int
    page: int
    page_size: int


class SupplierQualityDocumentRead(BaseModel):
    id: int
    document_no: str
    po_id: int
    po_no: str
    po_item_id: int | None
    file_id: int
    file_name: str
    document_type: str
    status: str
    note: str | None
    submitted_at: datetime
    review_note: str | None


class SupplierQualityDocumentPage(BaseModel):
    items: list[SupplierQualityDocumentRead]
    total: int
    page: int
    page_size: int


class SupplierReconciliationRead(BaseModel):
    id: int
    reconciliation_no: str
    po_id: int
    po_no: str
    currency_code: str
    total_amount: Decimal
    status: str
    items_version: int
    note: str | None
    created_at: datetime
    updated_at: datetime


class SupplierReconciliationPage(BaseModel):
    items: list[SupplierReconciliationRead]
    total: int
    page: int
    page_size: int


class SupplierReconciliationMessageCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=2000)


class SupplierReconciliationAction(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class SupplierReconciliationMessageRead(BaseModel):
    id: int
    author_type: str
    message: str
    created_at: datetime


class SupplierReconciliationMessagePage(BaseModel):
    items: list[SupplierReconciliationMessageRead]
    total: int
    page: int
    page_size: int
