"""未被 Worker 领取的 Agent 任务不能无限停留在运行中。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.modules.ai import agent_runtime
from app.modules.ai.model import AIAgentTask
from app.modules.task_queue.model import TaskExecution


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    AIAgentTask.__table__.create(engine)
    TaskExecution.__table__.create(engine)
    return engine


def _task(engine, *, status="RUNNING", revision=0):
    db = Session(engine, expire_on_commit=False)
    task = AIAgentTask(id="t" * 32, user_id=7, status=status, revision=revision,
                       payload={"messages": ["查库存"], "trace": [], "chat": None},
                       reply="正在查询业务数据…", error_code=None,
                       created_at=_now(), updated_at=_now())
    db.add(task)
    db.commit()
    return db, task


def _execution(db, *, status="QUEUED", age_seconds=300):
    execution = TaskExecution(
        id="e" * 32, task_type="agent.run", business_id="t" * 32, actor_id=7,
        run_generation=1, business_revision=0, payload={}, checkpoint={},
        status=status, attempt_count=0, delivery_generation=0, fencing_token=0,
        created_at=_now(), updated_at=_now() - timedelta(seconds=age_seconds),
    )
    db.add(execution)
    db.commit()
    return execution


def test_unclaimed_queued_task_is_failed_with_actionable_reply():
    engine = _engine()
    db, task = _task(engine)
    execution = _execution(db)

    result = agent_runtime._reap_unclaimed_task(db, task)

    assert result.status == "FAILED"
    assert result.error_code == "WORKER_UNAVAILABLE"
    assert "Worker 未启动" in result.reply
    assert db.get(TaskExecution, execution.id).status == "FAILED"
    db.close()
    engine.dispose()


def test_freshly_queued_or_claimed_task_is_not_reaped():
    engine = _engine()
    db, task = _task(engine)
    fresh = _execution(db, age_seconds=1)
    assert agent_runtime._reap_unclaimed_task(db, task).status == "RUNNING"
    assert db.get(TaskExecution, fresh.id).status == "QUEUED"
    db.close()

    engine2 = _engine()
    db2, task2 = _task(engine2)
    claimed = _execution(db2, status="RUNNING", age_seconds=300)
    assert agent_runtime._reap_unclaimed_task(db2, task2).status == "RUNNING"
    assert db2.get(TaskExecution, claimed.id).status == "RUNNING"
    db2.close()
    engine.dispose()
    engine2.dispose()
