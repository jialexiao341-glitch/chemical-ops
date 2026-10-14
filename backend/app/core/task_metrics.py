"""从持久化任务状态采集跨 API/Worker 进程可见的 Prometheus 快照。"""

from sqlalchemy import func, or_, select

from app.core.observability import MetricsRegistry
from app.modules.task_queue.model import TaskExecution
from app.modules.task_queue.service import TASK_ROUTES, now


QUEUES = tuple(sorted(set(TASK_ROUTES.values())))
STATUSES = ("QUEUED", "RETRYING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "WAITING_INPUT")


def refresh_task_queue_metrics(db, registry: MetricsRegistry) -> None:
    """刷新任务积压、状态、重试和失败快照；标签只使用固定队列/状态名。"""

    counts = {(queue, status): 0 for queue in QUEUES for status in STATUSES}
    attempts = {queue: 0 for queue in QUEUES}
    rows = db.execute(select(TaskExecution.task_type, TaskExecution.status,
        func.count(TaskExecution.id), func.coalesce(func.sum(TaskExecution.attempt_count), 0))
        .group_by(TaskExecution.task_type, TaskExecution.status)).all()
    for task_type, status, count, attempt_sum in rows:
        queue = TASK_ROUTES.get(task_type)
        if queue is None:
            continue
        counts[(queue, status)] = int(count)
        attempts[queue] += int(attempt_sum)

    timestamp = now()
    oldest = {queue: None for queue in QUEUES}
    ready_created = db.execute(select(TaskExecution.task_type, func.min(TaskExecution.created_at))
        .where(TaskExecution.status.in_(("QUEUED", "RETRYING")),
            or_(TaskExecution.next_attempt_at.is_(None), TaskExecution.next_attempt_at <= timestamp))
        .group_by(TaskExecution.task_type)).all()
    for task_type, created_at in ready_created:
        queue = TASK_ROUTES.get(task_type)
        if queue is None or created_at is None:
            continue
        if oldest[queue] is None or created_at < oldest[queue]:
            oldest[queue] = created_at

    for queue in QUEUES:
        backlog = counts[(queue, "QUEUED")] + counts[(queue, "RETRYING")]
        registry.set_gauge("task_queue_backlog", backlog, labels={"queue": queue})
        registry.set_gauge("task_queue_oldest_ready_seconds",
            max(0.0, (timestamp - oldest[queue]).total_seconds()) if oldest[queue] else 0.0,
            labels={"queue": queue})
        registry.set_gauge("task_queue_attempts", attempts[queue], labels={"queue": queue})
        for status in STATUSES:
            registry.set_gauge("task_queue_executions", counts[(queue, status)],
                labels={"queue": queue, "status": status.lower()})
