"""Agent 回归用例：从本人任务生成脱敏草稿，管理员审阅后导出为评测用例。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai.capabilities import AGENT_TASK_REQUIREMENTS
from app.modules.ai.error_policy import ErrorClass, classify, failure_stage
from app.modules.ai.model import AIAgentTask, AIFeedback, AIRegressionCase
from app.modules.ai.redaction import redact
from app.modules.ai.schema import (
    RegressionCaseBatchCreate,
    RegressionCaseBatchItem,
    RegressionCaseBatchItemResult,
    RegressionCaseBatchResult,
    RegressionCaseBatchReview,
    RegressionCaseBatchReviewItem,
    RegressionCaseBatchReviewResult,
    RegressionCaseCandidate,
    RegressionCaseCandidatePage,
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


def _draft(task: AIAgentTask) -> RegressionCaseDraft:
    """按任务轨迹推导公开契约；问题文本原样返回，脱敏确认仍由提交人完成。"""
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


def draft_from_task(db: Session, user: User, task_id: str) -> RegressionCaseDraft:
    """只对本人任务生成草稿；问题文本仍需提交人逐字确认脱敏后才能保存。"""
    return _draft(_owned_task(db, user, task_id))


def _infra_failure(error_code: str | None) -> bool:
    """基础设施失败不能作为能力回归候选；差评属于主观信号，另按来源判断。"""
    if not error_code:
        return False
    category, _, _ = classify(str(error_code))
    return category in (ErrorClass.TRANSIENT_INFRA, ErrorClass.AMBIGUOUS_TIMEOUT)


def candidate_drafts(db: Session, user: User, *, days: int = 7,
                     limit: int = 10, include_infra: bool = False
                     ) -> RegressionCaseCandidatePage:
    """从近期差评或失败任务确定性生成草稿；不落库、不调用模型，管理员审阅后才成为用例。

    差评与失败都是可复现信号：差评补充主观原因，失败的 error_code 直接给出失败阶段。
    非管理员只看到本人任务；同一问题已存在用例时仍返回草稿并附可用用例编号，
    由审阅人决定是否跳过或重新提交，避免静默去重掩盖同类问题。
    默认排除 WORKER_UNAVAILABLE 等基础设施失败，避免把服务抖动做成能力回归；
    差评来源不受此过滤影响，管理员可显式 include_infra 审计。
    """
    if not 1 <= days <= 90 or not 1 <= limit <= 50:
        raise BusinessValidationError("天数需为 1-90，条数需为 1-50")
    since = datetime.now() - timedelta(days=days)
    admin = _is_admin(db, user)
    down_reasons: dict[str, str | None] = {}
    for feedback in db.scalars(
        select(AIFeedback)
        .where(AIFeedback.rating == "DOWN", AIFeedback.created_at >= since)
        .order_by(AIFeedback.created_at.desc())
    ).all():
        down_reasons.setdefault(feedback.task_id, feedback.reason_code)

    tasks = list(db.scalars(
        select(AIAgentTask)
        .where(AIAgentTask.created_at >= since)
        .order_by(AIAgentTask.created_at.desc())
        .limit(limit * 10)
    ).all())
    ordered = [task for task in tasks if task.id in down_reasons]
    ordered += [task for task in tasks if task.id not in down_reasons and task.error_code]

    collected: list[tuple[RegressionCaseDraft, str, str | None, AIAgentTask, str]] = []
    seen: set[str] = set()
    for task in ordered:
        if not admin and task.user_id != user.id:
            continue
        source = "feedback" if task.id in down_reasons else "failure"
        if source == "failure" and not include_infra and _infra_failure(task.error_code):
            continue
        draft = _draft(task)
        if not draft.question:
            continue
        key = _case_key(draft.question, draft.expected_execution_mode, draft.expected_tasks)
        if key in seen:
            continue
        seen.add(key)
        collected.append((draft, key, down_reasons.get(task.id), task, source))
        if len(collected) >= limit:
            break

    existing_by_key: dict[str, AIRegressionCase] = {}
    existing_by_source: dict[str, AIRegressionCase] = {}
    case_keys = {key for _, key, _, _, _ in collected}
    source_ids = {task.id for _, _, _, task, _ in collected}
    if case_keys or source_ids:
        rows = db.scalars(select(AIRegressionCase).where(or_(
            AIRegressionCase.case_key.in_(case_keys),
            AIRegressionCase.source_task_id.in_(source_ids)))).all()
        for row in rows:
            existing_by_key.setdefault(row.case_key, row)
            if row.source_task_id:
                existing_by_source.setdefault(row.source_task_id, row)
    items = []
    for draft, key, reason_code, task, source in collected:
        # 脱敏改写会改变 case_key；同一来源任务仍需看到已入库用例，避免重复提交。
        case = existing_by_key.get(key) or existing_by_source.get(task.id)
        visible = case is not None and (admin or case.created_by == user.id)
        error_code = getattr(task, "error_code", None)
        preview = redact(draft.question)
        items.append(RegressionCaseCandidate(
            **draft.model_dump(),
            case_key=key,
            source=source,
            task_status=str(getattr(task, "status", "") or ""),
            error_code=error_code,
            failure_stage=failure_stage(error_code) if error_code else None,
            feedback_reason_code=reason_code,
            existing_case_id=case.id if visible else None,
            redacted_question=preview.text,
            redaction_findings=preview.findings,
        ))
    return RegressionCaseCandidatePage(days=days, total=len(items), items=items)


def options() -> RegressionCaseOptions:
    return RegressionCaseOptions(
        modes=list(MODE_LABELS),
        tasks=[RegressionTaskOption(key=key, label=label) for key, label in TASK_LABELS.items()],
    )


def create_case(db: Session, user: User, data: RegressionCaseCreate) -> RegressionCaseRead:
    if not data.redacted_confirmed:
        raise BusinessValidationError("请确认问题文本已脱敏后再提交回归用例")
    # 客户端可能漏改：保存前统一做确定性脱敏，评测集里不出现联系方式与证件号。
    question = redact(data.question).text.strip()
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
        note=(redact(data.note).text.strip()
              if isinstance(data.note, str) and data.note.strip() else None),
        status="DRAFT",
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return _read(case)


def create_cases_batch(
        db: Session, user: User, data: RegressionCaseBatchCreate) -> RegressionCaseBatchResult:
    """一次确认批量创建：逐条服务端脱敏、校验归属与任务类别，重复项跳过而不中断整批。

    与单条提交共用同一脱敏与去重口径：保存的是脱敏后文本；批内重复、已存在草稿、
    已审阅用例、来源任务已有用例分别归入 SKIPPED/REUSED，单项失败不影响其余项。
    """
    if not data.redacted_confirmed:
        raise BusinessValidationError("请确认问题文本已脱敏后再提交回归用例")
    admin = _is_admin(db, user)
    results: list[RegressionCaseBatchItemResult | None] = [None] * len(data.items)
    pending: list[tuple[int, RegressionCaseBatchItem, str, list[str], list[str],
                         AIAgentTask | None, str, dict[str, int]]] = []
    pending_keys: set[str] = set()
    pending_sources: set[str] = set()

    def failed(index: int, item: RegressionCaseBatchItem, question: str,
               findings: dict[str, int], reason: str) -> None:
        results[index] = RegressionCaseBatchItemResult(
            source_task_id=item.source_task_id, status="FAILED", reason=reason,
            question=question, redaction_findings=findings)

    for index, item in enumerate(data.items):
        preview = redact(item.question)
        question = preview.text.strip()
        findings = preview.findings
        if len(question) < 5:
            failed(index, item, question, findings, "脱敏后问题不足 5 个字符")
            continue
        try:
            expected = _norm_tasks(item.expected_tasks)
            forbidden = _norm_tasks(item.forbidden_tasks)
            if set(expected) & set(forbidden):
                raise BusinessValidationError("同一任务不能同时作为必选和禁止项")
        except BusinessValidationError as exc:
            failed(index, item, question, findings, str(exc))
            continue

        task = None
        if item.source_task_id:
            task = (db.get(AIAgentTask, item.source_task_id) if admin
                    else db.scalar(select(AIAgentTask).where(
                        AIAgentTask.id == item.source_task_id,
                        AIAgentTask.user_id == user.id)))
            if task is None:
                failed(index, item, question, findings, "Agent 任务不存在")
                continue
        elif not admin:
            failed(index, item, question, findings, "从任务详情提交回归用例时需要关联任务")
            continue

        key = _case_key(question, item.expected_execution_mode, expected)
        existing = db.scalar(select(AIRegressionCase).where(AIRegressionCase.case_key == key))
        if existing is not None:
            reusable = existing.status == "DRAFT" and (existing.created_by == user.id or admin)
            results[index] = RegressionCaseBatchItemResult(
                source_task_id=item.source_task_id, case_key=key, case_id=existing.id,
                status="REUSED" if reusable else "SKIPPED",
                reason=None if reusable else "该回归用例已存在且进入审阅状态",
                question=question, redaction_findings=findings)
            continue
        if task is not None:
            source_case = db.scalar(select(AIRegressionCase).where(
                AIRegressionCase.source_task_id == task.id).limit(1))
            if source_case is not None:
                results[index] = RegressionCaseBatchItemResult(
                    source_task_id=item.source_task_id, case_key=key,
                    case_id=source_case.id, status="SKIPPED",
                    reason="该来源任务已有回归用例", question=question,
                    redaction_findings=findings)
                continue
        # 批内去重只看“本次会新建”的项：前一项已因既有用例被跳过时，
        # 后一项仍应报出真实原因（既有用例），而不是笼统的“批内重复”。
        if key in pending_keys or (task is not None and task.id in pending_sources):
            results[index] = RegressionCaseBatchItemResult(
                source_task_id=item.source_task_id, case_key=key, status="SKIPPED",
                reason="本批次内重复", question=question,
                redaction_findings=findings)
            continue
        pending_keys.add(key)
        if task is not None:
            pending_sources.add(task.id)
        pending.append((index, item, question, expected, forbidden, task, key, findings))

    created = 0
    for index, item, question, expected, forbidden, task, key, findings in pending:
        now = datetime.now()
        case = AIRegressionCase(
            case_key=key,
            source_task_id=task.id if task is not None else None,
            source_task_hash=_task_hash(task.id) if task is not None else None,
            source_prompt_version=_source_prompt_version(task) if task is not None else None,
            question=question,
            expected_execution_mode=item.expected_execution_mode,
            expected_tasks=expected,
            forbidden_tasks=forbidden,
            note=(redact(item.note).text.strip()
                  if isinstance(item.note, str) and item.note.strip() else None),
            status="DRAFT",
            created_by=user.id,
            created_at=now,
            updated_at=now,
        )
        try:
            with db.begin_nested():
                db.add(case)
                db.flush()
        except IntegrityError:
            # 并发提交同一用例：先查回既有行，不让整批回滚。
            existing = db.scalar(select(AIRegressionCase).where(AIRegressionCase.case_key == key))
            reusable = (existing is not None and existing.status == "DRAFT"
                        and (existing.created_by == user.id or admin))
            results[index] = RegressionCaseBatchItemResult(
                source_task_id=item.source_task_id, case_key=key,
                case_id=existing.id if existing is not None else None,
                status="REUSED" if reusable else "SKIPPED",
                reason=None if reusable else "该回归用例已存在且进入审阅状态",
                question=question, redaction_findings=findings)
            continue
        created += 1
        results[index] = RegressionCaseBatchItemResult(
            source_task_id=item.source_task_id, case_key=key, case_id=case.id,
            status="CREATED", question=question, redaction_findings=findings)
    if created:
        db.commit()

    rows = [row for row in results if row is not None]
    return RegressionCaseBatchResult(
        items=rows,
        created=sum(1 for row in rows if row.status == "CREATED"),
        reused=sum(1 for row in rows if row.status == "REUSED"),
        skipped=sum(1 for row in rows if row.status == "SKIPPED"),
        failed=sum(1 for row in rows if row.status == "FAILED"),
        total=len(rows),
    )


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


def review_cases_batch(
        db: Session, user: User, data: RegressionCaseBatchReview
) -> RegressionCaseBatchReviewResult:
    """管理员一次批准/归档多条；不存在、状态不允许或重复编号逐条给出原因。

    与单条审阅共用同一状态迁移规则（仅 DRAFT 可批准、DRAFT/APPROVED 可归档），
    但批量模式不因一条失败回滚其余项，便于把一批候选推进到评测集。
    """
    if not _is_admin(db, user):
        raise AuthorizationError("仅管理员可审阅回归用例")
    now = datetime.now()
    seen: set[int] = set()
    items: list[RegressionCaseBatchReviewItem] = []
    updated = 0
    for case_id in data.case_ids:
        case = db.get(AIRegressionCase, case_id)
        if case is None:
            items.append(RegressionCaseBatchReviewItem(
                case_id=case_id, result="FAILED", reason="回归用例不存在"))
            continue
        if case_id in seen:
            items.append(RegressionCaseBatchReviewItem(
                case_id=case_id, case_key=case.case_key, result="SKIPPED",
                case_status=case.status, reason="重复编号"))
            continue
        seen.add(case_id)
        if data.action == "APPROVE":
            if case.status != "DRAFT":
                items.append(RegressionCaseBatchReviewItem(
                    case_id=case_id, case_key=case.case_key, result="SKIPPED",
                    case_status=case.status, reason="仅草稿可批准"))
                continue
            case.status = "APPROVED"
        else:
            if case.status not in ("DRAFT", "APPROVED"):
                items.append(RegressionCaseBatchReviewItem(
                    case_id=case_id, case_key=case.case_key, result="SKIPPED",
                    case_status=case.status, reason="当前状态不可归档"))
                continue
            case.status = "ARCHIVED"
        case.reviewed_by = user.id
        case.reviewed_at = now
        case.updated_at = now
        updated += 1
        items.append(RegressionCaseBatchReviewItem(
            case_id=case_id, case_key=case.case_key, result="UPDATED",
            case_status=case.status))
    if updated:
        db.commit()
    return RegressionCaseBatchReviewResult(
        items=items,
        updated=sum(1 for row in items if row.result == "UPDATED"),
        skipped=sum(1 for row in items if row.result == "SKIPPED"),
        failed=sum(1 for row in items if row.result == "FAILED"),
        total=len(items),
    )
