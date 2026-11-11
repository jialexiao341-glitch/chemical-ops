"""AI 会话和消息数据库模型。"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AIAgentTask(Base):
    """个人只读 Agent 任务；保存公开动作/结果，不保存模型思维链或提示词。"""

    __tablename__ = "ai_agent_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    revision: Mapped[int] = mapped_column(nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    reply: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AIPurchaseDraftConfirmation(Base):
    """一次性采购草稿确认快照；快照消费与申请写入处于同一事务。"""

    __tablename__ = "ai_purchase_draft_confirmations"
    __table_args__ = (UniqueConstraint("confirmation_id", name="uq_ai_purchase_draft_confirmation_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    confirmation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False, index=True)
    preview_version: Mapped[int] = mapped_column(nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    draft_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    object_versions: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False)
    purchase_request_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_requests.id"), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    executed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)


class AIAgentActionProposal(Base):
    """用户确认前的动作快照与执行结果账本。"""

    __tablename__ = "ai_agent_action_proposals"
    __table_args__ = (
        UniqueConstraint("confirmation_id", name="uq_ai_action_proposal_confirmation"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_ai_action_proposal_user_idempotency"),
        Index("ix_ai_action_proposal_owner_status", "user_id", "status"),
        Index("ix_ai_action_proposal_expiry_status", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    confirmation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preview_version: Mapped[int] = mapped_column(nullable=False, default=1)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_resource_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    department_scope_snapshot: Mapped[list | None] = mapped_column(JSON, nullable=True)
    warehouse_scope_snapshot: Mapped[list | None] = mapped_column(JSON, nullable=True)
    diff: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blockers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))
    executed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)


class AIConversation(Base):
    """登录用户可见的 AI 会话。"""

    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_scene: Mapped[str] = mapped_column(String(64), nullable=False, default="GENERAL")
    permission_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    last_message_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))


class AIMessage(Base):
    """AI 会话中的一条消息。"""

    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id"), nullable=False)
    message_role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class AIConversationState(Base):
    """会话级结构化状态；不把任务执行 checkpoint 混入用户消息。"""

    __tablename__ = "ai_conversation_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id"), nullable=False, unique=True)
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    memory_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    query_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    query_trace: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    permission_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attachment_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    state_version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )


class AIQueryLog(Base):
    """Text2SQL 每轮查询的追加式留档；会话状态只留最近一次，本表保留历史轨迹。"""

    __tablename__ = "ai_query_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id"), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slots: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    template: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int] = mapped_column(default=0, nullable=False)
    truncated: Mapped[bool] = mapped_column(default=False, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))

class AIFeedback(Base):
    """Agent 任务反馈；只保存公开运行元数据，不保存提示词正文或模型思维链。"""

    __tablename__ = "ai_feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "task_id", name="uq_ai_feedback_user_task"),
        Index("ix_ai_feedback_task", "task_id"),
        Index("ix_ai_feedback_rating_created", "rating", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    task_id: Mapped[str] = mapped_column(ForeignKey("ai_agent_tasks.id"), nullable=False)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_versions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))


class AIRegressionCase(Base):
    """已审阅的 Agent 回归用例；问题文本需人工脱敏，导出时不带任务原文和用户身份。"""

    __tablename__ = "ai_regression_cases"
    __table_args__ = (
        UniqueConstraint("case_key", name="uq_ai_regression_case_key"),
        Index("ix_ai_regression_case_status_created", "status", "created_at"),
        Index("ix_ai_regression_case_creator_created", "created_by", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    case_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_task_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_tasks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    forbidden_tasks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    created_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class AIOperationSuggestion(Base):
    """每个运营异常对应一条共享建议，处理状态由有权限的人员共同维护。"""

    __tablename__ = 'ai_operation_suggestions'
    __table_args__ = (UniqueConstraint('exception_id', name='uq_ai_operation_suggestion_exception'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exception_id: Mapped[int] = mapped_column(ForeignKey('operation_exceptions.id'), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='OPEN')
    handled_by: Mapped[int | None] = mapped_column(ForeignKey('sys_users.id'), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey('operation_tasks.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class AIModelProfile(Base):
    """可在前端切换的 OpenAI 兼容模型配置；密钥不随响应返回明文。"""

    __tablename__ = "ai_model_profiles"
    __table_args__ = (
        UniqueConstraint("profile_name", name="uq_ai_model_profile_name"),
        Index("ix_ai_model_profile_default", "is_default"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    context_window: Mapped[int | None] = mapped_column(nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    temperature: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0.2)
    timeout_seconds: Mapped[int] = mapped_column(nullable=False, default=60)
    max_retries: Mapped[int] = mapped_column(nullable=False, default=2)
    max_concurrency: Mapped[int] = mapped_column(nullable=False, default=8)
    stream_usage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )
