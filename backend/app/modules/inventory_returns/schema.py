"""退货接口请求和响应模型。"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReturnItemCreate(BaseModel):
    """退货明细字段。"""

    product_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    location_id: int = Field(gt=0)
    batch_id: int = Field(gt=0)
    unit_id: int = Field(gt=0)
    requested_quantity: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


class ReturnCreate(BaseModel):
    """创建退货申请字段。"""

    supplier_id: int = Field(gt=0)
    po_id: int | None = Field(default=None, gt=0)
    delivery_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=1000)
    items: list[ReturnItemCreate] = Field(min_length=1, max_length=100)


class ReturnReject(BaseModel):
    """驳回退货申请原因。"""

    reason: str = Field(min_length=1, max_length=1000)


class ReturnItemRead(BaseModel):
    """退货明细响应。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    return_request_id: int
    line_no: int
    product_id: int
    warehouse_id: int
    location_id: int
    batch_id: int
    unit_id: int
    requested_quantity: Decimal
    returned_quantity: Decimal
    status: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class ReturnRead(BaseModel):
    """退货申请响应。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    return_no: str
    supplier_id: int
    po_id: int | None
    delivery_id: int | None
    applicant_id: int
    reason: str
    status: str
    approved_by: int | None
    approved_at: datetime | None
    rejected_at: datetime | None
    reject_reason: str | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[ReturnItemRead]


class ReturnPage(BaseModel):
    """退货申请分页响应。"""
    items: list[ReturnRead]
    total: int
    page: int
    page_size: int
