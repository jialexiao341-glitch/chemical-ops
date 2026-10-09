"""Exercise database polling, concurrency limits and retry settlement."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.modules.task_queue import service, worker
from app.modules.task_queue.model import TaskExecution
from tests.test_task_queue_delivery import queue_engine


@pytest.fixture
def tasks(queue_engine):
    factory = sessionmaker(queue_engine, expire_on_commit=False)
    ids = []
    with factory() as db:
        for _ in range(5):
            row = service.enqueue(db, task_type="agent.run", business_id=uuid4().hex,
                actor_id=1, generation=0, payload={})
            ids.append(row.id)
        db.commit()
    yield factory, ids
    with factory() as db:
        db.execute(delete(TaskExecution).where(TaskExecution.id.in_(ids)))
        db.commit()


def test_polling_limits_concurrency_and_does_not_repeat_completed_tasks(tasks, monkeypatch):
    factory, ids = tasks
    active, peak = 0, 0
    completed = []
    async def execute(factory, settings, execution):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.2)
            def finish(db):
                service.finish(db, execution.id, execution.fencing_token, status="SUCCEEDED")
                db.commit()
            await worker.database(factory, finish)
            completed.append(execution.id)
        finally:
            active -= 1
    monkeypatch.setattr(worker, "execute", execute)
    config = Settings(_env_file=None, task_agent_concurrency=2, task_poll_interval_seconds=0.1)
    async def verify():
        running = asyncio.create_task(worker.run(config, factory, "agent"))
        try:
            async with asyncio.timeout(10):
                while len(completed) < len(ids):
                    await asyncio.sleep(0.05)
            await asyncio.sleep(0.2)
        finally:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        assert active == 0 and peak == 2
        assert sorted(completed) == sorted(ids)
    asyncio.run(verify())


def test_once_settles_interruption_as_delayed_retry(tasks, monkeypatch):
    factory, ids = tasks
    async def fail(*_args):
        raise RuntimeError("substitute execution interruption")
    monkeypatch.setattr(worker, "execute", fail)
    asyncio.run(worker.run(Settings(_env_file=None), factory, "agent", once=True))
    with factory() as db:
        rows = list(db.scalars(select(TaskExecution).where(TaskExecution.id.in_(ids))))
        retried = [row for row in rows if row.status == "RETRYING"]
        assert len(retried) == 1
        assert retried[0].attempt_count == 1 and retried[0].next_attempt_at > service.now()
        assert retried[0].error_code == "WORKER_INTERRUPTED"
        assert sum(row.status == "QUEUED" for row in rows) == 4
