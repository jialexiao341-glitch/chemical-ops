"""会话、消息、上下文和查询留档的持久化入口。

状态更新函数不提交事务；聊天轮次及管理操作按原有边界提交。
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.orm import Session
from pydantic import TypeAdapter

from app.core.errors import BusinessValidationError
from app.core.cache import cached
from app.core.config import get_settings
from app.modules.ai.model import AIAgentTask, AIPurchaseDraftConfirmation, AIConversation, AIConversationState, AIMessage, AIQueryLog
from app.modules.ai.schema import AIChatRequest, AIQueryTrace, AIHistorySnapshot, AIMessageSnapshot, PendingClarification, Understanding
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


LOGGER = logging.getLogger("chemicalops.ai")


def get_owned_conversation(db: Session, user: User, conversation_id: int, *, allow_stale: bool = False) -> AIConversation:
    """读取当前用户自己的会话，其他用户的会话按不存在处理。"""

    conversation = db.scalar(select(AIConversation).where(AIConversation.id == conversation_id, AIConversation.user_id == user.id))
    if conversation is None:
        raise BusinessValidationError("AI 会话不存在或无权访问")
    if not allow_stale:
        from app.modules.system.data_scope import department_scope_snapshot
        scope = department_scope_snapshot(db, user)
        if scope is not None and (conversation.permission_snapshot or {}).get("department_scope") != scope:
            raise BusinessValidationError("会话创建后的部门授权已变化，请新建会话")
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
    from app.modules.system.data_scope import department_scope_snapshot
    return {"roles": get_user_role_codes(db, user.id), "permissions": get_user_permission_codes(db, user.id),
            "department_scope": department_scope_snapshot(db, user)}


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
    conversation = get_owned_conversation(db, user, conversation_id, allow_stale=True)
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
    """置顶优先，再按最近消息时间返回当前用户会话。"""

    condition = (AIConversation.user_id == user.id) & (AIConversation.business_scene != "FLOAT")
    from app.modules.system.data_scope import department_scope_snapshot
    scope = department_scope_snapshot(db, user)
    if scope is not None:
        conversations = db.scalars(select(AIConversation).where(condition).order_by(
            AIConversation.pinned.desc(), AIConversation.last_message_at.desc(), AIConversation.id.desc()
        ))
        visible = [item for item in conversations if (item.permission_snapshot or {}).get("department_scope") == scope]
        return visible[:limit], len(visible)
    total = db.scalar(select(func.count(AIConversation.id)).where(condition)) or 0
    items = list(db.scalars(select(AIConversation).where(condition).order_by(AIConversation.pinned.desc(), AIConversation.last_message_at.desc(), AIConversation.id.desc()).limit(limit)).all())
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


def list_messages(db: Session, user: User, conversation_id: int, *, limit: int = 100, before_id: int | None = None) -> tuple[list[AIMessageSnapshot], int]:
    """读取本人消息，默认最近一页；可按消息 ID 向前分页。"""

    get_owned_conversation(db, user, conversation_id)
    snapshot = cached(db, "ai_history", (user.id, conversation_id, limit, before_id), TypeAdapter(AIHistorySnapshot),
                      lambda: _load_messages(db, conversation_id, limit, before_id=before_id),
                      ttl=get_settings().redis_session_ttl_seconds)
    return snapshot.items, snapshot.total


def _load_messages(db: Session, conversation_id: int, limit: int, *, before_id: int | None = None) -> AIHistorySnapshot:
    condition = AIMessage.conversation_id == conversation_id
    total = db.scalar(select(func.count(AIMessage.id)).where(condition)) or 0
    query = select(AIMessage).where(condition)
    if before_id is not None:
        query = query.where(AIMessage.id < before_id)
    items = list(db.scalars(query.order_by(AIMessage.id.desc()).limit(limit)).all())
    items.reverse()
    return AIHistorySnapshot(items=[AIMessageSnapshot.model_validate(item) for item in items], total=total)


def ensure_conversation(db: Session, user: User, data: AIChatRequest) -> AIConversation:
    """获取或创建会话，并保存权限快照。"""

    if data.conversation_id:
        conversation = get_owned_conversation(db, user, data.conversation_id)
        if (conversation.business_scene == 'FLOAT') != (data.conversation_scene == 'FLOAT'):
            raise BusinessValidationError('悬浮助手与工作台会话不能混用')
        conversation.permission_snapshot = permission_snapshot(db, user)
        return conversation
    first_user = next((message.content.strip() for message in data.messages if message.role == "user" and message.content.strip()), "新建对话")
    conversation = AIConversation(
        user_id=user.id,
        title=first_user[:80],
        business_scene=data.conversation_scene,
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
    merged = {**(row.memory_state or {}), **memory}
    next_version = (row.state_version or 0) + 1
    if isinstance(merged.get("pending_clarification"), dict):
        try:
            pending = PendingClarification.model_validate(merged["pending_clarification"])
            merged["pending_clarification"] = pending.model_copy(update={"state_version": next_version}).model_dump(mode="json")
        except (TypeError, ValueError):
            merged.pop("pending_clarification", None)
    row.memory_state = json.loads(json.dumps(merged, ensure_ascii=False))
    row.state_version = next_version
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)


def _permission_digest(db: Session, user: User) -> str:
    value = json.dumps(permission_snapshot(db, user), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def save_pending_clarification(
    db: Session, user: User, conversation_id: int, question: str, decision: Understanding, *,
    expected_state_id: str | None = None, expected_state_version: int | None = None,
    now: datetime | None = None, ttl_seconds: int = 900,
) -> PendingClarification:
    """创建或 CAS 替换待澄清状态；不保存原问题明文。"""
    conversation = get_owned_conversation(db, user, conversation_id)
    if not conversation_state_enabled(db):
        raise BusinessValidationError("当前环境无法持久化澄清状态，请重新发起该请求。")
    if not decision.clarification_slot or len(decision.clarification_options) < 2:
        raise BusinessValidationError("澄清未提供可绑定的选项，不能安全续接。")
    state = lock_conversation_state(db, conversation)
    if state is None:
        if expected_state_id is not None or expected_state_version is not None:
            raise BusinessValidationError("澄清状态已变化，请重新选择。")
        state = AIConversationState(conversation_id=conversation.id, thread_id=f"ai:{user.id}:{conversation.id}",
                                    state_version=1, memory_state={})
        db.add(state)
        db.flush()
    else:
        db.refresh(state)
    memory = dict(state.memory_state or {})
    raw_pending = memory.get("pending_clarification")
    if raw_pending:
        current = PendingClarification.model_validate(raw_pending)
        if current.state_id != expected_state_id or state.state_version != expected_state_version or current.state_version != state.state_version:
            raise BusinessValidationError("澄清状态版本冲突，请重新选择。")
    elif expected_state_id is not None or expected_state_version is not None:
        raise BusinessValidationError("澄清状态已变化，请重新选择。")

    expected_version = int(state.state_version or 0)
    next_version = expected_version + 1
    created = now or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    pending = PendingClarification(
        state_id=uuid4().hex,
        question_hash=hashlib.sha256(question.encode("utf-8")).hexdigest(),
        slot=decision.clarification_slot,
        question=decision.question or "请回答本轮澄清问题。",
        options=decision.clarification_options,
        created_at=created,
        expires_at=created + timedelta(seconds=ttl_seconds),
        permission_hash=_permission_digest(db, user),
        state_version=next_version,
        contract_version="1",
    )
    memory["pending_clarification"] = pending.model_dump(mode="json")
    permission_state = permission_snapshot(db, user)
    _write_state_values(
        db, state, current_version=expected_version, next_version=next_version,
        memory=memory, error="澄清状态版本冲突，请重新选择。",
        permission_snapshot_value=permission_state)
    return pending


def load_pending_clarification(db: Session, user: User, conversation_id: int, *, now: datetime | None = None) -> PendingClarification | None:
    """读取本人有效澄清；过期、权限改变、版本不符或损坏状态被清除并拒绝续接。"""
    conversation = get_owned_conversation(db, user, conversation_id)
    state = load_conversation_state(db, conversation)
    raw = (state.memory_state or {}).get("pending_clarification") if state else None
    if not raw:
        return None
    try:
        pending = PendingClarification.model_validate(raw)
    except (TypeError, ValueError):
        clear_pending_clarification(db, user, conversation_id)
        raise BusinessValidationError("澄清状态无效，请重新发起原问题。") from None
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    message = None
    if current_time >= pending.expires_at:
        message = "澄清状态已过期，请重新发起原问题。"
    elif pending.contract_version != "1" or pending.state_version != state.state_version:
        message = "澄清状态版本已变化，请重新发起原问题。"
    elif pending.permission_hash != _permission_digest(db, user):
        message = "权限已变化，请重新发起原问题。"
    if message:
        clear_pending_clarification(db, user, conversation_id, state_id=pending.state_id,
                                    expected_state_version=state.state_version, allow_stale_version=True)
        raise BusinessValidationError(message)
    return pending


def _write_state_values(db: Session, state: AIConversationState, *, current_version: int,
                        next_version: int, memory: dict, error: str,
                        permission_snapshot_value: dict | None = None) -> int:
    """以 state_version 为 CAS 写入状态；显式写时间避免不同方言的 onupdate 差异。"""
    values = {
        "memory_state": memory,
        "state_version": next_version,
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    if permission_snapshot_value is not None:
        values["permission_snapshot"] = permission_snapshot_value
    count = db.execute(update(AIConversationState).where(
        AIConversationState.id == state.id,
        AIConversationState.state_version == current_version,
    ).values(**values)).rowcount
    if count != 1:
        raise BusinessValidationError(error)
    db.expire(state)
    return next_version


def _clear_pending_values(db: Session, state: AIConversationState, memory: dict, *, current_version: int,
                          next_version: int, error: str) -> int:
    return _write_state_values(
        db, state, current_version=current_version, next_version=next_version,
        memory=memory, error=error)


def clear_pending_clarification(
    db: Session, user: User, conversation_id: int, *, state_id: str | None = None,
    expected_state_version: int | None = None, allow_stale_version: bool = False,
) -> int:
    """以状态 ID 和版本 CAS 清除 pending，保留同一 JSON 中的其他业务状态。"""
    conversation = get_owned_conversation(db, user, conversation_id)
    state = lock_conversation_state(db, conversation)
    if state is None:
        return 0
    db.refresh(state)
    memory = dict(state.memory_state or {})
    raw = memory.get("pending_clarification")
    if not raw:
        if state_id is not None:
            raise BusinessValidationError("澄清状态已被消费或清除。")
        return int(state.state_version or 0)
    current_version = int(state.state_version or 0)
    try:
        pending = PendingClarification.model_validate(raw)
    except (TypeError, ValueError):
        if state_id is not None or expected_state_version is not None:
            raise BusinessValidationError("澄清状态无效或已变化，请重新发起原问题。") from None
        memory.pop("pending_clarification", None)
        return _clear_pending_values(
            db, state, memory, current_version=current_version, next_version=current_version + 1,
            error="澄清状态版本冲突，请重新选择。")
    if ((state_id is not None and pending.state_id != state_id)
            or (expected_state_version is not None and current_version != expected_state_version)
            or (pending.state_version != current_version and not allow_stale_version)):
        raise BusinessValidationError("澄清状态版本冲突，请重新选择。")
    memory.pop("pending_clarification", None)
    next_version = current_version + 1
    return _clear_pending_values(
        db, state, memory, current_version=current_version, next_version=next_version,
        error="澄清状态版本冲突，请重新选择。")


def original_question_for_pending(db: Session, user: User, conversation_id: int, pending: PendingClarification) -> str | None:
    """按摘要从本人会话消息中还原原问题，不在澄清状态重复存正文。"""
    get_owned_conversation(db, user, conversation_id)
    messages = db.scalars(select(AIMessage).where(
        AIMessage.conversation_id == conversation_id, AIMessage.message_role == "USER"
    ).order_by(AIMessage.id.desc()).limit(100)).all()
    for message in messages:
        if hashlib.sha256(message.content.encode("utf-8")).hexdigest() == pending.question_hash:
            return message.content
    return None


PURCHASE_DRAFT_BRIDGE_KEY = "purchase_draft_bridge"


def _parse_iso_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _sync_pending_version(memory: dict, next_version: int) -> None:
    """会话状态整体递增时，同步澄清状态版本，避免同一 JSON 内互相失效。"""
    if isinstance(memory.get("pending_clarification"), dict):
        try:
            pending = PendingClarification.model_validate(memory["pending_clarification"])
            memory["pending_clarification"] = pending.model_copy(update={"state_version": next_version}).model_dump(mode="json")
        except (TypeError, ValueError):
            memory.pop("pending_clarification", None)


def load_purchase_draft_bridge(
    db: Session, user: User, conversation_id: int, *, now: datetime | None = None,
) -> dict | None:
    """读取本人会话中尚未补齐的采购草稿来源；过期或版本失效按不存在处理。"""

    conversation = get_owned_conversation(db, user, conversation_id)
    state = load_conversation_state(db, conversation)
    if state is None:
        return None
    raw = (state.memory_state or {}).get(PURCHASE_DRAFT_BRIDGE_KEY)
    if not isinstance(raw, dict) or raw.get("contract_version") != "1":
        return None
    if int(raw.get("state_version") or 0) != int(state.state_version or 0):
        return None
    expires_at = _parse_iso_utc(raw.get("expires_at"))
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    if expires_at is None or expires_at <= current_time:
        return None
    if not isinstance(raw.get("source"), dict) or not isinstance(raw.get("requirements"), dict):
        return None
    return raw


def save_purchase_draft_bridge(
    db: Session, user: User, conversation_id: int, bridge: dict, *,
    expected_state_version: int | None = None, now: datetime | None = None, ttl_seconds: int = 600,
) -> dict | None:
    """按会话版本 CAS 保存草稿来源锚点与已收集需求；不覆盖其他业务状态。"""

    if not conversation_state_enabled(db):
        return None
    conversation = get_owned_conversation(db, user, conversation_id)
    state = lock_conversation_state(db, conversation)
    if state is None:
        if expected_state_version is not None:
            raise BusinessValidationError("草稿整理状态已变化，请重新说明")
        state = AIConversationState(conversation_id=conversation.id, thread_id=f"ai:{user.id}:{conversation.id}",
                                    state_version=1, memory_state={})
        db.add(state)
        db.flush()
    else:
        db.refresh(state)
    memory = dict(state.memory_state or {})
    current = memory.get(PURCHASE_DRAFT_BRIDGE_KEY)
    if expected_state_version is not None:
        current_version = int(current.get("state_version") or 0) if isinstance(current, dict) else 0
        if current_version != expected_state_version:
            raise BusinessValidationError("草稿整理状态已变化，请重新说明")
    current_version = int(state.state_version or 0)
    next_version = current_version + 1
    created = now or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    stored = {
        **bridge,
        "contract_version": "1",
        "conversation_id": conversation.id,
        "created_at": created.isoformat(),
        "expires_at": (created + timedelta(seconds=ttl_seconds)).isoformat(),
        "state_version": next_version,
    }
    memory[PURCHASE_DRAFT_BRIDGE_KEY] = json.loads(json.dumps(stored, ensure_ascii=False, default=str))
    _sync_pending_version(memory, next_version)
    _write_state_values(
        db, state, current_version=current_version, next_version=next_version,
        memory=memory, error="草稿整理状态已变化，请重新说明",
        permission_snapshot_value=permission_snapshot(db, user))
    return stored


def clear_purchase_draft_bridge(
    db: Session, user: User, conversation_id: int, *, state_version: int | None = None,
) -> int:
    """成功后清除本次来源锚点；版本不符时保留新状态，不误删其他请求。"""

    if not conversation_state_enabled(db):
        return 0
    conversation = get_owned_conversation(db, user, conversation_id)
    state = lock_conversation_state(db, conversation)
    if state is None:
        return 0
    db.refresh(state)
    memory = dict(state.memory_state or {})
    current = memory.get(PURCHASE_DRAFT_BRIDGE_KEY)
    if not isinstance(current, dict):
        return int(state.state_version or 0)
    if state_version is not None and int(current.get("state_version") or 0) != state_version:
        return int(state.state_version or 0)
    memory.pop(PURCHASE_DRAFT_BRIDGE_KEY, None)
    current_version = int(state.state_version or 0)
    next_version = current_version + 1
    _sync_pending_version(memory, next_version)
    return _write_state_values(
        db, state, current_version=current_version, next_version=next_version,
        memory=memory, error="草稿整理状态已变化，请重新说明")


def save_batch_state(db: Session, user: User, conversation: AIConversation, state: AIConversationState | None, tasks: list[dict]) -> None:
    """保存批量任务上下文，与聊天消息共用调用方事务。"""
    if not conversation_state_enabled(db):
        return
    if state is None:
        state = AIConversationState(conversation_id=conversation.id, thread_id=f"ai:{user.id}:{conversation.id}")
        db.add(state)
    memory = {**(state.memory_state or {}), "batch_tasks": tasks}
    next_version = (state.state_version or 0) + 1
    if isinstance(memory.get("pending_clarification"), dict):
        try:
            pending = PendingClarification.model_validate(memory["pending_clarification"])
            memory["pending_clarification"] = pending.model_copy(update={"state_version": next_version}).model_dump(mode="json")
        except (TypeError, ValueError):
            memory.pop("pending_clarification", None)
    state.memory_state = memory
    state.query_plan = None  # 多计划不能伪装成最后一项单计划。
    state.permission_snapshot = permission_snapshot(db, user)
    state.state_version = next_version
    state.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)


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
