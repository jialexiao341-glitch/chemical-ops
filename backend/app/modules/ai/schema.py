"""AI 助手请求与响应模型。"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AIChatMessage(BaseModel):
    """一条 OpenAI 兼容格式的对话消息。"""

    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=20_000)


class AIChatRequest(BaseModel):
    """AI 对话请求；附件通过文件 ID 关联到当前用户已上传的文件。"""

    messages: list[AIChatMessage] = Field(min_length=1, max_length=50)
    attachments: list[str] = Field(default_factory=list, max_length=20)
    attachment_file_ids: list[int] = Field(default_factory=list, max_length=20)
    conversation_id: int | None = Field(default=None, gt=0)


class AIChatResponse(BaseModel):
    """AI 对话响应。"""

    message: AIChatMessage
    conversation_id: int
    model: str
    provider: str
    usage: dict[str, int] | None = None
    citations: list | None = None
    query_trace: "AIQueryTrace | None" = None
    query_slots: list[dict[str, Any]] | None = None
    user_query: str | None = None
    answer: str | None = None


class AIQueryTrace(BaseModel):
    """Text2SQL 的可审计查询链路，供 API、持久化引用和前端渲染复用。"""

    query: str
    answer: str | None = None
    dataset: str | None = None
    dataset_label: str | None = None
    permission: str | None = None
    thread_id: str | None = None
    executed_at: datetime | None = None
    data_scope: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    slots: list[dict[str, Any]]
    template: str
    sql: str
    parameterized_sql: str | None = None
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    unit: str | None = None
    unit_note: str | None = None
    row_count: int
    truncated: bool
    stages: list[str]
    render: dict[str, Any]


class AIConversationRead(BaseModel):
    """会话列表摘要。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    business_scene: str
    status: str
    pinned: bool
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AIConversationUpdate(BaseModel):
    """会话标题和置顶状态。"""

    title: str | None = None
    pinned: bool | None = None


class AIConversationPage(BaseModel):
    """当前用户可访问的会话列表。"""

    items: list[AIConversationRead]
    total: int


class AIMessageRead(BaseModel):
    """会话消息。"""

    id: int
    conversation_id: int
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    citations: list | None
    created_at: datetime


class AIMessagePage(BaseModel):
    """会话消息分页结果。"""

    items: list[AIMessageRead]
    total: int


class BriefingRequest(BaseModel):
    """生成运营晨报时提交的字段。"""

    push: bool = Field(default=False, description="是否同时发送站内通知")
    notify_role_codes: list[str] | None = Field(
        default=None,
        max_length=10,
        description="覆盖默认通知角色；为空时通知 SYS_ADMIN 与 PROCUREMENT_MANAGER",
    )


class BriefingResponse(BaseModel):
    """AI 运营晨报响应。"""

    content: str
    snapshot: dict[str, Any]
    model: str
    provider: str
    generated_at: datetime
    pushed: bool
    notified_count: int = 0


class NLFilterRequest(BaseModel):
    """自然语言解析列表筛选条件的请求。"""

    dataset: str = Field(min_length=1, max_length=64, description="目录中的数据集键")
    question: str = Field(min_length=1, max_length=500, description="自然语言筛选描述")


class NLFilterTimeRange(BaseModel):
    """解析出的时间范围（字段必须在数据集白名单内）。"""

    field: str
    date_from: date | None = None
    date_to: date | None = None


class NLFilterResult(BaseModel):
    """自然语言筛选解析结果；只产出条件，不执行查询。"""

    dataset: str
    dataset_label: str
    filters: dict[str, str] = Field(default_factory=dict)
    time_range: NLFilterTimeRange | None = None
    keywords: str | None = None
    dropped: list[str] = Field(default_factory=list, description="被白名单或格式校验剔除的条件说明")
    raw: str = Field(default="", description="模型原始输出，便于排查")


class AIPurchaseDraftPreviewItem(BaseModel):
    """供用户核对的采购申请候选明细，不代表已创建业务单据。"""

    requested_name: str
    product_name: str | None = None
    quantity: str
    unit_name: str
    technical_requirements: str | None = None
    budget_price: str | None = None


class AIPurchaseDraftPreview(BaseModel):
    """AI 提出的采购草稿候选值；用户确认后才会调用采购申请接口。"""

    draft: dict[str, Any]
    display_items: list[AIPurchaseDraftPreviewItem]
    warnings: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = True


class AIPurchaseDraftRequest(BaseModel):
    """待整理成采购申请表单候选值的自然语言需求。"""

    question: str = Field(min_length=1, max_length=2000)
