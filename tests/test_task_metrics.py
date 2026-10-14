"""任务队列 Prometheus 快照以真实持久化状态为来源。"""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.observability import MetricsRegistry
from app.core.task_metrics import refresh_task_queue_metrics
from app.modules.task_queue.model import TaskExecution
from app.modules.task_queue.service import now


def _execution(task_type, status, *, created_at, attempt_count=0, next_attempt_at=None):
    return TaskExecution(id=uuid4().hex, task_type=task_type, business_id=uuid4().hex,
        actor_id=1, run_generation=0, business_revision=0, payload={}, checkpoint={},
        status=status, attempt_count=attempt_count, delivery_generation=0, fencing_token=0,
        next_attempt_at=next_attempt_at, created_at=created_at, updated_at=created_at)


def test_queue_metrics_report_persisted_backlog_and_due_age():
    engine = create_engine("sqlite://")
    TaskExecution.__table__.create(engine)
    timestamp = now()
    with Session(engine) as db:
        db.add_all([
            _execution("agent.run", "QUEUED", created_at=timestamp - timedelta(seconds=12)),
            _execution("agent.run", "RETRYING", created_at=timestamp - timedelta(seconds=30),
                attempt_count=2, next_attempt_at=timestamp + timedelta(seconds=60)),
            _execution("documents.fetch", "FAILED", created_at=timestamp - timedelta(seconds=5),
                attempt_count=3),
        ])
        db.commit()
        registry = MetricsRegistry()

        refresh_task_queue_metrics(db, registry)
        rendered = registry.render_prometheus()

    assert 'chemicalops_task_queue_backlog{queue="agent"} 2.000000' in rendered
    assert 'chemicalops_task_queue_oldest_ready_seconds{queue="agent"} 12.' in rendered
    assert 'chemicalops_task_queue_executions{queue="documents",status="failed"} 1.000000' in rendered
    assert 'chemicalops_task_queue_attempts{queue="documents"} 3.000000' in rendered
    assert 'chemicalops_task_queue_backlog{queue="documents"} 0.000000' in rendered
    engine.dispose()
