"""供应商门户接口响应模型。"""

from pydantic import BaseModel, ConfigDict, Field

from app.modules.purchase_orders.schema import PurchaseOrderRead


class SupplierOrderPage(BaseModel):
    """供应商订单分页响应。"""
    items: list[PurchaseOrderRead]
    total: int
    page: int
    page_size: int


class SupplierOrderReject(BaseModel):
    """供应商拒绝订单时提交的原因。"""
    reason: str = Field(min_length=1, max_length=1000)
