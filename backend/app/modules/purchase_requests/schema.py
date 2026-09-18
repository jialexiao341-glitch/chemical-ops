"""采购申请接口的请求和响应模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PurchaseRequestItemCreate(BaseModel):
    """创建采购申请明细时提交的字段。"""

    product_id: int | None = Field(default=None, gt=0)
    requested_name: str = Field(min_length=1, max_length=255)
    technical_requirements: str | None = None
    quantity: Decimal = Field(gt=0)
    unit_id: int = Field(gt=0)
    budget_price: Decimal | None = Field(default=None, ge=0)
    expected_date: date | None = None


class PurchaseRequestCreate(BaseModel):
    """创建采购申请时提交的字段。"""

    department_id: int | None = Field(default=None, gt=0)
    purpose: str = Field(min_length=1, max_length=1000)
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|URGENT)$")
    budget_amount: Decimal | None = Field(default=None, ge=0)
    currency_code: str = Field(default="CNY", min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    expected_date: date | None = None
    items: list[PurchaseRequestItemCreate] = Field(min_length=1, max_length=100)


class PurchaseRequestUpdate(BaseModel):
    """草稿或驳回申请允许修改的字段。"""

    department_id: int | None = Field(default=None, gt=0)
    purpose: str | None = Field(default=None, min_length=1, max_length=1000)
    priority: str | None = Field(default=None, pattern="^(LOW|NORMAL|HIGH|URGENT)$")
    budget_amount: Decimal | None = Field(default=None, ge=0)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    expected_date: date | None = None
    items: list[PurchaseRequestItemCreate] | None = Field(default=None, min_length=1, max_length=100)


class ApprovalAction(BaseModel):
    """审批通过或驳回时提交的意见。"""

    opinion: str | None = Field(default=None, max_length=2000)


class CancelAction(BaseModel):
    """取消采购申请时提交的原因。"""

    reason: str = Field(min_length=1, max_length=1000)


class PurchaseRequestItemRead(PurchaseRequestItemCreate):
    """采购申请明细响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int
    line_no: int
    fulfilled_quantity: Decimal
    status: str
    created_at: datetime
    updated_at: datetime


class PurchaseRequestApprovalRead(BaseModel):
    """采购申请审批节点响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int
    sequence_no: int
    node_code: str
    node_name: str
    approver_id: int | None
    action: str
    opinion: str | None
    acted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PurchaseRequestRead(BaseModel):
    """采购申请详情响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    request_no: str
    applicant_id: int
    department_id: int | None
    purpose: str
    priority: str
    budget_amount: Decimal | None
    currency_code: str
    expected_date: date | None
    status: str
    submitted_at: datetime | None
    approved_at: datetime | None
    rejected_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime
    updated_at: datetime
    items: list[PurchaseRequestItemRead]
    approvals: list[PurchaseRequestApprovalRead]


class PurchaseRequestPage(BaseModel):
    """采购申请分页响应。"""

    items: list[PurchaseRequestRead]
    total: int
    page: int
    page_size: int
