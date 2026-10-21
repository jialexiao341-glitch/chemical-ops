"""AI 任务与待确认草稿的保留期限清理。"""

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.core.observability import metrics
from app.modules.ai.model import AIAgentTask, AIPurchaseDraftConfirmation
from app.modules.task_queue.model import TaskExecution, TaskOutbox, TaskResourceLock

TASK_RETENTION_DAYS = 30
TERMINAL_TASK_STATES = ("SUCCEEDED", "FAILED", "CANCELLED")


def cleanup_expired_ai_records(db: Session, *, now=None, limit: int = 500) -> dict[str, int]:
    """过期草稿标记失效，并清除 30 天以上的终态任务及队列载荷。

    运行中的任务不会被清理。所有截止时间都按 UTC naive 协议计算。
    """
    instant = now or utc_now()
    expired = db.execute(
        select(AIPurchaseDraftConfirmation.id).where(
            AIPurchaseDraftConfirmation.status == "PENDING",
            AIPurchaseDraftConfirmation.expires_at <= instant,
        ).limit(limit)
    ).scalars().all()
    if expired:
        db.query(AIPurchaseDraftConfirmation).filter(AIPurchaseDraftConfirmation.id.in_(expired)).update(
            {"status": "EXPIRED"}, synchronize_session="fetch"
        )

    cutoff = instant - timedelta(days=TASK_RETENTION_DAYS)
    task_ids = db.execute(
        select(AIAgentTask.id).where(
            AIAgentTask.status.in_(TERMINAL_TASK_STATES), AIAgentTask.updated_at < cutoff
        ).order_by(AIAgentTask.updated_at, AIAgentTask.id).limit(limit)
    ).scalars().all()
    if task_ids:
        executions = db.execute(select(TaskExecution.id).where(
            TaskExecution.task_type.in_(("agent.run", "agent.chat")),
            TaskExecution.business_id.in_(task_ids),
        )).scalars().all()
        if executions:
            db.execute(delete(TaskResourceLock).where(TaskResourceLock.execution_id.in_(executions)))
            db.execute(delete(TaskOutbox).where(TaskOutbox.execution_id.in_(executions)))
            db.execute(delete(TaskExecution).where(TaskExecution.id.in_(executions)))
        db.execute(delete(AIAgentTask).where(AIAgentTask.id.in_(task_ids)))
    db.commit()
    counts = {"expired_confirmations": len(expired), "purged_tasks": len(task_ids)}
    metrics.increment("ai_expired_confirmations", value=counts["expired_confirmations"])
    metrics.increment("ai_retained_tasks_purged", value=counts["purged_tasks"])
    metrics.increment("ai_record_cleanup", labels={"result": "success"})
    return counts
