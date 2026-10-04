"""库存接口的请求与响应模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class WarehouseCreate(BaseModel):
    """创建仓库时提交的字段。"""

    warehouse_code: str = Field(min_length=1, max_length=64)
    warehouse_name: str = Field(min_length=1, max_length=128)
    region: str | None = Field(default=None, max_length=128)
    address: str | None = Field(default=None, max_length=500)
    manager_id: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)


class LocationCreate(BaseModel):
    """创建库位时提交的字段。"""

    location_code: str = Field(min_length=1, max_length=64)
    location_name: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=500)


class WarehouseRead(BaseModel):
    """仓库响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    warehouse_code: str
    warehouse_name: str
    region: str | None
    address: str | None
    manager_id: int | None
    status: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class LocationRead(BaseModel):
    """库位响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    warehouse_id: int
    location_code: str
    location_name: str
    status: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class InboundCreate(BaseModel):
    """将已验收到货单执行入库时提交的字段。"""

    delivery_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    location_id: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


class InventoryBalanceRead(BaseModel):
    """库存余额响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    warehouse_id: int
    location_id: int
    product_id: int
    batch_id: int
    unit_id: int
    quantity: Decimal
    locked_quantity: Decimal
    status: str
    created_at: datetime
    updated_at: datetime


class InventoryIssueOptionRead(BaseModel):
    """最小化的可领用库存选项，不返回通用库存台账字段。"""

    id: int
    product_id: int
    product_name: str
    warehouse_id: int
    warehouse_name: str
    location_id: int
    location_name: str
    batch_id: int
    batch_no: str
    unit_id: int
    unit_name: str
    available_quantity: Decimal


class InventoryBalanceStatusChange(BaseModel):
    """冻结或解冻库存余额时提交的原因。"""

    reason: str = Field(min_length=1, max_length=1000)


class InventoryBalanceStatusLogRead(BaseModel):
    """库存余额状态变更记录响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    balance_id: int
    previous_status: str
    new_status: str
    reason: str
    operator_id: int
    created_at: datetime


class InventoryBalanceStatusLogPage(BaseModel):
    """库存余额状态变更记录分页响应。"""

    items: list[InventoryBalanceStatusLogRead]
    total: int
    page: int
    page_size: int


class InventoryTransactionRead(BaseModel):
    """库存流水响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_no: str
    transaction_type: str
    warehouse_id: int
    location_id: int
    product_id: int
    batch_id: int
    unit_id: int
    quantity: Decimal
    delivery_item_id: int | None
    source_type: str | None
    source_id: int | None
    operator_id: int
    note: str | None
    created_at: datetime


class InboundRead(BaseModel):
    """入库结果响应。"""

    delivery_id: int
    transaction_count: int
    transactions: list[InventoryTransactionRead]
    balances: list[InventoryBalanceRead]


class InventoryBalancePage(BaseModel):
    """库存余额分页响应。"""

    items: list[InventoryBalanceRead]
    total: int
    page: int
    page_size: int


class InventoryTransactionPage(BaseModel):
    """库存流水分页响应。"""

    items: list[InventoryTransactionRead]
    total: int
    page: int
    page_size: int


class InventoryIssueItemCreate(BaseModel):
    """创建库存领用明细时提交的字段。"""

    product_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    location_id: int = Field(gt=0)
    batch_id: int = Field(gt=0)
    unit_id: int = Field(gt=0)
    requested_quantity: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


class InventoryIssueRequestCreate(BaseModel):
    """创建库存领用申请时提交的字段。"""

    department_id: int | None = Field(default=None, gt=0)
    purpose: str = Field(min_length=1, max_length=500)
    items: list[InventoryIssueItemCreate] = Field(min_length=1, max_length=100)


class InventoryIssueRequestUpdate(BaseModel):
    """修改库存领用申请草稿时提交的可选字段。"""

    department_id: int | None = Field(default=None, gt=0)
    purpose: str | None = Field(default=None, min_length=1, max_length=500)
    items: list[InventoryIssueItemCreate] | None = Field(default=None, min_length=1, max_length=100)


class InventoryIssueReject(BaseModel):
    """驳回库存领用申请时提交的原因。"""

    reason: str = Field(min_length=1, max_length=1000)


class InventoryIssueItemRead(BaseModel):
    """库存领用明细响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    issue_request_id: int
    line_no: int
    product_id: int
    warehouse_id: int
    location_id: int
    batch_id: int
    unit_id: int
    requested_quantity: Decimal
    issued_quantity: Decimal
    status: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class InventoryIssueRequestRead(BaseModel):
    """库存领用申请响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    issue_no: str
    applicant_id: int
    department_id: int | None
    purpose: str
    status: str
    approved_by: int | None
    approved_at: datetime | None
    rejected_at: datetime | None
    reject_reason: str | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[InventoryIssueItemRead]


class InventoryIssueRequestPage(BaseModel):
    """库存领用申请分页响应。"""

    items: list[InventoryIssueRequestRead]
    total: int
    page: int
    page_size: int


class InventoryTransferItemCreate(BaseModel):
    """创建库存调拨明细时提交的字段。"""

    product_id: int = Field(gt=0)
    source_warehouse_id: int = Field(gt=0)
    source_location_id: int = Field(gt=0)
    target_warehouse_id: int = Field(gt=0)
    target_location_id: int = Field(gt=0)
    batch_id: int = Field(gt=0)
    unit_id: int = Field(gt=0)
    requested_quantity: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


class InventoryTransferRequestCreate(BaseModel):
    """创建库存调拨申请时提交的字段。"""

    purpose: str = Field(min_length=1, max_length=500)
    items: list[InventoryTransferItemCreate] = Field(min_length=1, max_length=100)


class InventoryTransferRequestUpdate(BaseModel):
    """修改库存调拨申请草稿时提交的可选字段。"""

    purpose: str | None = Field(default=None, min_length=1, max_length=500)
    items: list[InventoryTransferItemCreate] | None = Field(default=None, min_length=1, max_length=100)


class InventoryTransferReject(BaseModel):
    """驳回库存调拨申请时提交的原因。"""

    reason: str = Field(min_length=1, max_length=1000)


class InventoryTransferItemRead(BaseModel):
    """库存调拨明细响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    transfer_request_id: int
    line_no: int
    product_id: int
    source_warehouse_id: int
    source_location_id: int
    target_warehouse_id: int
    target_location_id: int
    batch_id: int
    unit_id: int
    requested_quantity: Decimal
    transferred_quantity: Decimal
    status: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class InventoryTransferRequestRead(BaseModel):
    """库存调拨申请响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    transfer_no: str
    applicant_id: int
    purpose: str
    status: str
    approved_by: int | None
    approved_at: datetime | None
    rejected_at: datetime | None
    reject_reason: str | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[InventoryTransferItemRead]


class InventoryTransferRequestPage(BaseModel):
    """库存调拨申请分页响应。"""

    items: list[InventoryTransferRequestRead]
    total: int
    page: int
    page_size: int


class InventoryStocktakeItemCreate(BaseModel):
    """创建库存盘点明细时提交的字段。"""

    product_id: int = Field(gt=0)
    location_id: int = Field(gt=0)
    batch_id: int = Field(gt=0)
    unit_id: int = Field(gt=0)
    counted_quantity: Decimal = Field(ge=0)
    note: str | None = Field(default=None, max_length=1000)


class InventoryStocktakeRequestCreate(BaseModel):
    """创建库存盘点申请时提交的字段。"""

    warehouse_id: int = Field(gt=0)
    location_id: int | None = Field(default=None, gt=0)
    purpose: str = Field(min_length=1, max_length=500)
    items: list[InventoryStocktakeItemCreate] = Field(min_length=1, max_length=1000)


class InventoryStocktakeRequestUpdate(BaseModel):
    """修改库存盘点申请草稿时提交的可选字段。"""

    purpose: str | None = Field(default=None, min_length=1, max_length=500)
    items: list[InventoryStocktakeItemCreate] | None = Field(default=None, min_length=1, max_length=1000)


class InventoryStocktakeReject(BaseModel):
    """驳回库存盘点申请时提交的原因。"""

    reason: str = Field(min_length=1, max_length=1000)


class InventoryStocktakeItemRead(BaseModel):
    """库存盘点明细响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    stocktake_request_id: int
    line_no: int
    product_id: int
    location_id: int
    batch_id: int
    unit_id: int
    book_quantity: Decimal
    counted_quantity: Decimal
    difference_quantity: Decimal
    status: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class InventoryStocktakeRequestRead(BaseModel):
    """库存盘点申请响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    stocktake_no: str
    applicant_id: int
    warehouse_id: int
    location_id: int | None
    purpose: str
    status: str
    approved_by: int | None
    approved_at: datetime | None
    rejected_at: datetime | None
    reject_reason: str | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[InventoryStocktakeItemRead]


class InventoryStocktakeRequestPage(BaseModel):
    """库存盘点申请分页响应。"""

    items: list[InventoryStocktakeRequestRead]
    total: int
    page: int
    page_size: int
