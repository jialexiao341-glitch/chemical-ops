"""Real child process + isolated DB exercise of asynchronous worker supervision."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.modules.task_queue import broker, processes, service, worker
from app.modules.task_queue.model import TaskExecution
from tests.test_task_queue_delivery import queue_engine, db, broker_settings


@pytest.fixture
def sleeping_execution(db, monkeypatch, tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run_task_execution.py").write_text(
        "import sys,time\nsys.stdin.readline()\ntime.sleep(3)\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    execution = service.enqueue(db, task_type="documents.fetch", business_id=uuid4().hex,
        actor_id=1, generation=0, payload={})
    db.commit()
    claimed = service.claim_execution(db, execution.id, 0, "test", 15)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, join_transaction_mode="create_savepoint")
    return claimed, factory


def test_synchronous_child_preserves_amqp_and_lease_heartbeats(db, sleeping_execution):
    execution, factory = sleeping_execution
    config = broker_settings().model_copy(update={"task_heartbeat_seconds": 1, "task_lease_seconds": 15})
    ticks = []
    async def verify():
        async with broker.connection(config) as client:
            channel = await client.channel()
            await broker.topology(channel)
            async def ticker():
                while True:
                    ticks.append(1)
                    await asyncio.sleep(0.05)
            timer = asyncio.create_task(ticker())
            try:
                await worker.execute(factory, config, execution)
                assert not client.is_closed and not channel.is_closed
                await channel.get_queue("chemicalops.documents")
            finally:
                timer.cancel()
                await asyncio.gather(timer, return_exceptions=True)
    asyncio.run(verify())
    db.expire_all()
    row = db.get(TaskExecution, execution.id)
    assert len(ticks) >= 30 and row.heartbeat_at > row.created_at
    assert row.status == "RETRYING"
    assert not processes.process_alive(row.checkpoint["process_pid"])


@pytest.mark.parametrize("failure", ["lost_lease", "database_disconnect"])
def test_supervision_stops_child_when_heartbeat_cannot_be_renewed(db, sleeping_execution, monkeypatch, failure):
    execution, factory = sleeping_execution
    config = Settings(_env_file=None, task_heartbeat_seconds=1, task_lease_seconds=15)
    def heartbeat(*_args):
        if failure == "database_disconnect":
            raise ConnectionError("simulated database connection loss")
        return False
    monkeypatch.setattr(service, "heartbeat", heartbeat)
    with pytest.raises((service.ExecutionLost, ConnectionError)):
        asyncio.run(worker.execute(factory, config, execution))
    db.expire_all()
    row = db.get(TaskExecution, execution.id)
    assert not processes.process_alive(row.checkpoint["process_pid"])


def test_runtime_budget_terminates_running_child(db, sleeping_execution, monkeypatch):
    execution, factory = sleeping_execution
    (worker.ROOT / "scripts/run_task_execution.py").write_text(
        "import sys,time\nsys.stdin.readline()\ntime.sleep(60)\n", encoding="utf-8")
    execution.task_type = "agent.run"
    db.commit()
    config = Settings(_env_file=None, task_heartbeat_seconds=1, task_lease_seconds=15, agent_task_timeout_seconds=1)
    with pytest.raises(TimeoutError):
        asyncio.run(worker.execute(factory, config, execution))
    db.expire_all()
    row = db.get(TaskExecution, execution.id)
    assert not processes.process_alive(row.checkpoint["process_pid"])
