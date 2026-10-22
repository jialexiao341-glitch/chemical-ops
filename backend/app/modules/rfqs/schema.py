"""询价、报价和比价接口的请求与响应模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RFQItemCreate(BaseModel):
    """创建询价明细时提交的字段。"""

    source_request_item_id: int | None = Field(default=None, gt=0)
    product_id: int | None = Field(default=None, gt=0)
    requested_name: str = Field(min_length=1, max_length=255)
    specification: str | None = Field(default=None, max_length=1000)
    quantity: Decimal = Field(gt=0)
    unit_id: int = Field(gt=0)
    required_delivery_date: date | None = None
    technical_requirements: str | None = None


class RFQCreate(BaseModel):
    """创建询价单时提交的字段。"""

    source_request_id: int | None = Field(default=None, gt=0)
    quote_deadline: datetime | None = None
    requested_delivery_date: date | None = None
    delivery_requirements: str | None = Field(default=None, max_length=1000)
    items: list[RFQItemCreate] = Field(min_length=1, max_length=100)
    supplier_ids: list[int] = Field(min_length=1, max_length=50)


class RFQUpdate(BaseModel):
    """询价草稿允许修改的字段。"""

    quote_deadline: datetime | None = None
    requested_delivery_date: date | None = None
    delivery_requirements: str | None = Field(default=None, max_length=1000)
    items: list[RFQItemCreate] | None = Field(default=None, min_length=1, max_length=100)
    supplier_ids: list[int] | None = Field(default=None, min_length=1, max_length=50)


class RFQSupplierRead(BaseModel):
    """询价供应商响应。"""

    model_config = ConfigDict(from_attributes=True)

    rfq_id: int
    supplier_id: int
    invited_at: datetime
    response_status: str
    response_at: datetime | None
    invitation_channel: str | None
    note: str | None


class RFQItemRead(RFQItemCreate):
    """询价明细响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    rfq_id: int
    line_no: int
    created_at: datetime
    updated_at: datetime


class SupplierQuoteItemCreate(BaseModel):
    """录入供应商报价明细时提交的字段。"""

    rfq_item_id: int = Field(gt=0)
    supplier_product_id: int | None = Field(default=None, gt=0)
    supplier_model: str | None = Field(default=None, max_length=128)
    quoted_quantity: Decimal = Field(gt=0)
    unit_id: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    tax_included: bool | None = None
    moq_quantity: Decimal | None = Field(default=None, gt=0)
    moq_unit_id: int | None = Field(default=None, gt=0)
    freight_amount: Decimal | None = Field(default=None, ge=0)
    freight_tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    freight_tax_included: bool | None = None
    lead_days: int | None = Field(default=None, ge=0)
    payment_terms: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=1000)


class SupplierQuoteCreate(BaseModel):
    """录入供应商报价时提交的字段。"""

    supplier_id: int = Field(gt=0)
    quote_date: date | None = None
    valid_until: date | None = None
    currency_code: str = Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    source_file_id: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)
    items: list[SupplierQuoteItemCreate] = Field(min_length=1, max_length=100)


class QuoteCandidateEvidence(BaseModel):
    """报价候选字段的原文依据。"""

    field: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=500)
    source_quote: str = Field(min_length=1, max_length=600)
    source_location: str = Field(min_length=1, max_length=120)


class QuoteCandidateItem(BaseModel):
    """报价文件中一条待人工复核的明细候选。"""

    rfq_item_id: int | None = None
    product_label: str | None = None
    supplier_model: str | None = None
    quoted_quantity: str | None = None
    unit_name: str | None = None
    unit_price: str | None = None
    tax_rate: str | None = None
    tax_included: bool | None = None
    moq_quantity: str | None = None
    moq_unit_name: str | None = None
    freight_amount: str | None = None
    freight_tax_rate: str | None = None
    freight_tax_included: bool | None = None
    lead_days: int | None = None
    payment_terms: str | None = None
    source_quote: str
    source_location: str


class QuoteParseCandidate(BaseModel):
    """报价文件的可编辑候选结果，不代表已录入报价。"""

    file_id: int
    file_name: str
    supplier_name: str | None = None
    currency_code: str | None = None
    quote_date: str | None = None
    valid_until: str | None = None
    note: str | None = None
    items: list[QuoteCandidateItem]
    evidence: list[QuoteCandidateEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SupplierQuoteItemRead(SupplierQuoteItemCreate):
    """供应商报价明细响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    quote_id: int


class SupplierQuoteRead(BaseModel):
    """供应商报价响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    quote_no: str
    rfq_id: int
    supplier_id: int
    quote_version: int
    quote_date: date
    valid_until: date | None
    currency_code: str
    status: str
    source_file_id: int | None
    received_by: int | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    items: list[SupplierQuoteItemRead]


class QuoteComparisonItemRead(BaseModel):
    """比价明细响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    comparison_id: int
    quote_id: int
    rfq_item_id: int
    supplier_id: int
    quoted_unit_price: Decimal | None
    total_amount: Decimal | None
    currency_code: str | None
    unit_id: int | None
    tax_rate: Decimal | None
    tax_included: bool | None
    comparison_status: str
    comparison_reasons: list[str] | None
    moq_quantity: Decimal | None
    lead_days: int | None
    payment_terms: str | None
    freight_amount: Decimal | None
    freight_tax_rate: Decimal | None
    freight_tax_included: bool | None
    cost_analysis: dict | None = None
    quality_history: dict | None = None
    historical_score: Decimal | None
    composite_score: Decimal | None
    rank_no: int | None
    selection_flag: int
    note: str | None


class QuoteComparisonRead(BaseModel):
    """比价结果响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    comparison_no: str
    rfq_id: int
    created_by: int
    selected_quote_id: int | None
    conclusion: str | None
    selection_reason: str | None
    status: str
    confirmed_by: int | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[QuoteComparisonItemRead]


class QuoteSelection(BaseModel):
    """确认中选报价时提交的字段。"""

    comparison_id: int = Field(gt=0)
    quote_id: int = Field(gt=0)
    selection_reason: str = Field(min_length=1, max_length=2000)


class RFQRead(BaseModel):
    """询价单详情响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    rfq_no: str
    source_request_id: int | None
    requester_id: int
    quote_deadline: datetime | None
    requested_delivery_date: date | None
    delivery_requirements: str | None
    status: str
    sent_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[RFQItemRead]
    suppliers: list[RFQSupplierRead]
    quotes: list[SupplierQuoteRead]
    comparisons: list[QuoteComparisonRead]


class RFQPage(BaseModel):
    """询价单分页响应。"""

    items: list[RFQRead]
    total: int
    page: int
    page_size: int
