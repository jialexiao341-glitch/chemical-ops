"""任务进展监控：只使用队列与检查点的确定性信号。

心跳正常只说明进程还在；这里额外观察最后一次实质进展（检查点更新时间）、
决策次数、失败次数和 token 预算，输出可解释的诊断，不自动取消任务。
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.observability import metrics
from app.modules.task_queue import service
from app.modules.task_queue.model import TaskExecution


LOGGER = logging.getLogger("chemicalops.task_progress")
ACTIVE_STATUSES = ("QUEUED", "RETRYING", "RUNNING")
WATCHED_LIMIT = 200


@dataclass(frozen=True)
class ProgressDiagnosis:
    """单条执行的可解释诊断；只陈述观测到的事实。"""

    execution_id: str
    task_type: str
    business_id: str
    status: str
    verdict: str
    recommendation: str
    reasons: tuple[str, ...]
    queued_seconds: int | None = None
    running_seconds: int | None = None
    heartbeat_age_seconds: int | None = None
    last_progress_seconds: int | None = None
    decisions: int | None = None
    failures: int | None = None
    attempt_count: int = 0
    token_used: int | None = None
    token_limit: int | None = None
    llm_seconds: float | None = None
    tool_seconds: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _seconds(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, int((now - value).total_seconds()))


def _checkpoint_int(checkpoint: dict, key: str) -> int | None:
    value = checkpoint.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _token_usage(checkpoint: dict) -> tuple[int | None, int | None]:
    budget = checkpoint.get("token_budget")
    if not isinstance(budget, dict):
        return None, None
    used = budget.get("used_tokens")
    limit = budget.get("limit")
    used = used if isinstance(used, int) and not isinstance(used, bool) and used >= 0 else None
    limit = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else None
    return used, limit


def _timing(checkpoint: dict, key: str) -> float | None:
    timings = checkpoint.get("timings")
    if not isinstance(timings, dict):
        return None
    value = timings.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return round(float(value), 3)
    return None


def diagnose(execution: TaskExecution, *, now: datetime, settings: Settings) -> ProgressDiagnosis:
    """按固定优先级给出诊断：卡住 > 错误循环 > 预算风险 > 过慢 > 排队过久 > 正常。"""
    checkpoint = execution.checkpoint or {}
    if execution.started_at is not None:
        queued = _seconds(execution.created_at, execution.started_at)
    elif execution.status != "RUNNING":
        queued = _seconds(execution.created_at, now)
    else:
        queued = None
    running = _seconds(execution.started_at, now) if execution.status == "RUNNING" else None
    heartbeat_age = _seconds(execution.heartbeat_at, now) if execution.status == "RUNNING" else None
    progress_age = _seconds(execution.updated_at, now) if execution.status == "RUNNING" else None
    decisions = _checkpoint_int(checkpoint, "decisions")
    failures = _checkpoint_int(checkpoint, "failures")
    token_used, token_limit = _token_usage(checkpoint)
    llm_seconds = _timing(checkpoint, "llm_seconds")
    tool_seconds = _timing(checkpoint, "tool_seconds")
    reasons: list[str] = []
    verdict, recommendation = "OK", "WAIT"

    if execution.status in {"QUEUED", "RETRYING"}:
        if queued is not None and queued >= settings.task_progress_wait_warn_seconds:
            verdict, recommendation = "WAITING_TOO_LONG", "NOTIFY_OPERATOR"
            reasons.append(f"排队等待 {queued} 秒，超过阈值 {settings.task_progress_wait_warn_seconds} 秒")
        else:
            reasons.append(f"排队等待 {queued} 秒，尚未开始执行")
    elif execution.status == "RUNNING":
        document_task = execution.task_type.startswith("documents.")
        stall_threshold = (settings.task_progress_document_stall_seconds if document_task
                           else settings.task_progress_stall_seconds)
        if progress_age is not None and progress_age >= stall_threshold:
            recommendation = "CANCEL" if progress_age >= stall_threshold * 3 else "MANUAL_REVIEW"
            verdict = "STALLED"
            reasons.append(f"心跳后 {progress_age} 秒没有新的检查点更新，超过阈值 {stall_threshold} 秒")
            if recommendation == "CANCEL":
                reasons.append("长时间无实质进展，建议人工取消后重试；本扫描不会自动取消")
            if heartbeat_age is not None:
                reasons.append(f"最近心跳 {heartbeat_age} 秒前，进程仍存活")
        elif failures is not None and failures >= 2:
            verdict, recommendation = "ERROR_LOOP", "MANUAL_REVIEW"
            reasons.append(f"本轮已累计 {failures} 次工具失败")
        elif token_limit is not None and token_used is not None and token_used >= token_limit * 0.9:
            verdict, recommendation = "BUDGET_RISK", "NOTIFY_USER"
            reasons.append(f"token 已使用 {token_used}/{token_limit}，接近任务预算上限")
        elif not document_task and running is not None and running >= settings.agent_task_timeout_seconds * 0.8:
            verdict, recommendation = "SLOW", "WAIT"
            reasons.append(f"已运行 {running} 秒，接近超时预算 {settings.agent_task_timeout_seconds} 秒")
        else:
            reasons.append("最近检查点仍在更新，未发现异常信号")
    else:
        reasons.append("非活动状态，不纳入进展诊断")

    return ProgressDiagnosis(
        execution_id=execution.id,
        task_type=execution.task_type,
        business_id=execution.business_id,
        status=execution.status,
        verdict=verdict,
        recommendation=recommendation,
        reasons=tuple(reasons),
        queued_seconds=queued,
        running_seconds=running,
        heartbeat_age_seconds=heartbeat_age,
        last_progress_seconds=progress_age,
        decisions=decisions,
        failures=failures,
        attempt_count=execution.attempt_count or 0,
        token_used=token_used,
        token_limit=token_limit,
        llm_seconds=llm_seconds,
        tool_seconds=tool_seconds,
    )


def scan_progress(db: Session, *, now: datetime | None = None,
                  settings: Settings | None = None) -> list[ProgressDiagnosis]:
    """读取当前活动执行并逐条诊断；不做任何状态变更。"""
    runtime = settings or get_settings()
    timestamp = now or service.now()
    rows = list(db.scalars(
        select(TaskExecution)
        .where(TaskExecution.status.in_(ACTIVE_STATUSES))
        .order_by(TaskExecution.created_at, TaskExecution.id)
        .limit(WATCHED_LIMIT)
    ).all())
    return [diagnose(row, now=timestamp, settings=runtime) for row in rows]


_last_attention: dict[str, str] = {}


def run_progress_scan() -> list[ProgressDiagnosis]:
    """定时扫描入口：只记录指标与日志，取消/恢复仍走既有任务控制路径。"""
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        diagnoses = scan_progress(db)
    seen: set[str] = set()
    for item in diagnoses:
        seen.add(item.execution_id)
        metrics.increment("task_progress_diagnosis", labels={"verdict": item.verdict.lower()})
        previous = _last_attention.get(item.execution_id)
        _last_attention[item.execution_id] = item.verdict
        # 同一执行同一诊断只告警一次，避免每个扫描周期重复刷日志。
        if item.verdict != "OK" and previous != item.verdict:
            LOGGER.warning("task_progress_attention execution_id=%s task_type=%s verdict=%s reasons=%s",
                           item.execution_id, item.task_type, item.verdict, "; ".join(item.reasons))
    for execution_id in set(_last_attention) - seen:
        _last_attention.pop(execution_id, None)
    return diagnoses