"""AI 会话和消息数据库模型。"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
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
    """会话级结构化状态；不把 LangGraph 内部 checkpoint 混入用户消息。"""

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
