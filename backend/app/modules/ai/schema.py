"""AI 数据契约的唯一声明处：接口、模型输出、工具参数和共享状态。

只依赖基础类型与纯数据目录，不依赖控制器、业务服务、ORM 或模型客户端。
运行时可变状态和数据库表分别留在执行模块与 model.py。
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.modules.ai.catalog import CATALOG, slot_description


class AIChatMessage(BaseModel):
    """一条 OpenAI 兼容格式的对话消息。"""

    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=20_000)


class BatchChoice(BaseModel):
    """仅选择服务端已保存候选，不承载客户端执行计划。"""
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(pattern=r"^t[1-6]$")
    entity: Literal["product", "rfq_item"]
    selected_id: int = Field(strict=True, gt=0)
    revision: int = Field(strict=True, ge=1)


class AIChatRequest(BaseModel):
    """AI 对话请求；附件通过文件 ID 关联到当前用户已上传的文件。"""

    route_token: str | None = Field(default=None, max_length=64000)
    retry_failed: bool = Field(default=False, strict=True)
    batch_choice: BatchChoice | None = None
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
    batch_result: dict[str, Any] | None = None
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


class AIMessageSnapshot(BaseModel):
    """历史缓存的原始消息快照；展示前仍需重验引用和权限。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    message_role: Literal["USER", "ASSISTANT", "SYSTEM", "TOOL"]
    content: str
    citations: list | None
    created_at: datetime


class AIHistorySnapshot(BaseModel):
    """持久化消息分页的短期缓存，不保存已过滤的授权结论。"""

    items: list[AIMessageSnapshot]
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
    """服务端保存的草稿预览；确认令牌只允许消费该版本的快照。"""

    draft: dict[str, Any]
    display_items: list[AIPurchaseDraftPreviewItem]
    warnings: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    confirmation_id: str | None = None
    preview_version: int | None = None
    expires_at: datetime | None = None
    requires_user_confirmation: bool = True


class AIPurchaseDraftConfirm(BaseModel):
    """显式确认用户看到的某个预览版本。"""

    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=32, max_length=32, pattern="^[a-f0-9]{32}$")
    preview_version: int = Field(strict=True, ge=1)
    confirm: Literal[True]


class AIPurchaseDraftRequest(BaseModel):
    """待整理成采购申请表单候选值的自然语言需求。"""

    question: str = Field(min_length=1, max_length=10_000)
    conversation_id: int | None = Field(default=None, gt=0)


class AIPurchaseDraftPatch(BaseModel):
    """只接受草稿字段的显式修改；当前版本必须再次确认。"""
    model_config = ConfigDict(extra="forbid")
    confirmation_id: str = Field(min_length=32, max_length=32, pattern="^[a-f0-9]{32}$")
    preview_version: int = Field(strict=True, ge=1)
    changes: dict[str, Any] = Field(min_length=1)


# 共享意图与状态

class Intent(StrEnum):
    """AI 支持的入口意图：数据查询 / 文档问答 / 功能介绍 / 问候 / 范围外。"""

    MULTI = "multi"
    GUIDANCE = "guidance"
    CLARIFY = "clarify"
    QUERY = "query"
    DOC = "doc"
    PROJECT = "project"
    GREETING = "greeting"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    reason: str
    understanding: dict | None = None


# 任务状态

class TaskStatus(StrEnum):
    """单项只读任务从规划到终止的状态；等待补充与依赖阻塞不视为成功。"""
    PENDING = "PENDING"  # 已识别，尚未生成执行计划
    PLANNED = "PLANNED"  # 计划已生成并通过校验
    RUNNING = "RUNNING"  # 正在执行只读查询
    WAITING_INPUT = "WAITING_INPUT"  # 缺少参数或存在候选歧义，需要补充
    SUCCEEDED = "SUCCEEDED"  # 已执行且有可核验结果；空结果也是成功
    FAILED = "FAILED"  # 校验、权限、模型或执行失败
    BLOCKED = "BLOCKED"  # 前置任务未成功，当前任务没有执行
    CANCELLED = "CANCELLED"  # 用户取消，后续任务没有执行


class BatchStatus(StrEnum):
    """由全部子任务终态计算的批次结果，不覆盖各项的具体失败原因。"""
    SUCCEEDED = "SUCCEEDED"  # 所有子任务成功
    PARTIAL = "PARTIAL"  # 至少一项成功，仍有未完成子任务
    WAITING_INPUT = "WAITING_INPUT"  # 没有成功结果，且需要用户补充
    FAILED = "FAILED"  # 没有成功结果，存在失败或阻塞
    CANCELLED = "CANCELLED"  # 整批在执行前取消


TASK_STATUS_LABELS = {
    TaskStatus.PENDING: "待规划", TaskStatus.PLANNED: "待执行", TaskStatus.RUNNING: "执行中",
    TaskStatus.WAITING_INPUT: "待补充", TaskStatus.SUCCEEDED: "已完成", TaskStatus.FAILED: "失败",
    TaskStatus.BLOCKED: "依赖阻塞", TaskStatus.CANCELLED: "已取消", BatchStatus.PARTIAL: "部分完成",
}


# 语义理解与路由

Task = Literal["inventory", "quotes", "analytics", "document"]


class Slots(BaseModel):
    """仅承载用户明确给出的业务条件；不接受数据库 ID 或身份字段。"""
    model_config = ConfigDict(extra="forbid")
    product_keyword: str | None = Field(default=None, max_length=200)
    rfq_no: str | None = Field(default=None, max_length=32)
    warehouse_keyword: str | None = Field(default=None, max_length=128)
    date_from: date | None = None
    date_to: date | None = None
    limit: int | None = Field(default=None, strict=True, ge=1, le=100)
    unit: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def validate_dates(self):
        """拒绝倒置的 ISO 日期范围，防止错误条件进入计划生成阶段。"""
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("时间范围起止顺序错误")
        return self


class SubTask(BaseModel):
    """一项原子只读请求；依赖由前置任务 ID 表示，不包含任意执行代码。"""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^t[1-6]$")
    kind: Task
    question: str = Field(min_length=2, max_length=1000)
    slots: Slots = Field(default_factory=Slots)
    depends_on: list[str] = Field(default_factory=list, max_length=5)


class Understanding(BaseModel):
    """语义模型的严格输出契约，由程序校验后才能用于路由或拆分。"""
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["capability", "guidance", "query", "purchase_draft", "greeting", "unsupported", "clarify"]
    dialogue_action: Literal["new", "continue", "modify", "switch", "cancel"] = "new"
    tasks: list[Task] = Field(default_factory=list, max_length=4)
    excluded_tasks: list[Task] = Field(default_factory=list, max_length=4)
    slots: Slots = Field(default_factory=Slots)
    question: str | None = Field(default=None, max_length=1000)
    sub_tasks: list[SubTask] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def normalize(self):
        """校验任务一致性和无环依赖，并去除被明确否定的任务类别。"""
        seen = set()
        for task in self.sub_tasks:
            if task.id in seen or not set(task.depends_on) <= seen:
                raise ValueError("子任务 ID 必须唯一，依赖必须来自前置子任务")
            if task.kind in self.excluded_tasks:
                raise ValueError("子任务不得执行被排除的意图")
            seen.add(task.id)
        if self.sub_tasks and set(self.tasks) != {task.kind for task in self.sub_tasks}:
            raise ValueError("子任务类别必须与总任务一致")
        self.tasks = list(dict.fromkeys(task for task in self.tasks if task not in self.excluded_tasks))
        if self.dialogue_action == "cancel":
            self.tasks = []
        elif self.purpose == "query" and not self.tasks:
            raise ValueError("查询必须明确业务任务")
        if self.purpose != "query":
            self.tasks = []
            self.sub_tasks = []
        return self

    @property
    def route(self) -> str:
        """根据已校验任务决定入口；多项原子任务进入批次，混合未拆分则澄清。"""
        if self.dialogue_action == "cancel":
            return "cancel"
        if self.purpose != "query":
            return self.purpose
        tasks = set(self.tasks)
        if len(self.sub_tasks) > 1:
            return "batch"
        if tasks <= {"inventory", "quotes"}:
            return "agent"
        if tasks == {"document"}:
            return "document"
        if tasks == {"analytics"}:
            return "query"
        return "clarify"  # 未拆分的混合请求不能直接执行

    @property
    def agent_goal(self) -> str:
        """将库存/报价类别映射到现有 Agent 的完成条件；其他类别返回 unknown。"""
        return ({"inventory": "inventory_query", "quotes": "supplier_quote_query"}.get(self.tasks[0], "unknown")
                if len(self.tasks) == 1 else "inventory_and_quotes_query" if set(self.tasks) == {"inventory", "quotes"} else "unknown")


class RouteRequest(BaseModel):
    """统一路由接口的输入；会话 ID 仍需服务端检查归属。"""
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = Field(default=None, gt=0)


# 工具输入与输出

PositiveID = Annotated[int, Field(strict=True, gt=0)]


class ToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryInput(ToolSchema):
    product_id: PositiveID
    warehouse_id: PositiveID | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 20


class QuoteInput(ToolSchema):
    product_id: PositiveID
    rfq_item_id: PositiveID
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 20


class ToolCall(ToolSchema):
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, object]


class ProductSearchInput(ToolSchema):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    keyword: str = Field(min_length=1, max_length=100)
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 10


class RFQSearchInput(ToolSchema):
    product_id: PositiveID
    rfq_no: str | None = Field(default=None, min_length=1, max_length=32)
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 10


class ProductCandidate(ToolSchema):
    product_id: int
    product_code: str
    product_name: str
    model: str | None
    packaging_spec: str | None
    unit_id: int
    unit_name: str


class ProductSearchResult(ToolSchema):
    tool: Literal["catalog.search_products"] = "catalog.search_products"
    keyword: str
    total_rows: int
    truncated: bool
    rows: list[ProductCandidate]
    sources: list["Source"]


class RFQCandidate(ToolSchema):
    rfq_item_id: int
    rfq_id: int
    rfq_no: str
    product_id: int
    specification: str | None
    technical_requirements: str | None


class RFQSearchResult(ToolSchema):
    tool: Literal["supplier_quotes.find_rfq_items"] = "supplier_quotes.find_rfq_items"
    product_id: int
    total_rows: int
    truncated: bool
    rows: list[RFQCandidate]
    sources: list["Source"]


class Source(ToolSchema):
    resource: str
    record_id: int
    parent_id: int | None = None


class InventoryRow(ToolSchema):
    balance_id: int
    warehouse_id: int
    warehouse_name: str
    batch_id: int
    batch_no: str
    expiry_date: date | None
    unit_id: int
    unit_name: str
    status: str
    quantity: Decimal
    locked_quantity: Decimal
    available_quantity: Decimal


class InventoryTotal(ToolSchema):
    unit_id: int
    unit_name: str
    available_quantity: Decimal


class InventoryResult(ToolSchema):
    tool: Literal["inventory.query_available"] = "inventory.query_available"
    observed_at: datetime
    product_id: int
    product_name: str
    warehouse_id: int | None
    scope: str = "当前用户可访问仓库；未指定仓库时不是企业全量库存"
    total_rows: int
    truncated: bool
    totals: list[InventoryTotal]
    scope_warehouse_ids: list[int] = Field(default_factory=list)
    rows: list[InventoryRow]
    sources: list[Source]
    warnings: list[str]


class QuoteRow(ToolSchema):
    quote_id: int
    quote_item_id: int
    supplier_id: int
    supplier_name: str
    quote_no: str
    quote_version: int
    quote_date: date
    valid_until: date | None
    currency_code: str
    unit_id: int
    unit_name: str
    supplier_model: str | None
    tax_rate: Decimal | None
    unit_price: Decimal
    quoted_quantity: Decimal
    moq_quantity: Decimal | None
    moq_unit_id: int | None
    lead_days: int | None
    rank: int | None = None


class QuoteResult(ToolSchema):
    tool: Literal["supplier_quotes.compare"] = "supplier_quotes.compare"
    observed_at: datetime
    as_of: date
    product_id: int
    rfq_id: int
    rfq_no: str
    rfq_item_id: int
    specification: str | None
    technical_requirements: str | None
    scope: str = "同一询价明细；普通用户仅本人询价，采购经理/管理员全部询价"
    comparison_basis: str = "未税单价；仅在币种、单位、税率、供应商型号相同且明确时排序"
    total_rows: int
    truncated: bool
    rows: list[QuoteRow]
    sources: list[Source]
    warnings: list[str]


# Agent 任务与动作

class TaskCreate(ToolSchema):
    question: str = Field(min_length=1, max_length=2000)
    route_token: str | None = Field(default=None, max_length=64000)


class TaskContinue(TaskCreate):
    revision: Annotated[int, Field(strict=True, ge=0)]
    product_id: PositiveID | None = None
    all_products: bool = False
    rfq_item_id: PositiveID | None = None


class ChatTaskCreate(TaskCreate):
    conversation_id: PositiveID | None = None


class CallAction(ToolCall):
    action: Literal["call_tool"]


class AskAction(ToolSchema):
    action: Literal["ask_user"]
    question: str = Field(min_length=1, max_length=1000)


class FinishAction(ToolSchema):
    action: Literal["finish"]
    evidence_steps: list[PositiveID] = Field(min_length=1, max_length=24)


ACTION = TypeAdapter(Annotated[CallAction | AskAction | FinishAction, Field(discriminator="action")])


class PendingChoice(ToolSchema):
    entity: Literal["product", "rfq_item"]
    lookup_arguments: dict
    candidates: list[dict]
    revision: int


class Workflow(ToolSchema):
    """条件只用于限定查询；候选和业务事实仍必须由授权工具核验。"""
    rfq_no: str | None = Field(default=None, min_length=1, max_length=32)
    pending: PendingChoice | None = None
    resume_selection: bool = False
    product_keyword: str | None = None
    all_products: bool = False
    verified_products: list[int] = Field(default_factory=list)


class TaskRead(ToolSchema):
    id: str
    can_select_all_products: bool = False
    status: Literal["RUNNING", "WAITING_INPUT", "SUCCEEDED", "FAILED", "CANCELLED"]
    revision: int
    reply: str
    error_code: str | None
    messages: list[str]
    trace: list[dict]
    conversation_id: int | None = None


# 多意图批次

class TaskResult(BaseModel):
    """子任务计划、终态和来源证据；失败项不得携带成功结果。"""
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Task
    question: str
    depends_on: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    query_plan: dict | None = None
    execution_plan: dict | None = None
    answer: str | None = None
    error_code: str | None = None
    citations: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    pending: PendingChoice | None = None


class BatchResult(BaseModel):
    """整批汇总状态及按原始顺序排列的子任务结果。"""
    status: BatchStatus
    tasks: list[TaskResult]


class AgentTaskPage(BaseModel):
    items: list[TaskRead]
    total: int
    page: int
    page_size: int


# 查询计划

class QueryFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal[tuple(sorted({field for spec in CATALOG.values() for field in spec.filters}))] = Field(
        title="筛选槽位", description="必须属于当前 dataset 的 filters，不能把分组别名用于筛选。各数据集允许值：" + slot_description("filters"))
    operator: Literal["eq", "contains", "gte", "lte", "in"] = Field(default="eq", title="筛选操作符",
        description="eq=等于，contains=包含文本，gte=大于等于，lte=小于等于，in=属于集合。in 的 value 必须是数组；其余操作使用单个值。")
    value: str | int | float | list[str | int | float] = Field(title="筛选值",
        description="用户明确给出或前置查询明确返回的值，不得猜测ID。状态使用业务编码：finance_invoices 已核验=VERIFIED；finance_payments 已付款=PAID。")


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: Literal[tuple(CATALOG)] = Field(title="查询数据集",
        description="根据问题选择唯一数据集，不能选择无关数据集来凑合法输出。数据集含义：" + slot_description("label"))
    metric: Literal["count", "amount", "sum_quantity", "records"] = Field(title="统计指标",
        description="count=记录数量，amount=金额合计，sum_quantity=库存数量合计，records=固定业务明细。发票金额为含税金额；报价单价不得跨产品或单位求和；金额按币种分别统计。各数据集允许值：" + slot_description("metrics"))
    time_field: Literal[tuple(sorted({field for spec in CATALOG.values() for field in spec.times}))] | None = Field(
        default="created_at", title="时间口径",
        description="日期筛选依据的业务时间字段。采购订单本月统计使用 order_date；未限定日期可为 null；无时间字段的数据集必须为 null。各数据集允许值：" + slot_description("times"))
    date_from: date | None = Field(default=None, title="起始日期",
        description="包含当天的 ISO 日期 YYYY-MM-DD；不限起始时间为 null。相对时间以输入 today 换算；本月从当月第一天开始。不得晚于 date_to。")
    date_to: date | None = Field(default=None, title="结束日期",
        description="包含当天的 ISO 日期 YYYY-MM-DD；不限结束时间为 null。相对时间以输入 today 换算；本月截至 today，不能擅自扩展到未来月底。")
    group_by: Literal[tuple(sorted({field for spec in CATALOG.values() for field in spec.dimensions}))] | None = Field(
        default=None, title="分组维度",
        description="只能是一个维度字符串或 null，不能是数组。按供应商分组使用 supplier，不能使用筛选字段 supplier_name；金额会再按币种分组。各数据集允许值：" + slot_description("dimensions"))
    filters: list[QueryFilter] = Field(default_factory=list, title="筛选条件",
        description="按用户明确条件逐项填写；没有条件使用 []，不得猜测。已付款金额须筛选 status=PAID，已核验发票金额须筛选 status=VERIFIED。")
    order: Literal["asc", "desc"] = Field(default="desc", title="排序方向",
        description="asc=升序，desc=降序；金额最高、数量最多等排名使用 desc。")
    limit: int = Field(default=20, ge=1, le=100, title="最多展示条数",
        description="用户明确最多显示 N 家或 N 条时取 N；未指定取20。仅限制明细展示，不能将展示条数当作全范围统计数量。允许1至100。")

    @model_validator(mode="after")
    def validate_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("时间范围起止顺序错误")
        if (self.date_from or self.date_to) and not self.time_field:
            raise ValueError("日期筛选必须指定时间字段")
        return self


class Text2SQLRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    limit: int = Field(default=20, ge=1, le=100)


class Text2SQLResponse(BaseModel):
    question: str
    plan: QueryPlan
    sql: str
    parameterized_sql: str
    columns: list[str]
    slots: list[dict[str, Any]]
    template: str
    render_columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    source_records: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int
    truncated: bool
    stages: list[str]
    render: dict[str, Any]
    unit: str | None
    unit_note: str | None
    read_only: Literal[True] = True


# 采购草稿模型输出

class _DraftItem(BaseModel):
    requested_name: str = Field(default="", max_length=255)
    product_id: int | None = Field(default=None, gt=0)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_id: int | None = Field(default=None, gt=0)
    technical_requirements: str | None = None
    budget_price: Decimal | None = Field(default=None, ge=0)
    expected_date: date | None = None


class _DraftProposal(BaseModel):
    purpose: str = Field(default="", max_length=1000)
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"
    budget_amount: Decimal | None = Field(default=None, ge=0)
    currency_code: str = Field(default="CNY", min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    expected_date: date | None = None
    items: list[_DraftItem] = Field(min_length=1, max_length=100)
    missing_fields: list[str] = Field(default_factory=list)


# 严格模型输出格式由契约生成，避免维护第二份字段定义。

def schema_response_format(model: type[BaseModel], name: str) -> dict:
    schema = model.model_json_schema()

    def strict(node):
        if isinstance(node, dict):
            node.pop("default", None)
            # 当前服务的 Schema 子集不接受 format=date；模型约束 ISO 外形，Pydantic 校验真实日期。
            if node.get("format") == "date":
                node.pop("format")
                node["pattern"] = r"^\d{4}-\d{2}-\d{2}$"
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in list(node.values()):
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)

    strict(schema)
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
