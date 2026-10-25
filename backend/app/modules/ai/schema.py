"""AI 数据契约的唯一声明处：接口、模型输出、工具参数和共享状态。

只依赖基础类型与纯数据目录，不依赖控制器、业务服务、ORM 或模型客户端。
运行时可变状态和数据库表分别留在执行模块与 model.py。
"""

from dataclasses import dataclass
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from typing_extensions import TypedDict

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from app.modules.ai.catalog import CATALOG, slot_description
from app.modules.purchase_requests.schema import PurchaseRequestCreate, PurchaseRequestItemCreate


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
    """自然语言或结构化采购申请草稿候选值。"""

    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, min_length=1, max_length=10_000)
    draft: PurchaseRequestCreate | None = None
    conversation_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_input_mode(self) -> "AIPurchaseDraftRequest":
        if (self.question is None) == (self.draft is None):
            raise ValueError("question 和 draft 必须且只能提供一个")
        return self


class AIPurchaseDraftPatch(BaseModel):
    """只接受草稿字段的显式修改；当前版本必须再次确认。"""
    model_config = ConfigDict(extra="forbid")
    confirmation_id: str = Field(min_length=32, max_length=32, pattern="^[a-f0-9]{32}$")
    preview_version: int = Field(strict=True, ge=1)
    changes: dict[str, Any] = Field(min_length=1)


class AIActionProposalCreate(BaseModel):
    """提交候选动作；action_type 仍需由服务端处理器白名单校验。"""

    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=100)


class AIActionProposalRevise(BaseModel):
    """修订本人待确认的提案并递增预览版本。"""

    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=32, max_length=32, pattern="^[a-f0-9]{32}$")
    preview_version: int = Field(strict=True, ge=1)
    payload: dict[str, Any]


class AIActionProposalCancel(BaseModel):
    """取消本人当前版本的动作提案。"""

    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=32, max_length=32, pattern="^[a-f0-9]{32}$")
    preview_version: int = Field(strict=True, ge=1)


class AIActionProposalConfirm(BaseModel):
    """只允许用户明确确认当前预览版本。"""

    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=32, max_length=32, pattern="^[a-f0-9]{32}$")
    preview_version: int = Field(strict=True, ge=1)
    confirm: Literal[True]


class AIActionProposalPreview(BaseModel):
    """供页面展示的动作差异、证据、阻塞项和确认状态。"""

    confirmation_id: str
    action_type: str
    resource_type: str | None = None
    resource_id: str | None = None
    preview_version: int
    diff: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    risk_level: str
    status: Literal["PENDING", "EXECUTED", "EXPIRED", "CANCELLED", "INVALIDATED"]
    expires_at: datetime
    requires_user_confirmation: bool = True


class AIActionProposalRead(AIActionProposalPreview):
    """供提案 Inbox 安全展示的详情；不包含执行 payload 和资源快照。"""

    created_at: datetime
    business_reference: str | None = None
    source_route: str | None = None
    availability: Literal["AVAILABLE", "PERMISSION_REVOKED", "RESOURCE_UNAVAILABLE"]
    unavailable_reason: str | None = None
    revision_values: dict[str, Any] = Field(default_factory=dict)


class AIActionProposalPage(BaseModel):
    """当前用户动作提案分页结果。"""

    items: list[AIActionProposalRead]
    total: int


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

Task = Literal["inventory", "quotes", "purchase_request", "order_trace", "quality_acceptance", "delivery", "finance_reconciliation", "supplier", "supplier_profile", "analytics", "document"]


class Slots(BaseModel):
    """仅承载用户明确给出的业务条件；不接受数据库 ID 或身份字段。"""
    model_config = ConfigDict(extra="forbid")
    product_keyword: str | None = Field(default=None, max_length=200)
    rfq_no: str | None = Field(default=None, max_length=32)
    request_no: str | None = Field(default=None, max_length=32)
    po_no: str | None = Field(default=None, max_length=32)
    acceptance_no: str | None = Field(default=None, max_length=32)
    delivery_no: str | None = Field(default=None, max_length=32)
    reconciliation_no: str | None = Field(default=None, max_length=32)
    exception_no: str | None = Field(default=None, max_length=32, description="准确的运营异常编号，例如 EX20261025000001；不得猜测")
    supplier_code: str | None = Field(default=None, max_length=64)
    warehouse_keyword: str | None = Field(default=None, max_length=128)
    date_from: date | None = None
    date_to: date | None = None
    limit: int | None = Field(default=None, strict=True, ge=1, le=100)
    unit: str | None = Field(default=None, max_length=32)
    aggregate_products: bool = False

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


class PurchaseRequestActionFields(TypedDict, total=False):
    """采购申请修改候选；不与询价字段混用。"""
    purpose: str | None
    priority: str | None
    budget_amount: Decimal | None
    currency_code: str | None
    expected_date: str | None
    department_id: int | None
    items: list[PurchaseRequestItemCreate] | None


class RfqDraftActionFields(TypedDict, total=False):
    """询价草稿候选；仅含当前入口实际接受的字段。"""
    supplier_codes: list[str] | None
    quote_deadline: str | None
    requested_delivery_date: str | None
    delivery_requirements: str | None


class ExceptionTaskActionFields(TypedDict, total=False):
    """异常处理任务候选；不含负责人 ID，避免模型猜测用户。"""
    title: str | None
    priority: str | None
    due_at: str | None


class ReplenishmentActionFields(TypedDict, total=False):
    """补货申请候选；供应商和产品由槽位解析，不接受模型指定 ID。"""
    quantity: Decimal | None
    reason: str | None
    expected_date: str | None
    note: str | None


PurchaseRequestActionFields.__pydantic_config__ = ConfigDict(extra="forbid")
RfqDraftActionFields.__pydantic_config__ = ConfigDict(extra="forbid")
ExceptionTaskActionFields.__pydantic_config__ = ConfigDict(extra="forbid")
ReplenishmentActionFields.__pydantic_config__ = ConfigDict(extra="forbid")


class Understanding(BaseModel):
    """语义模型的严格输出契约，由程序校验后才能用于路由或拆分。"""
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["capability", "guidance", "query", "purchase_draft", "purchase_update", "purchase_submit", "purchase_order_submit", "rfq_draft", "exception_task", "replenishment_draft", "greeting", "unsupported", "clarify"]
    execution_mode: Literal["agent", "batch", "query", "document", "none"] = "none"
    clarification_slot: str | None = Field(default=None, min_length=1, max_length=64)
    clarification_options: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=5)
    dialogue_action: Literal["new", "continue", "modify", "switch", "cancel"] = "new"
    tasks: list[Task] = Field(default_factory=list, max_length=4)
    excluded_tasks: list[Task] = Field(default_factory=list, max_length=4)
    slots: Slots = Field(default_factory=Slots)
    action_fields: PurchaseRequestActionFields | RfqDraftActionFields | ExceptionTaskActionFields | ReplenishmentActionFields | None = None
    question: str | None = Field(default=None, max_length=1000)
    sub_tasks: list[SubTask] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def normalize(self):
        """校验任务一致性、执行模式和无环依赖，再移除明确排除的类别。"""
        if self.purpose == "purchase_draft" and self.action_fields is not None:
            # 草稿字段由服务端从完整问题重新整理；模型附带的候选字段不参与该入口。
            self.action_fields = None
        if self.action_fields is not None:
            self.action_fields = {key: value for key, value in self.action_fields.items() if value is not None}
            if self.purpose not in {"purchase_update", "rfq_draft", "exception_task", "replenishment_draft"}:
                raise ValueError("当前意图不接受动作候选字段，action_fields 必须为 null")
        if self.purpose == "clarify":
            if self.clarification_options and not self.clarification_slot:
                raise ValueError("澄清选项必须绑定待回答槽位")
            if self.clarification_slot and len(self.clarification_options) < 2:
                raise ValueError("可持久化澄清必须包含至少两个选项")
            if len(set(self.clarification_options)) != len(self.clarification_options):
                raise ValueError("澄清选项不得重复")
        elif self.clarification_slot is not None or self.clarification_options:
            raise ValueError("非澄清意图不得携带澄清槽位或选项")

        if self.purpose != "query":
            if self.execution_mode != "none" or self.tasks or self.sub_tasks:
                raise ValueError("非查询意图必须使用 none 模式且不含查询任务")
            if self.purpose in {"purchase_update", "purchase_submit", "rfq_draft"} and not self.slots.request_no:
                raise ValueError("修改、提交采购申请或创建询价草稿必须提供准确申请编号")
            if self.purpose == "purchase_order_submit" and not self.slots.po_no:
                raise ValueError("提交采购订单审批必须提供准确订单号")
            if self.purpose == "purchase_update":
                allowed = {"purpose", "priority", "budget_amount", "currency_code", "expected_date", "items", "department_id"}
                if not self.action_fields or set(self.action_fields) - allowed:
                    raise ValueError("申请修改意图必须提供有效的候选字段")
            elif self.purpose == "rfq_draft":
                allowed = {"supplier_codes", "quote_deadline", "requested_delivery_date", "delivery_requirements"}
                codes = (self.action_fields or {}).get("supplier_codes")
                if not isinstance(codes, list) or not codes or any(not isinstance(code, str) or not code.strip() for code in codes):
                    raise ValueError("创建询价提案必须提供用户明确指定的供应商编码")
                if set(self.action_fields or {}) - allowed:
                    raise ValueError("询价提案包含不允许的候选字段：" + ", ".join(sorted(set(self.action_fields) - allowed)))
            elif self.purpose == "exception_task":
                if not self.slots.exception_no:
                    raise ValueError("创建异常处理任务必须提供准确异常编号")
                allowed = {"title", "priority", "due_at"}
                fields = self.action_fields or {}
                title = fields.get("title")
                if not isinstance(title, str) or not title.strip():
                    raise ValueError("创建异常处理任务必须提供任务标题")
                if set(fields) - allowed:
                    raise ValueError("异常任务提案包含不允许的候选字段：" + ", ".join(sorted(set(fields) - allowed)))
                if fields.get("priority") is not None and fields["priority"] not in {"LOW", "NORMAL", "HIGH", "URGENT"}:
                    raise ValueError("异常任务优先级无效")
            elif self.purpose == "replenishment_draft":
                if not self.slots.supplier_code or not self.slots.product_keyword:
                    raise ValueError("创建补货申请必须提供准确的供应商编码和产品编码或名称")
                allowed = {"quantity", "reason", "expected_date", "note"}
                fields = self.action_fields or {}
                quantity = fields.get("quantity")
                if quantity is None or not isinstance(quantity, Decimal) or quantity <= 0:
                    raise ValueError("创建补货申请必须提供正数补货数量")
                reason = fields.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    raise ValueError("创建补货申请必须说明补货原因")
                if set(fields) - allowed:
                    raise ValueError("补货提案包含不允许的候选字段：" + ", ".join(sorted(set(fields) - allowed)))
            elif self.action_fields is not None:
                raise ValueError("当前意图不接受动作候选字段")
        elif self.dialogue_action == "cancel":
            if self.execution_mode != "none" or self.tasks or self.sub_tasks:
                raise ValueError("取消操作不得携带执行模式或查询任务")
        else:
            if self.execution_mode == "none":
                raise ValueError("查询必须显式选择执行模式")
            if not self.tasks:
                raise ValueError("查询必须明确业务任务")

        seen = set()
        for task in self.sub_tasks:
            if task.id in seen or not set(task.depends_on) <= seen:
                raise ValueError("子任务 ID 必须唯一，依赖必须来自前置子任务")
            if task.kind in self.excluded_tasks:
                raise ValueError("子任务不得执行被排除的意图")
            seen.add(task.id)
        normalized_tasks = list(dict.fromkeys(task for task in self.tasks if task not in self.excluded_tasks))
        subtask_kinds = {task.kind for task in self.sub_tasks}
        if self.sub_tasks and set(normalized_tasks) != subtask_kinds:
            raise ValueError("子任务类别必须与总任务一致")
        self.tasks = normalized_tasks

        if self.purpose == "query" and self.dialogue_action != "cancel":
            if self.execution_mode == "agent":
                if not set(self.tasks) <= {"inventory", "quotes", "purchase_request", "order_trace", "quality_acceptance", "delivery", "finance_reconciliation", "supplier", "supplier_profile"} or self.sub_tasks:
                    raise ValueError("agent 模式仅支持未拆分的库存、报价、采购申请、订单追溯、质量验收、到货、财务对账、供应商或供应商 360 查询目标")
                if set(self.tasks) & {"purchase_request", "order_trace", "quality_acceptance", "delivery", "finance_reconciliation", "supplier", "supplier_profile"} and len(self.tasks) != 1:
                    raise ValueError("按编号读取采购申请、订单追溯、质量验收、到货单、对账单、供应商和供应商 360 必须作为单一 Agent 目标执行")
                if "quality_acceptance" in self.tasks and not self.slots.acceptance_no:
                    raise ValueError("质量验收 Agent 目标必须提供准确验收编号")
                if "delivery" in self.tasks and not self.slots.delivery_no:
                    raise ValueError("到货 Agent 目标必须提供准确到货单号")
                if "finance_reconciliation" in self.tasks and not self.slots.reconciliation_no:
                    raise ValueError("财务对账 Agent 目标必须提供准确对账单号")
                if "supplier" in self.tasks and not self.slots.supplier_code:
                    raise ValueError("供应商 Agent 目标必须提供准确供应商编码")
                if "supplier_profile" in self.tasks and not self.slots.supplier_code:
                    raise ValueError("供应商 360 Agent 目标必须提供准确供应商编码")
            elif self.execution_mode == "batch":
                if not 2 <= len(self.sub_tasks) <= 6:
                    raise ValueError("batch 模式必须包含 2 至 6 个原子任务")
                if not subtask_kinds <= {"inventory", "quotes", "analytics", "document"}:
                    raise ValueError("批次暂不支持采购申请读取或订单追溯")
                if set(self.tasks) != subtask_kinds:
                    raise ValueError("batch 任务类别必须与子任务类别一致")
            elif self.execution_mode == "query":
                if self.tasks != ["analytics"] or len(self.sub_tasks) != 1 or self.sub_tasks[0].kind != "analytics":
                    raise ValueError("query 模式必须包含一个 analytics 子任务")
            elif self.execution_mode == "document":
                if self.tasks != ["document"] or len(self.sub_tasks) != 1 or self.sub_tasks[0].kind != "document":
                    raise ValueError("document 模式必须包含一个 document 子任务")
        return self

    @property
    def route(self) -> str:
        """query 直接使用已经校验的执行模式，非查询意图返回其 purpose。"""
        if self.dialogue_action == "cancel":
            return "cancel"
        if self.purpose != "query":
            return self.purpose
        return self.execution_mode

    @property
    def agent_goal(self) -> str:
        """将单一 Agent 类别映射到服务端完成条件。"""
        return ({"inventory": "inventory_query", "quotes": "supplier_quote_query",
                 "purchase_request": "purchase_request_query", "order_trace": "purchase_order_trace",
                 "quality_acceptance": "quality_acceptance_query", "delivery": "delivery_query",
                 "finance_reconciliation": "finance_reconciliation_query",
                 "supplier": "supplier_query", "supplier_profile": "supplier_profile"}.get(self.tasks[0], "unknown")
                if len(self.tasks) == 1 else "inventory_and_quotes_query" if set(self.tasks) == {"inventory", "quotes"} else "unknown")


class CapabilityManifest(BaseModel):
    """按当前用户权限裁剪的路由能力清单；不含业务记录或数据库资源 ID。"""

    model_config = ConfigDict(extra="forbid")

    contract_version: str
    digest: str
    agent_tools: list[dict[str, Any]]
    analytics_datasets: list[dict[str, Any]]
    document_search: bool
    resource_scopes: list[str]
    action_proposals: list[dict[str, Any]] = Field(default_factory=list)
    agent_tasks: list[str] = Field(default_factory=list)


class PendingClarification(BaseModel):
    """仅保存原问题摘要和一个受约束的待回答字段，不重复业务问题正文。"""

    model_config = ConfigDict(extra="forbid")

    state_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    question_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    slot: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=500)
    options: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(min_length=2, max_length=5)
    created_at: datetime
    expires_at: datetime
    permission_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    state_version: int = Field(strict=True, ge=1)
    contract_version: str = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_lifetime(self):
        if self.expires_at <= self.created_at:
            raise ValueError("澄清状态过期时间必须晚于创建时间")
        if len(set(self.options)) != len(self.options):
            raise ValueError("澄清状态选项不得重复")
        return self


class RouteRequest(BaseModel):
    """统一路由接口的输入；会话 ID 仍需服务端检查归属。"""
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = Field(default=None, gt=0)


ContextObjectType = Literal[
    "purchase_order",
    "purchase_request",
    "rfq",
    "delivery",
    "quality_acceptance",
    "inventory_balance",
    "finance_reconciliation",
    "supplier",
]


class AIContextRef(BaseModel):
    """页面只提交对象引用；服务端必须重新读取对象并校验权限。"""

    model_config = ConfigDict(extra="forbid")
    object_type: ContextObjectType
    object_id: int = Field(strict=True, gt=0)


class AIContextAskRequest(BaseModel):
    """页面 Copilot 的问题和当前对象；不接受业务字段快照。"""

    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    context: AIContextRef


class AIContextSnapshot(BaseModel):
    """已按当前用户权限读取的最小业务上下文。"""

    model_config = ConfigDict(extra="forbid")
    object_type: ContextObjectType
    object_id: int = Field(strict=True, gt=0)
    title: str
    reference_no: str | None = None
    status: str | None = None
    summary: list[str] = Field(default_factory=list)
    source_records: list[dict[str, Any]] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)


class AIContextAskResponse(BaseModel):
    """页面 Copilot 的确定性回答及来源。"""

    model_config = ConfigDict(extra="forbid")
    answer: str
    context: AIContextSnapshot
    citations: list[dict[str, Any]] = Field(default_factory=list)
    model: str = "context"
    provider: str = "chemicalops"


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


class PurchaseRequestInput(ToolSchema):
    request_no: str = Field(min_length=1, max_length=32, pattern=r"^PR[A-Za-z0-9_-]+$")


class PurchaseOrderTraceInput(ToolSchema):
    po_no: str = Field(min_length=1, max_length=32, pattern=r"^PO[-_A-Za-z0-9]+$")


class QualityAcceptanceInput(ToolSchema):
    acceptance_no: str = Field(min_length=4, max_length=32, pattern=r"^QA[A-Za-z0-9_-]+$")


class DeliveryInput(ToolSchema):
    delivery_no: str = Field(min_length=4, max_length=32, pattern=r"^DL[A-Za-z0-9_-]+$")


class FinanceReconciliationInput(ToolSchema):
    reconciliation_no: str = Field(min_length=4, max_length=32, pattern=r"^FR[A-Za-z0-9_-]+$")


class SupplierInput(ToolSchema):
    supplier_code: str = Field(min_length=1, max_length=64)


class SupplierProfileInput(ToolSchema):
    supplier_code: str = Field(min_length=1, max_length=64)


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


class PurchaseRequestResult(ToolSchema):
    tool: Literal["purchase_requests.get_by_no"] = "purchase_requests.get_by_no"
    total_rows: int
    rows: list[dict[str, Any]]
    sources: list["Source"]


class QualityAcceptanceRow(ToolSchema):
    acceptance_no: str
    result: str
    inspection_time: datetime | None
    test_result: dict[str, Any] | list[Any] | None
    certificate_complete: bool
    report_available: bool
    conclusion: str | None


class QualityAcceptanceResult(ToolSchema):
    tool: Literal["quality_acceptances.get_by_no"] = "quality_acceptances.get_by_no"
    total_rows: int
    rows: list[QualityAcceptanceRow]
    sources: list["Source"]


class DeliveryItemRow(ToolSchema):
    line_no: int
    planned_quantity: Decimal
    actual_quantity: Decimal
    short_quantity: Decimal
    document_complete: bool


class DeliveryRow(ToolSchema):
    delivery_no: str
    status: str
    expected_arrival_date: date | None
    actual_arrival_date: date | None
    items: list[DeliveryItemRow]


class DeliveryResult(ToolSchema):
    tool: Literal["deliveries.get_by_no"] = "deliveries.get_by_no"
    total_rows: int
    rows: list[DeliveryRow]
    sources: list["Source"]


class FinanceStatusCount(ToolSchema):
    status: str
    count: int
    amount: Decimal


class FinanceReconciliationLine(ToolSchema):
    reconciliation_item_id: int
    line_no: int
    product_name: str
    unit_name: str
    ordered_quantity: Decimal
    received_quantity: Decimal
    accepted_quantity: Decimal
    returned_quantity: Decimal
    reconciliation_quantity: Decimal
    amount_incl_tax: Decimal
    invoiced_reserved_amount: Decimal
    verified_invoice_amount: Decimal
    unmatched_invoice_capacity: Decimal
    warnings: list[str]


class FinancePaymentPrecheck(ToolSchema):
    reconciliation_confirmed: bool
    verified_invoice_amount: Decimal
    active_payment_amount: Decimal
    remaining_reconciliation_amount: Decimal
    max_new_payment_amount: Decimal
    currency_code: str
    blockers: list[str]
    limitation: str


class FinanceReconciliationRow(ToolSchema):
    reconciliation_no: str
    status: str
    currency_code: str
    total_amount: Decimal
    invoices: list[FinanceStatusCount]
    payments: list[FinanceStatusCount]
    reconciliation_version: int
    source_changed: bool
    line_warnings: list[str]
    lines: list[FinanceReconciliationLine]
    unallocated_invoices: list[str]
    payment_precheck: FinancePaymentPrecheck


class FinanceReconciliationResult(ToolSchema):
    tool: Literal["finance_reconciliations.get_by_no"] = "finance_reconciliations.get_by_no"
    total_rows: int
    rows: list[FinanceReconciliationRow]
    sources: list["Source"]


class SupplierRow(ToolSchema):
    supplier_code: str
    supplier_name: str
    status: str
    region: str | None
    business_scope: str | None
    cooperation_level: str | None
    payment_terms: str | None
    default_lead_days: int | None


class SupplierResult(ToolSchema):
    tool: Literal["suppliers.get_by_code"] = "suppliers.get_by_code"
    total_rows: int
    rows: list[SupplierRow]
    sources: list["Source"]


class SupplierProfileResult(ToolSchema):
    """供应商 360：各业务段按当前权限裁剪，金额与数量由服务端格式化。"""

    tool: Literal["suppliers.profile"] = "suppliers.profile"
    supplier_code: str
    supplier_name: str | None
    status: str | None
    sections: list[dict[str, Any]]
    sources: list["Source"]
    answer: str


class PurchaseOrderTraceResult(ToolSchema):
    tool: Literal["purchase_orders.trace_by_no"] = "purchase_orders.trace_by_no"
    po_no: str
    supplier: str | None
    order_status: str
    order_updated_at: str | None
    stages: list[dict[str, Any]]
    conclusion: list[str]
    unavailable_stages: list[str]
    source_records: list[dict[str, Any]]
    answer: str


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
    tax_included: bool | None
    unit_price: Decimal
    quoted_quantity: Decimal
    moq_quantity: Decimal | None
    moq_unit_id: int | None
    lead_days: int | None
    freight_amount: Decimal | None
    freight_tax_rate: Decimal | None
    freight_tax_included: bool | None
    payment_terms: str | None
    cost_analysis: dict | None = None
    rank: int | None = None
    comparison_status: Literal["COMPARABLE", "NOT_COMPARABLE"] = "NOT_COMPARABLE"
    comparison_reasons: list[str] = Field(default_factory=list)
    quality_history: dict | None = None


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
    comparison_basis: str = "仅在币种、单位、税率、含税口径和供应商型号相同的组内按单价排名；成本候选仅在完整可比报价中按全部询价明细的已知总成本确定，账期、交期和可见质量验收事实作为解释与风险，不合成综合分，不做汇率换算"
    total_rows: int
    truncated: bool
    rows: list[QuoteRow]
    recommendation: dict | None = None
    sources: list[Source]
    warnings: list[str]


# Agent 任务与动作

class TaskCreate(ToolSchema):
    question: str = Field(min_length=1, max_length=2000)
    route_token: str | None = Field(default=None, max_length=64000)
    conversation_id: int | None = Field(default=None, gt=0)


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

def schema_error_details(exc: ValidationError) -> list[dict]:
    """反馈结构位置与本地根校验规则，不包含输入值或模型原文。"""
    details = []
    for error in exc.errors()[:6]:
        detail = {"type": error["type"], "loc": error["loc"]}
        if error["type"] == "value_error" and not error["loc"]:
            detail["rule"] = error["msg"]
        details.append(detail)
    return details

def schema_response_format(model: type[BaseModel], name: str) -> dict:
    schema = model.model_json_schema()

    def strict(node):
        if isinstance(node, dict):
            # 兼容服务要求 anyOf 分支显式声明 type，不能只含本地引用。
            for branch in node.get("anyOf", []):
                reference = branch.get("$ref", "") if isinstance(branch, dict) else ""
                if reference.startswith("#/$defs/"):
                    definition = deepcopy(schema["$defs"][reference.removeprefix("#/$defs/")])
                    branch.pop("$ref")
                    branch.update(definition)
            node.pop("default", None)
            # 当前服务的 Schema 子集不接受 format=date；模型约束 ISO 外形，Pydantic 校验真实日期。
            if node.get("format") == "date":
                node.pop("format")
                node["pattern"] = r"^\d{4}-\d{2}-\d{2}$"
            if node.get("type") == "object":
                if not node.get("properties"):
                    raise ValueError("严格模型输出 Schema 必须声明非空对象字段，不能使用开放字典")
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in list(node.values()):
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)

    strict(schema)
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
