"""Agent 任务反馈：只保存公开运行元数据，并按版本聚合。"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.ai_agent.model import AIAgentTask, AIFeedback
from app.modules.ai_agent.schema import AIFeedbackAdminSummary, AIFeedbackCreate, AIFeedbackRead, AIFeedbackSummary
from app.modules.system_management.model import User


def _read(feedback: AIFeedback) -> AIFeedbackRead:
    return AIFeedbackRead(
        task_id=feedback.task_id,
        rating=feedback.rating,
        reason_code=feedback.reason_code,
        comment=feedback.comment,
        correction=feedback.correction,
        prompt_version=feedback.prompt_version,
        prompt_versions=feedback.prompt_versions or {},
        model_name=feedback.model_name,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


def _owned_task(db: Session, user: User, task_id: str) -> AIAgentTask:
    """反馈只能落在本人任务上；不通过任务读取接口二次重验资源范围。"""
    task = db.scalar(select(AIAgentTask).where(
        AIAgentTask.id == task_id, AIAgentTask.user_id == user.id))
    if task is None:
        raise ResourceNotFoundError("Agent 任务不存在")
    return task


def submit_feedback(db: Session, user: User, data: AIFeedbackCreate) -> AIFeedbackRead:
    """新增或覆盖本人对同一任务的反馈；版本快照取自服务端 run_meta。"""
    if data.rating == "DOWN" and not data.reason_code:
        raise BusinessValidationError("差评需选择原因")
    task = _owned_task(db, user, data.task_id)
    meta = (task.payload or {}).get("run_meta") or {}
    versions = meta.get("prompt_versions") or {}
    now = datetime.now()
    feedback = db.scalar(select(AIFeedback).where(
        AIFeedback.user_id == user.id, AIFeedback.task_id == data.task_id))
    if feedback is None:
        feedback = AIFeedback(user_id=user.id, task_id=data.task_id, created_at=now, updated_at=now)
        db.add(feedback)
    feedback.rating = data.rating
    feedback.reason_code = data.reason_code
    feedback.comment = data.comment
    feedback.correction = data.correction
    feedback.prompt_versions = versions or None
    feedback.prompt_version = versions.get("planner") or versions.get("routing")
    feedback.model_name = (meta.get("model") or {}).get("name")
    feedback.updated_at = now
    db.commit()
    db.refresh(feedback)
    return _read(feedback)


def get_feedback(db: Session, user: User, task_id: str) -> AIFeedbackRead | None:
    """读取本人任务反馈；无反馈时仍先校验任务归属。"""
    _owned_task(db, user, task_id)
    feedback = db.scalar(select(AIFeedback).where(
        AIFeedback.user_id == user.id, AIFeedback.task_id == task_id))
    return _read(feedback) if feedback is not None else None


def summary(db: Session, user: User, *, days: int = 7) -> AIFeedbackSummary:
    """按时间窗口聚合本人反馈；只统计评分、原因码和 prompt 版本，不输出原文。"""
    since = datetime.now() - timedelta(days=days)
    rows = db.execute(select(
        AIFeedback.rating, AIFeedback.reason_code, AIFeedback.prompt_version
    ).where(AIFeedback.user_id == user.id, AIFeedback.created_at >= since)).all()
    by_reason: dict[str, int] = {}
    by_prompt_version: dict[str, int] = {}
    up = 0
    for row in rows:
        if row.rating == "UP":
            up += 1
        reason = row.reason_code or "UNSPECIFIED"
        by_reason[reason] = by_reason.get(reason, 0) + 1
        version = row.prompt_version or "unknown"
        by_prompt_version[version] = by_prompt_version.get(version, 0) + 1
    total = len(rows)
    return AIFeedbackSummary(days=days, total=total, up=up, down=total - up,
                             by_reason=by_reason, by_prompt_version=by_prompt_version)


def summary_all(db: Session, *, days: int = 7) -> AIFeedbackAdminSummary:
    """跨用户聚合；只输出计数与版本分组，不读取评论、纠错或用户身份。"""
    since = datetime.now() - timedelta(days=days)
    rows = db.execute(select(
        AIFeedback.rating, AIFeedback.reason_code, AIFeedback.prompt_version,
        AIFeedback.model_name, AIFeedback.user_id,
    ).where(AIFeedback.created_at >= since)).all()
    by_reason: dict[str, int] = {}
    by_prompt_version: dict[str, int] = {}
    by_model: dict[str, int] = {}
    users: set[int] = set()
    up = 0
    for row in rows:
        users.add(row.user_id)
        if row.rating == "UP":
            up += 1
        reason = row.reason_code or "UNSPECIFIED"
        by_reason[reason] = by_reason.get(reason, 0) + 1
        version = row.prompt_version or "unknown"
        by_prompt_version[version] = by_prompt_version.get(version, 0) + 1
        model = row.model_name or "unknown"
        by_model[model] = by_model.get(model, 0) + 1
    total = len(rows)
    return AIFeedbackAdminSummary(
        days=days, total=total, up=up, down=total - up, users=len(users),
        by_reason=by_reason, by_prompt_version=by_prompt_version, by_model=by_model)