"""采购订单接口的请求与响应模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PurchaseOrderCreate(BaseModel):
    """根据已确认比价结果生成采购订单时提交的字段。"""

    model_config = ConfigDict(extra="forbid")

    comparison_id: int = Field(gt=0)
    quote_id: int = Field(gt=0)
    delivery_address: str | None = Field(default=None, max_length=500)
    expected_arrival_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class PurchaseOrderUpdate(BaseModel):
    """采购订单草稿允许更新的字段。"""

    model_config = ConfigDict(extra="forbid")

    delivery_address: str | None = Field(default=None, max_length=500)
    expected_arrival_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class PurchaseOrderApprovalAction(BaseModel):
    """采购订单审批时提交的意见。"""

    opinion: str | None = Field(default=None, max_length=2000)


class PurchaseOrderCancelAction(BaseModel):
    """取消采购订单时提交的原因。"""

    reason: str = Field(min_length=1, max_length=1000)


class PurchaseOrderItemRead(BaseModel):
    """采购订单明细响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    po_id: int
    line_no: int
    product_id: int
    supplier_product_id: int | None
    source_quote_item_id: int | None
    product_name_snapshot: str
    supplier_model_snapshot: str | None
    order_quantity: Decimal
    unit_id: int
    unit_price: Decimal
    tax_rate: Decimal | None
    payment_terms_snapshot: str | None
    planned_arrival_date: date | None
    received_quantity: Decimal
    status: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class PurchaseOrderApprovalRead(BaseModel):
    """采购订单审批记录响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    po_id: int
    sequence_no: int
    node_code: str
    node_name: str
    approver_id: int | None
    action: str
    opinion: str | None
    acted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PurchaseOrderEventRead(BaseModel):
    """采购订单事件响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    po_id: int
    event_type: str
    event_time: datetime
    operator_id: int | None
    from_status: str | None
    to_status: str | None
    event_note: str | None
    created_at: datetime


class PurchaseOrderRead(BaseModel):
    """采购订单详情响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    po_no: str
    supplier_id: int
    source_comparison_id: int | None
    source_quote_id: int | None
    source_request_id: int | None
    department_id: int | None
    buyer_id: int
    order_amount: Decimal
    currency_code: str
    delivery_address: str | None
    order_date: date | None
    expected_arrival_date: date | None
    status: str
    supplier_confirmed_at: datetime | None
    approved_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    items: list[PurchaseOrderItemRead]
    approvals: list[PurchaseOrderApprovalRead]
    events: list[PurchaseOrderEventRead]


class PurchaseOrderPage(BaseModel):
    """采购订单分页响应。"""

    items: list[PurchaseOrderRead]
    total: int
    page: int
    page_size: int
