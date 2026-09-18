"""补货接口请求和响应模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReplenishmentItemCreate(BaseModel):
    """补货明细字段。"""
    product_id: int = Field(gt=0)
    unit_id: int = Field(gt=0)
    requested_quantity: Decimal = Field(gt=0)
    expected_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class ReplenishmentCreate(BaseModel):
    """创建补货申请字段。"""
    supplier_id: int = Field(gt=0)
    source_po_id: int | None = Field(default=None, gt=0)
    source_delivery_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=1000)
    items: list[ReplenishmentItemCreate] = Field(min_length=1, max_length=100)


class ReplenishmentReject(BaseModel):
    """驳回补货申请原因。"""
    reason: str = Field(min_length=1, max_length=1000)


class ReplenishmentComplete(BaseModel):
    """完成补货申请时提交实际采购订单。"""
    fulfillment_po_id: int = Field(gt=0)


class ReplenishmentItemRead(BaseModel):
    """补货明细响应。"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    replenishment_request_id: int
    line_no: int
    product_id: int
    unit_id: int
    requested_quantity: Decimal
    expected_date: date | None
    status: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class ReplenishmentRead(BaseModel):
    """补货申请响应。"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    replenishment_no: str
    supplier_id: int
    source_po_id: int | None
    source_delivery_id: int | None
    applicant_id: int
    reason: str
    status: str
    fulfillment_po_id: int | None
    approved_by: int | None
    approved_at: datetime | None
    rejected_at: datetime | None
    reject_reason: str | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[ReplenishmentItemRead]


class ReplenishmentPage(BaseModel):
    """补货申请分页响应。"""
    items: list[ReplenishmentRead]
    total: int
    page: int
    page_size: int
