"""Agent 回归用例：从本人任务生成脱敏草稿，管理员审阅后导出为评测用例。"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai.capabilities import AGENT_TASK_REQUIREMENTS
from app.modules.ai.model import AIAgentTask, AIRegressionCase
from app.modules.ai.schema import (
    RegressionCaseCreate,
    RegressionCaseDraft,
    RegressionCaseOptions,
    RegressionCasePage,
    RegressionCaseRead,
    RegressionTaskOption,
)
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import User

MODE_LABELS = {
    "agent": "Agent 只读任务",
    "batch": "多意图批次",
    "query": "统计查询",
    "document": "文档问答",
    "none": "不执行",
}
TASK_LABELS = {
    "inventory": "库存",
    "quotes": "报价",
    "purchase_request": "采购申请",
    "order_trace": "订单追溯",
    "analytics": "统计",
    "document": "文档",
    "order_search": "订单检索",
    "exception_search": "异常检索",
    "quality_acceptance": "质量验收",
    "delivery": "到货",
    "finance_reconciliation": "对账",
    "supplier": "供应商",
    "supplier_profile": "供应商画像",
    "replenishment_plan": "补货计划",
}
_STATUSES = ("DRAFT", "APPROVED", "ARCHIVED")


def _is_admin(db: Session, user: User) -> bool:
    return "SYS_ADMIN" in set(get_user_role_codes(db, user.id))


def _norm_tasks(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        key = str(value).strip()
        if key not in TASK_LABELS:
            raise BusinessValidationError(f"未登记的回归任务：{key}")
        if key not in cleaned:
            cleaned.append(key)
    return sorted(cleaned)


def _case_key(question: str, mode: str, tasks: list[str]) -> str:
    digest = hashlib.sha256(
        f"{question.strip()}|{mode}|{','.join(sorted(tasks))}".encode("utf-8")
    ).hexdigest()[:8]
    return f"PR-{digest}"


def _task_hash(task_id: str) -> str:
    return hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]


def _read(case: AIRegressionCase) -> RegressionCaseRead:
    return RegressionCaseRead(
        id=case.id,
        case_key=case.case_key,
        source_task_id=case.source_task_id,
        source_task_hash=case.source_task_hash,
        source_prompt_version=case.source_prompt_version,
        question=case.question,
        expected_execution_mode=case.expected_execution_mode,
        expected_tasks=case.expected_tasks or [],
        forbidden_tasks=case.forbidden_tasks or [],
        note=case.note,
        status=case.status,
        created_by=case.created_by,
        reviewed_by=case.reviewed_by,
        created_at=case.created_at,
        reviewed_at=case.reviewed_at,
    )


def _owned_task(db: Session, user: User, task_id: str) -> AIAgentTask:
    task = db.scalar(select(AIAgentTask).where(
        AIAgentTask.id == task_id, AIAgentTask.user_id == user.id))
    if task is None:
        raise ResourceNotFoundError("Agent 任务不存在")
    return task


def _source_prompt_version(task: AIAgentTask) -> str | None:
    meta = (task.payload or {}).get("run_meta") or {}
    versions = meta.get("prompt_versions") or {}
    if not isinstance(versions, dict):
        return None
    return versions.get("planner") or versions.get("routing")


def draft_from_task(db: Session, user: User, task_id: str) -> RegressionCaseDraft:
    """只对本人任务生成草稿；问题文本仍需提交人逐字确认脱敏后才能保存。"""
    task = _owned_task(db, user, task_id)
    messages = (task.payload or {}).get("messages") or []
    question = str(messages[-1]).strip() if messages else ""
    called = {
        str(entry.get("tool"))
        for entry in (task.payload or {}).get("trace") or []
        if isinstance(entry, dict) and entry.get("action") == "call_tool"
    }
    expected = sorted(
        name for name, required in AGENT_TASK_REQUIREMENTS.items() if required <= called)
    return RegressionCaseDraft(
        source_task_id=task.id,
        source_task_hash=_task_hash(task.id),
        source_prompt_version=_source_prompt_version(task),
        question=question,
        expected_execution_mode="agent",
        expected_tasks=expected,
        forbidden_tasks=[],
    )


def options() -> RegressionCaseOptions:
    return RegressionCaseOptions(
        modes=list(MODE_LABELS),
        tasks=[RegressionTaskOption(key=key, label=label) for key, label in TASK_LABELS.items()],
    )


def create_case(db: Session, user: User, data: RegressionCaseCreate) -> RegressionCaseRead:
    if not data.redacted_confirmed:
        raise BusinessValidationError("请确认问题文本已脱敏后再提交回归用例")
    question = data.question.strip()
    if not question:
        raise BusinessValidationError("回归用例问题不能为空")
    expected = _norm_tasks(data.expected_tasks)
    forbidden = _norm_tasks(data.forbidden_tasks)
    if set(expected) & set(forbidden):
        raise BusinessValidationError("同一任务不能同时作为必选和禁止项")

    admin = _is_admin(db, user)
    task = None
    if data.source_task_id:
        task = _owned_task(db, user, data.source_task_id) if not admin else db.get(
            AIAgentTask, data.source_task_id)
        if task is None:
            raise ResourceNotFoundError("Agent 任务不存在")
    elif not admin:
        raise BusinessValidationError("从任务详情提交回归用例时需要关联任务")

    key = _case_key(question, data.expected_execution_mode, expected)
    existing = db.scalar(select(AIRegressionCase).where(AIRegressionCase.case_key == key))
    if existing is not None:
        if existing.status == "DRAFT" and (existing.created_by == user.id or admin):
            return _read(existing)
        raise BusinessValidationError("该回归用例已存在且进入审阅状态")

    now = datetime.now()
    case = AIRegressionCase(
        case_key=key,
        source_task_id=task.id if task is not None else None,
        source_task_hash=_task_hash(task.id) if task is not None else None,
        source_prompt_version=_source_prompt_version(task) if task is not None else None,
        question=question,
        expected_execution_mode=data.expected_execution_mode,
        expected_tasks=expected,
        forbidden_tasks=forbidden,
        note=data.note.strip() if isinstance(data.note, str) and data.note.strip() else None,
        status="DRAFT",
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return _read(case)


def list_cases(db: Session, user: User, *, status: str | None = None,
               page: int = 1, page_size: int = 20) -> RegressionCasePage:
    if status is not None and status not in _STATUSES:
        raise BusinessValidationError("无效的回归用例状态")
    conditions = []
    if not _is_admin(db, user):
        conditions.append(AIRegressionCase.created_by == user.id)
    if status:
        conditions.append(AIRegressionCase.status == status)
    base = select(AIRegressionCase)
    if conditions:
        base = base.where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(AIRegressionCase.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return RegressionCasePage(
        items=[_read(row) for row in rows], total=total, page=page, page_size=page_size)


def review_case(db: Session, user: User, case_id: int, action: str) -> RegressionCaseRead:
    if not _is_admin(db, user):
        raise AuthorizationError("仅管理员可审阅回归用例")
    case = db.get(AIRegressionCase, case_id)
    if case is None:
        raise ResourceNotFoundError("回归用例不存在")
    if action == "APPROVE":
        if case.status != "DRAFT":
            raise BusinessValidationError("仅草稿可批准")
        case.status = "APPROVED"
    elif action == "ARCHIVE":
        if case.status not in ("DRAFT", "APPROVED"):
            raise BusinessValidationError("当前状态不可归档")
        case.status = "ARCHIVED"
    else:
        raise BusinessValidationError("无效的审阅动作")
    case.reviewed_by = user.id
    case.reviewed_at = datetime.now()
    case.updated_at = datetime.now()
    db.commit()
    db.refresh(case)
    return _read(case)
