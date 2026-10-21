"""会话、消息、上下文和查询留档的持久化入口。

状态更新函数不提交事务；聊天轮次及管理操作按原有边界提交。
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.orm import Session
from pydantic import TypeAdapter

from app.core.errors import BusinessValidationError
from app.core.cache import cached
from app.core.config import get_settings
from app.modules.ai.model import AIAgentTask, AIPurchaseDraftConfirmation, AIConversation, AIConversationState, AIMessage, AIQueryLog
from app.modules.ai.schema import AIChatRequest, AIQueryTrace, AIHistorySnapshot, AIMessageSnapshot
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


LOGGER = logging.getLogger("chemicalops.ai")


def get_owned_conversation(db: Session, user: User, conversation_id: int) -> AIConversation:
    """读取当前用户自己的会话，其他用户的会话按不存在处理。"""

    conversation = db.scalar(select(AIConversation).where(AIConversation.id == conversation_id, AIConversation.user_id == user.id))
    if conversation is None:
        raise BusinessValidationError("AI 会话不存在或无权访问")
    return conversation


def conversation_state_enabled(db: Session) -> bool:
    """迁移尚未执行时保持旧版本可用；完成 017 后自动启用持久化上下文。"""

    try:
        bind = db.get_bind()
        return bool(bind is not None and inspect(bind).has_table(AIConversationState.__tablename__))
    except Exception as exc:
        LOGGER.warning("AI 会话状态表检查失败 error_type=%s", exc.__class__.__name__)
        return False


def permission_snapshot(db: Session, user: User) -> dict[str, list[str]]:
    return {"roles": get_user_role_codes(db, user.id), "permissions": get_user_permission_codes(db, user.id)}


def load_conversation_state(db: Session, conversation: AIConversation) -> AIConversationState | None:
    if not conversation_state_enabled(db):
        return None
    return db.scalar(select(AIConversationState).where(AIConversationState.conversation_id == conversation.id))


def query_log_enabled(db: Session) -> bool:
    """迁移 020 尚未执行时跳过留档，保持旧环境可用。"""

    try:
        bind = db.get_bind()
        return bool(bind is not None and inspect(bind).has_table(AIQueryLog.__tablename__))
    except Exception as exc:
        LOGGER.warning("AI 查询留档表检查失败 error_type=%s", exc.__class__.__name__)
        return False


def append_query_log(db: Session, conversation: AIConversation, trace: AIQueryTrace) -> None:
    """每轮 Text2SQL 追加一条留档，与会话级“最近一次”状态互补保留历史轨迹。"""

    if not query_log_enabled(db):
        return
    db.add(
        AIQueryLog(
            conversation_id=conversation.id,
            thread_id=trace.thread_id,
            question=trace.query,
            question_hash=hashlib.sha256(trace.query.encode("utf-8")).hexdigest()[:16],
            dataset=trace.dataset or "unknown",
            dataset_label=trace.dataset_label,
            slots=trace.model_dump(mode="json", include={"slots"})["slots"],
            template=trace.template,
            sql_text=trace.sql,
            row_count=trace.row_count,
            truncated=trace.truncated,
            unit=trace.unit,
            executed_at=trace.executed_at,
        )
    )


def save_query_state(
    db: Session,
    user: User,
    conversation: AIConversation,
    *,
    plan: object,
    trace: AIQueryTrace,
    citations: list[dict[str, object]],
) -> None:
    if not conversation_state_enabled(db):
        return
    existing = load_conversation_state(db, conversation)
    state = existing or AIConversationState(
        conversation_id=conversation.id,
        thread_id=f"ai:{user.id}:{conversation.id}",
        state_version=1,
    )
    state.query_plan = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else None
    state.query_trace = trace.model_dump(mode="json", exclude={"sql", "parameterized_sql", "rows"})
    state.permission_snapshot = permission_snapshot(db, user)
    state.attachment_refs = [
        {key: item.get(key) for key in ("file_id", "file_name", "parse_status", "parser", "object_key") if key in item}
        for item in citations
        if isinstance(item, dict) and item.get("file_id")
    ] or None
    if existing is None:
        db.add(state)


def delete_conversation(db: Session, user: User, conversation_id: int) -> None:
    """删除当前用户自己的会话及其消息。"""
    conversation = get_owned_conversation(db, user, conversation_id)
    # 取消任务并提升版本号，使持有旧租约的运行者无法覆盖删除状态。
    tasks = list(db.scalars(select(AIAgentTask).where(AIAgentTask.user_id == user.id,
        AIAgentTask.status.in_(("RUNNING", "WAITING_INPUT"))).with_for_update()).all())
    for task in tasks:
        if (task.payload.get("chat") or {}).get("conversation_id") != conversation.id:
            continue
        task.status = "CANCELLED"
        task.revision += 1
        task.reply = "会话已删除，任务已取消。"
        task.payload = {**task.payload, "chat": None,
                        "memory_state": {**(task.payload.get("memory_state") or {}), "pending": None}}
        from app.modules.task_queue.model import TaskExecution, TaskResourceLock
        executions = list(db.scalars(select(TaskExecution).where(TaskExecution.business_id == task.id,
            TaskExecution.task_type == "agent.run", TaskExecution.actor_id == user.id,
            TaskExecution.status.in_(("QUEUED", "RUNNING", "RETRYING"))).with_for_update()).all())
        for execution in executions:
            execution.status = "CANCELLED"
            execution.fencing_token += 1
            execution.lease_until = None
            db.execute(delete(TaskResourceLock).where(TaskResourceLock.execution_id == execution.id))
    confirmations = db.scalars(select(AIPurchaseDraftConfirmation).where(
        AIPurchaseDraftConfirmation.user_id == user.id,
        AIPurchaseDraftConfirmation.status == "PENDING",
        func.json_contains(AIPurchaseDraftConfirmation.evidence,
                           func.json_object("conversation_id", conversation.id)) == 1).with_for_update()).all()
    for confirmation in confirmations:
        confirmation.status = "CANCELLED"
    if conversation_state_enabled(db):
        db.execute(delete(AIConversationState).where(AIConversationState.conversation_id == conversation.id))
    if query_log_enabled(db):
        db.execute(delete(AIQueryLog).where(AIQueryLog.conversation_id == conversation.id))
    db.execute(delete(AIMessage).where(AIMessage.conversation_id == conversation.id))
    db.delete(conversation)
    db.commit()


def clear_query_context(db: Session, user: User, conversation_id: int) -> None:
    """清除结构化 QueryPlan，不删除用户可见聊天记录。"""

    conversation = get_owned_conversation(db, user, conversation_id)
    if conversation_state_enabled(db):
        db.execute(delete(AIConversationState).where(AIConversationState.conversation_id == conversation.id))
        db.commit()


def list_conversations(db: Session, user: User, *, limit: int = 50) -> tuple[list[AIConversation], int]:
    """按最近消息时间返回当前用户会话。"""

    condition = AIConversation.user_id == user.id
    total = db.scalar(select(func.count(AIConversation.id)).where(condition)) or 0
    items = list(db.scalars(select(AIConversation).where(condition).order_by(AIConversation.last_message_at.desc(), AIConversation.id.desc()).limit(limit)).all())
    return items, total


def update_conversation(db: Session, user: User, conversation_id: int, *, title: str | None = None, pinned: bool | None = None) -> AIConversation:
    """只更新当前用户自己的会话管理字段。"""
    conversation = get_owned_conversation(db, user, conversation_id)
    if title is not None:
        normalized = title.strip()
        if not normalized or len(normalized) > 255:
            raise BusinessValidationError("会话标题长度需为 1 至 255 个字符")
        conversation.title = normalized
    if pinned is not None:
        conversation.pinned = pinned
    db.commit()
    db.refresh(conversation)
    return conversation


def list_messages(db: Session, user: User, conversation_id: int, *, limit: int = 100) -> tuple[list[AIMessageSnapshot], int]:
    """读取当前用户会话消息。"""

    get_owned_conversation(db, user, conversation_id)
    snapshot = cached(db, "ai_history", (user.id, conversation_id, limit), TypeAdapter(AIHistorySnapshot),
                      lambda: _load_messages(db, conversation_id, limit),
                      ttl=get_settings().redis_session_ttl_seconds)
    return snapshot.items, snapshot.total


def _load_messages(db: Session, conversation_id: int, limit: int) -> AIHistorySnapshot:
    condition = AIMessage.conversation_id == conversation_id
    total = db.scalar(select(func.count(AIMessage.id)).where(condition)) or 0
    items = list(db.scalars(select(AIMessage).where(condition).order_by(AIMessage.created_at.asc(), AIMessage.id.asc()).limit(limit)).all())
    return AIHistorySnapshot(items=[AIMessageSnapshot.model_validate(item) for item in items], total=total)


def ensure_conversation(db: Session, user: User, data: AIChatRequest) -> AIConversation:
    """获取或创建会话，并保存权限快照。"""

    if data.conversation_id:
        conversation = get_owned_conversation(db, user, data.conversation_id)
        conversation.permission_snapshot = permission_snapshot(db, user)
        return conversation
    first_user = next((message.content.strip() for message in data.messages if message.role == "user" and message.content.strip()), "新建对话")
    conversation = AIConversation(
        user_id=user.id,
        title=first_user[:80],
        business_scene="GENERAL",
        permission_snapshot=permission_snapshot(db, user),
        status="ACTIVE",
        last_message_at=datetime.now(),
    )
    db.add(conversation)
    db.flush()
    return conversation


def save_chat_turn(db: Session, conversation: AIConversation, question: str, answer: str, *, citations: list | None = None) -> None:
    """同步和流式回复共用同一落库路径；调用方决定在回复的哪个阶段提交。"""
    db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=question, citations=citations))
    db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=answer, citations=citations))
    conversation.last_message_at = datetime.now()
    db.commit()


def previous_query_plan(db: Session, conversation: AIConversation):
    """读取上一轮计划，无效历史状态按无计划处理。"""
    from app.modules.ai.schema import QueryPlan

    state = load_conversation_state(db, conversation)
    if state and state.query_plan:
        try:
            return QueryPlan.model_validate(state.query_plan)
        except (TypeError, ValueError):
            LOGGER.warning("AI 会话 QueryPlan 状态无效 conversation_id=%s", conversation.id)
    return None


def save_conversation_memory(db: Session, user: User, conversation_id: int, memory: dict) -> None:
    row = db.scalar(
        select(AIConversationState)
        .where(AIConversationState.conversation_id == conversation_id)
        .with_for_update()
    )
    if row is None:
        row = AIConversationState(
            conversation_id=conversation_id,
            thread_id=f"ai:{user.id}:{conversation_id}",
            state_version=1,
        )
        db.add(row)
    row.memory_state = json.loads(json.dumps(memory, ensure_ascii=False))
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)


def save_batch_state(db: Session, user: User, conversation: AIConversation, state: AIConversationState | None, tasks: list[dict]) -> None:
    """保存批量任务上下文，与聊天消息共用调用方事务。"""
    if not conversation_state_enabled(db):
        return
    if state is None:
        state = AIConversationState(conversation_id=conversation.id, thread_id=f"ai:{user.id}:{conversation.id}")
        db.add(state)
    state.memory_state = {**(state.memory_state or {}), "batch_tasks": tasks}
    state.query_plan = None  # 多计划不能伪装成最后一项单计划。
    state.permission_snapshot = permission_snapshot(db, user)
    state.state_version = (state.state_version or 0) + 1


def save_order_trace_state(db: Session, user: User, thread_id: str | None, trace: AIQueryTrace) -> None:
    """订单追溯清除旧单计划，留档仍由调用方处理。"""
    state = db.scalar(select(AIConversationState).where(AIConversationState.thread_id == thread_id)) if thread_id else None
    if state is not None:
        state.query_plan = None
        state.query_trace = trace.model_dump(mode="json", exclude={"sql", "parameterized_sql", "rows"})
        state.permission_snapshot = permission_snapshot(db, user)


def append_message(db: Session, conversation: AIConversation, role: str, content: str, *, citations: list | None = None) -> None:
    """追加消息并更新会话时间，不提前提交模型调用前后的事务。"""
    db.add(AIMessage(conversation_id=conversation.id, message_role=role, content=content, citations=citations))
    conversation.last_message_at = datetime.now()


def lock_conversation_state(db: Session, conversation: AIConversation) -> AIConversationState | None:
    """Agent 要求状态表已就绪，在当前事务中锁定上下文。"""
    return db.scalar(select(AIConversationState)
        .where(AIConversationState.conversation_id == conversation.id).with_for_update())
