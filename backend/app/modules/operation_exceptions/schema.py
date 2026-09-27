"""异常管理接口的请求与响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OperationExceptionCreate(BaseModel):
    """创建异常时提交的字段。"""

    exception_type: str = Field(pattern="^(SHORT_DELIVERY|QUALITY|QUALITY_PENDING|DOCUMENT|OVERDUE|INVENTORY_EXPIRY|OTHER)$")
    source_type: str = Field(pattern="^(PURCHASE_ORDER|DELIVERY|DELIVERY_ITEM|QUALITY_ACCEPTANCE|INVENTORY_BATCH|OTHER)$")
    source_id: int = Field(gt=0)
    po_id: int | None = Field(default=None, gt=0)
    delivery_id: int | None = Field(default=None, gt=0)
    delivery_item_id: int | None = Field(default=None, gt=0)
    responsible_department_id: int | None = Field(default=None, gt=0)
    owner_id: int | None = Field(default=None, gt=0)
    severity: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    description: str = Field(min_length=1)
    due_at: datetime | None = None


class OperationExceptionUpdate(BaseModel):
    """指派或推进异常状态时提交的字段。"""

    owner_id: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, pattern="^(PROCESSING|RESOLVED|CLOSED|CANCELLED)$")
    closing_note: str | None = Field(default=None, max_length=2000)
    due_at: datetime | None = None


class OperationExceptionRead(BaseModel):
    """异常记录响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    exception_no: str
    exception_type: str
    source_type: str
    source_id: int
    po_id: int | None
    delivery_id: int | None
    delivery_item_id: int | None
    responsible_department_id: int | None
    owner_id: int | None
    severity: str
    description: str
    status: str
    due_at: datetime | None
    closed_by: int | None
    closed_at: datetime | None
    closing_note: str | None
    created_at: datetime
    updated_at: datetime


class OperationExceptionPage(BaseModel):
    """异常记录分页响应。"""

    items: list[OperationExceptionRead]
    total: int
    page: int
    page_size: int


class OperationTaskCreate(BaseModel):
    """创建异常处理任务时提交的字段。"""

    title: str = Field(min_length=1, max_length=255)
    assignee_id: int | None = Field(default=None, gt=0)
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|URGENT)$")
    due_at: datetime | None = None


class OperationTaskUpdate(BaseModel):
    """更新异常处理任务时提交的可选字段。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    assignee_id: int | None = Field(default=None, gt=0)
    priority: str | None = Field(default=None, pattern="^(LOW|NORMAL|HIGH|URGENT)$")
    due_at: datetime | None = None
    status: str | None = Field(default=None, pattern="^(PROCESSING|COMPLETED|CANCELLED)$")
    completion_note: str | None = Field(default=None, max_length=2000)


class OperationTaskRead(BaseModel):
    """异常处理任务响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    exception_id: int
    title: str
    assignee_id: int | None
    priority: str
    due_at: datetime | None
    status: str
    completed_at: datetime | None
    completion_note: str | None
    created_at: datetime
    updated_at: datetime


class OperationTaskPage(BaseModel):
    """异常处理任务分页响应。"""

    items: list[OperationTaskRead]
    total: int
    page: int
    page_size: int


class OperationTaskCommentCreate(BaseModel):
    """创建任务处理记录时提交的字段。"""

    content: str = Field(min_length=1)
    attachment_file_id: int | None = Field(default=None, gt=0)


class OperationTaskCommentRead(BaseModel):
    """任务处理记录响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    commenter_id: int
    content: str
    attachment_file_id: int | None
    created_at: datetime


class OperationTaskCommentPage(BaseModel):
    """任务处理记录分页响应。"""

    items: list[OperationTaskCommentRead]
    total: int
    page: int
    page_size: int
