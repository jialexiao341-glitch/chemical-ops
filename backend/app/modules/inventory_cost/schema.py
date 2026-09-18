"""库存成本和有效期预警接口模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FifoOutboundCreate(BaseModel):
    """FIFO 出库字段；request_no 由前端生成并在重试时复用。"""
    request_no: str = Field(min_length=1, max_length=64)
    product_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    location_id: int = Field(gt=0)
    unit_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


class FifoAllocationRead(BaseModel):
    """FIFO 成本分摊响应。"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: int
    cost_layer_id: int
    batch_id: int
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal


class FifoOutboundRead(BaseModel):
    """FIFO 出库响应。"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_no: str
    product_id: int
    warehouse_id: int
    location_id: int
    unit_id: int
    requested_quantity: Decimal
    issued_quantity: Decimal
    total_cost: Decimal
    currency_code: str
    status: str
    operator_id: int
    note: str | None
    created_at: datetime
    allocations: list[FifoAllocationRead]


class ExpiryAlertRead(BaseModel):
    """库存有效期预警响应。"""
    product_id: int
    batch_id: int
    batch_no: str
    warehouse_id: int
    location_id: int
    quantity: Decimal
    expiry_date: date
    days_remaining: int
    alert_level: str
