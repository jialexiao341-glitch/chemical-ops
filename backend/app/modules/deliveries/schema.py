"""到货和收货接口的请求与响应模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DeliveryItemCreate(BaseModel):
    """登记到货计划时提交的明细字段。"""

    po_item_id: int = Field(gt=0)
    planned_quantity: Decimal = Field(gt=0)
    batch_no: str | None = Field(default=None, max_length=128)
    package_spec: str | None = Field(default=None, max_length=255)
    production_date: date | None = None
    expiry_date: date | None = None
    document_complete: bool = False
    note: str | None = Field(default=None, max_length=1000)


class DeliveryCreate(BaseModel):
    """登记一张到货单时提交的字段。"""

    po_id: int = Field(gt=0)
    shipment_date: date | None = None
    expected_arrival_date: date | None = None
    logistics_company: str | None = Field(default=None, max_length=128)
    tracking_no: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=1000)
    items: list[DeliveryItemCreate] = Field(min_length=1, max_length=100)


class DeliveryReceiveItem(BaseModel):
    """确认收货时提交的实际数量。"""

    delivery_item_id: int = Field(gt=0)
    actual_quantity: Decimal = Field(ge=0)
    short_quantity: Decimal = Field(default=0, ge=0)


class DeliveryReceive(BaseModel):
    """确认收货时提交的实际到货信息。"""

    actual_arrival_date: date | None = None
    items: list[DeliveryReceiveItem] = Field(min_length=1, max_length=100)


class DeliveryItemRead(BaseModel):
    """到货明细响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_id: int
    po_item_id: int
    product_id: int
    line_no: int
    batch_no: str | None
    package_spec: str | None
    planned_quantity: Decimal
    actual_quantity: Decimal
    short_quantity: Decimal
    unit_id: int
    production_date: date | None
    expiry_date: date | None
    document_complete: int
    note: str | None
    created_at: datetime
    updated_at: datetime


class DeliveryRead(BaseModel):
    """到货单详情响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_no: str
    po_id: int
    supplier_id: int
    shipment_date: date | None
    expected_arrival_date: date | None
    actual_arrival_date: date | None
    logistics_company: str | None
    tracking_no: str | None
    status: str
    received_by: int | None
    received_at: datetime | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    items: list[DeliveryItemRead]


class DeliveryPage(BaseModel):
    """到货单分页响应。"""

    items: list[DeliveryRead]
    total: int
    page: int
    page_size: int
