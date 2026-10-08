"""Real isolated MySQL tests; never create queue tables in the business database."""

from datetime import timedelta
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.task_queue.model import TaskExecution, TaskOutbox, TaskResourceLock
from app.modules.task_queue import service
from app.modules.task_queue import broker, dispatcher, worker
from app.core.config import Settings
from app.modules.jobs.model import SchedulerJobRun
from app.modules.jobs.service import start_scheduled_run
from app.modules.doc_kb.model import AiDocument, AiDocumentSection

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def queue_engine():
    config = dotenv_values(ROOT / ".env")
    if not config.get("MYSQL_ROOT_PASSWORD"):
        pytest.skip("Isolated MySQL acceptance credentials unavailable")
    engine = create_engine(URL.create("mysql+pymysql", username="root",
        password=config["MYSQL_ROOT_PASSWORD"], host=config.get("MYSQL_HOST", "127.0.0.1"),
        port=int(config.get("MYSQL_PORT", "3306")), database="chemicalops_mq_acceptance_20261008"))
    migration = (ROOT / "database/migrations/041_async_task_dispatch.sql").read_text()
    with engine.begin() as connection:
        for _ in range(2):
            for statement in migration.split(";"):
                if statement.strip():
                    connection.execute(text(statement))
    SchedulerJobRun.__table__.create(engine, checkfirst=True)
    AiDocument.__table__.create(engine, checkfirst=True)
    AiDocumentSection.__table__.create(engine, checkfirst=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db(queue_engine):
    with queue_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


def enqueue(db, **extra):
    return service.enqueue(db, task_type="agent.run", business_id=uuid4().hex,
                           actor_id=1, generation=0, payload={}, **extra)


def test_acceptance_rolls_back_all_intent(db):
    execution = enqueue(db)
    execution_id = execution.id
    db.rollback()
    assert db.get(TaskExecution, execution_id) is None
    assert db.scalar(select(TaskOutbox).where(TaskOutbox.execution_id == execution_id)) is None


def test_business_record_and_outbox_share_one_transaction(db):
    run_id = uuid4().hex
    run = start_scheduled_run(db, run_id, task_name="technical_documents_pipeline", commit=False)
    execution = service.enqueue(db, task_type="documents.fetch", business_id=run_id,
        actor_id=1, generation=0, payload={"cas_no": "64-17-5", "doc_types": ["msds"]})
    execution_id = execution.id
    db.rollback()
    assert db.scalar(select(SchedulerJobRun).where(SchedulerJobRun.run_id == run_id)) is None
    assert db.get(TaskExecution, execution_id) is None
    assert db.scalar(select(TaskOutbox).where(TaskOutbox.execution_id == execution_id)) is None


def test_committed_intent_survives_without_broker(db):
    execution = enqueue(db)
    db.commit()
    row = db.scalar(select(TaskOutbox).where(TaskOutbox.execution_id == execution.id))
    assert row.status == "PENDING" and execution.status == "QUEUED"


def test_resource_uniqueness_blocks_a_second_active_task(db):
    resource = uuid4().hex
    enqueue(db, resource_key=resource)
    with pytest.raises(IntegrityError):
        enqueue(db, resource_key=resource)
    db.rollback()


def test_delivery_retry_does_not_increment_execution_attempts(db):
    execution = enqueue(db)
    row = service.claim_delivery(db, "publisher")
    assert row is not None
    service.settle_delivery(db, row.id, "publisher", confirmed=False)
    db.refresh(execution)
    assert execution.attempt_count == 0
    assert db.get(TaskOutbox, row.id, populate_existing=True).status == "PENDING"


def test_claim_blocks_duplicate_and_completed_delivery(db):
    execution = enqueue(db)
    claimed = service.claim_execution(db, execution.id, 0, "first", 60)
    assert claimed is not None
    assert service.claim_execution(db, execution.id, 0, "second", 60) is None
    service.finish(db, execution.id, claimed.fencing_token, status="SUCCEEDED")
    db.commit()
    assert service.claim_execution(db, execution.id, 0, "second", 60) is None


def test_expired_execution_cannot_commit(db):
    execution = enqueue(db)
    claimed = service.claim_execution(db, execution.id, 0, "first", 60)
    claimed.lease_until = service.now() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(service.ExecutionLost):
        service.finish(db, execution.id, claimed.fencing_token, status="SUCCEEDED")


def test_retry_exhaustion_creates_failed_outbox(db):
    execution = enqueue(db)
    for attempt in range(1, 4):
        execution.next_attempt_at = None
        db.commit()
        claimed = service.claim_execution(db, execution.id, attempt - 1, "worker", 60)
        service.finish(db, execution.id, claimed.fencing_token, status="FAILED",
                       retryable=True, error_code="TEMPORARY_FAILURE")
        db.commit()
        db.refresh(execution)
        assert execution.attempt_count == attempt
        assert execution.status == ("RETRYING" if attempt < 3 else "FAILED")
        if attempt < 3:
            assert (29 if attempt == 1 else 119) <= (execution.next_attempt_at - service.now()).total_seconds() <= (30 if attempt == 1 else 120)
    assert db.scalar(select(TaskOutbox).where(TaskOutbox.execution_id == execution.id,
                                            TaskOutbox.routing_key == "agent.failed")) is not None


def test_unknown_task_is_not_accepted(db):
    with pytest.raises(ValueError):
        service.enqueue(db, task_type="shell.run", business_id="x", actor_id=1, generation=0, payload={})


def test_document_queue_drains_before_returning_to_legacy_path(db, monkeypatch):
    from types import SimpleNamespace
    from fastapi import BackgroundTasks
    from app.modules.jobs import technical_documents
    from app.modules.task_queue import adapters
    settings = Settings(_env_file=None, technical_document_execution_mode="rabbitmq",
                        rabbitmq_username="test", rabbitmq_password="test")
    monkeypatch.setattr(technical_documents, "get_settings", lambda: settings)
    request = SimpleNamespace(cas_no="rollout-test", doc_types=["msds"])
    queued_background = BackgroundTasks()
    run = technical_documents.schedule_pipeline(db, SimpleNamespace(id=1), request, queued_background, "fetch")
    assert queued_background.tasks == [] and settings.agent_execution_mode == "in_process"
    row = db.scalar(select(TaskExecution).where(TaskExecution.business_id == run.run_id))
    claimed = service.claim_execution(db, row.id, 0, "worker", 60)
    adapters.finish(db, row.id, claimed.fencing_token, status="SUCCEEDED")
    settings.agent_execution_mode = "rabbitmq"  # Enable only after document queue drained.
    assert settings.technical_document_execution_mode == "rabbitmq"
    settings.technical_document_execution_mode = settings.agent_execution_mode = "in_process"
    legacy_background = BackgroundTasks()
    legacy = technical_documents.schedule_pipeline(db, SimpleNamespace(id=1), request, legacy_background, "fetch")
    assert legacy.run_id != run.run_id and len(legacy_background.tasks) == 1
    assert service.claim_execution(db, row.id, 0, "old-message", 60) is None
    assert db.scalar(select(TaskExecution).where(TaskExecution.business_id == legacy.run_id)) is None


def test_document_acceptance_serializes_same_cas_requests(queue_engine, monkeypatch):
    from types import SimpleNamespace
    from fastapi import BackgroundTasks, HTTPException
    from app.modules.jobs import technical_documents
    config = Settings(_env_file=None, technical_document_execution_mode="rabbitmq",
                      rabbitmq_username="test", rabbitmq_password="test")
    monkeypatch.setattr(technical_documents, "get_settings", lambda: config)
    factory = sessionmaker(queue_engine, expire_on_commit=False)
    cas = "acceptance-" + uuid4().hex[:16]
    run_ids = []
    def submit(action):
        with factory() as session:
            try:
                background = BackgroundTasks()
                run = technical_documents.schedule_pipeline(session, SimpleNamespace(id=1),
                    SimpleNamespace(cas_no=cas, doc_types=["msds"]), background, action)
                run_ids.append(run.run_id)
                assert run.status == "QUEUED" and background.tasks == []
                assert run.result_json["cas_no"] == cas
                return 202
            except HTTPException as exc:
                return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(submit, ["fetch", "ingest"])) == [202, 409]
        with factory() as session:
            executions = list(session.scalars(select(TaskExecution).where(TaskExecution.business_id.in_(run_ids))))
            assert len(executions) == 1
            assert executions[0].payload == {"cas_no": cas, "doc_types": ["msds"]}
    finally:
        with factory() as session:
            execution_ids = list(session.scalars(select(TaskExecution.id).where(TaskExecution.business_id.in_(run_ids))))
            session.execute(delete(TaskOutbox).where(TaskOutbox.execution_id.in_(execution_ids)))
            session.execute(delete(TaskResourceLock).where(TaskResourceLock.execution_id.in_(execution_ids)))
            session.execute(delete(TaskExecution).where(TaskExecution.id.in_(execution_ids)))
            session.execute(delete(SchedulerJobRun).where(SchedulerJobRun.run_id.in_(run_ids)))
            session.commit()


@pytest.mark.parametrize("old_process_stopped", [True, False])
def test_recovery_requires_proof_old_process_stopped(db, monkeypatch, old_process_stopped):
    execution = service.enqueue(db, task_type="documents.ingest", business_id=uuid4().hex,
        actor_id=1, generation=0, payload={}, resource_key="cas:" + uuid4().hex)
    db.commit()
    claimed = service.claim_execution(db, execution.id, 0, "worker", 60)
    old_token = claimed.fencing_token
    claimed.lease_until = service.now() - timedelta(seconds=1)
    claimed.checkpoint = {"process_pid": 123456, "host": worker.socket.gethostname()}
    db.commit()
    monkeypatch.setattr(worker.processes, "process_alive", lambda _pid: not old_process_stopped)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, join_transaction_mode="create_savepoint")
    assert worker.recover(factory, Settings(_env_file=None)) == 1
    db.expire_all()
    recovered = db.get(TaskExecution, execution.id)
    assert recovered.fencing_token > old_token
    with pytest.raises(service.ExecutionLost):
        service.finish(db, execution.id, old_token, status="SUCCEEDED")
    db.rollback()
    recovered = db.get(TaskExecution, execution.id)
    assert recovered.status == ("RETRYING" if old_process_stopped else "FAILED")
    lock = db.scalar(select(TaskResourceLock).where(TaskResourceLock.execution_id == execution.id))
    assert lock is not None  # Retain it for retry or until manual isolation is proved.
    if not old_process_stopped:
        assert recovered.error_code == "RECOVERY_ISOLATION_REQUIRED"
        assert db.scalar(select(TaskOutbox).where(TaskOutbox.execution_id == execution.id,
            TaskOutbox.routing_key == "documents.failed")) is not None


def broker_settings():
    values = dotenv_values(ROOT / ".env.rabbitmq")
    import httpx
    vhost = "chemicalops-acceptance-20261008"
    with httpx.Client(base_url="http://127.0.0.1:15672", trust_env=False,
                      auth=(values["RABBITMQ_USERNAME"], values["RABBITMQ_PASSWORD"])) as client:
        client.put(f"/api/vhosts/{vhost}", json={}).raise_for_status()
        client.put(f"/api/permissions/{vhost}/{values['RABBITMQ_USERNAME']}",
                   json={"configure": ".*", "write": ".*", "read": ".*"}).raise_for_status()
    return Settings(_env_file=None, rabbitmq_username=values["RABBITMQ_USERNAME"],
                    rabbitmq_password=values["RABBITMQ_PASSWORD"], rabbitmq_vhost=vhost)


def test_real_confirmed_dispatch_and_unroutable_publish(db):
    execution = enqueue(db)
    db.commit()
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, join_transaction_mode="create_savepoint")

    async def verify():
        async with broker.connection(broker_settings()) as client:
            channel = await client.channel(publisher_confirms=True, on_return_raises=True)
            exchange = await broker.topology(channel)
            assert await dispatcher.dispatch_one(factory, exchange, "test-publisher")
            queue = await channel.get_queue("chemicalops.agent")
            message = await queue.get(timeout=10)
            envelope = broker.TaskMessage.model_validate_json(message.body)
            assert envelope.execution_id == execution.id
            await message.ack()
            with pytest.raises(Exception):
                await broker.publish(exchange, message_id=uuid4().hex, body=envelope, route="unbound-route")
    asyncio.run(verify())
    db.expire_all()
    assert db.scalar(select(TaskOutbox).where(TaskOutbox.execution_id == execution.id)).status == "SENT"


def test_invalid_broker_message_is_confirmed_to_quarantine(db):
    import aio_pika
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, join_transaction_mode="create_savepoint")
    async def verify():
        settings = broker_settings()
        async with broker.connection(settings) as client:
            channel = await client.channel(publisher_confirms=True, on_return_raises=True)
            await broker.topology(channel)
            source = await channel.get_queue("chemicalops.agent")
            failed = await channel.get_queue("chemicalops.agent.failed")
            await channel.default_exchange.publish(aio_pika.Message(b'{"command":"never execute"}'),
                routing_key="chemicalops.agent", mandatory=True)
            message = await source.get(timeout=10)
            await worker.handle(message, factory, settings, "agent", "acceptance", channel)
            result = await failed.get(timeout=10)
            assert result.body == b'{"error_code":"INVALID_TASK_MESSAGE"}'
            await result.ack()
    asyncio.run(verify())


def test_publish_confirmation_lost_is_republished_and_claimed_once(db):
    execution = enqueue(db)
    db.commit()
    first = service.claim_delivery(db, "crashed-publisher")

    async def verify():
        async with broker.connection(broker_settings()) as client:
            channel = await client.channel(publisher_confirms=True, on_return_raises=True)
            exchange = await broker.topology(channel)
            envelope = broker.TaskMessage(execution_id=execution.id, delivery_generation=0, task_type="agent.run")
            await broker.publish(exchange, message_id=first.id, body=envelope, route="agent")
            # Simulate crash before the database marks publication SENT.
            first.lease_until = service.now() - timedelta(seconds=1)
            db.commit()
            second = service.claim_delivery(db, "recovered-publisher")
            assert second.id == first.id
            await broker.publish(exchange, message_id=second.id, body=envelope, route="agent")
            service.settle_delivery(db, second.id, "recovered-publisher", confirmed=True)
            queue = await channel.get_queue("chemicalops.agent")
            claims = 0
            for _ in range(2):
                message = await queue.get(timeout=10)
                delivery = broker.TaskMessage.model_validate_json(message.body)
                assert delivery.execution_id == execution.id
                claimed = service.claim_execution(db, execution.id, 0, uuid4().hex, 60)
                if claimed:
                    claims += 1
                    service.finish(db, execution.id, claimed.fencing_token, status="SUCCEEDED")
                    db.commit()
                await message.ack()
            assert claims == 1
    asyncio.run(verify())


def test_real_worker_duplicate_and_completed_redelivery_do_not_execute(db, monkeypatch):
    execution = enqueue(db)
    db.commit()
    sessions = sessionmaker(bind=db.get_bind(), expire_on_commit=False, join_transaction_mode="create_savepoint")
    from contextlib import contextmanager
    from threading import Lock
    connection_lock = Lock()  # This rollback fixture deliberately shares one connection.
    @contextmanager
    def factory():
        with connection_lock:
            with sessions() as session:
                yield session
    executed = []

    async def fake_execution(factory, settings, claimed):
        # A model substitute exercises worker concurrency, not external model quality.
        executed.append(claimed.id)
        await asyncio.sleep(0.05)
        with factory() as session:
            row = service.finish(session, claimed.id, claimed.fencing_token, status="SUCCEEDED")
            row.checkpoint = {"completed_evidence": "preserved"}
            session.commit()
    monkeypatch.setattr(worker, "execute", fake_execution)

    async def verify():
        settings = broker_settings()
        async with broker.connection(settings) as client:
            channel = await client.channel(publisher_confirms=True, on_return_raises=True)
            exchange = await broker.topology(channel)
            envelope = broker.TaskMessage(execution_id=execution.id, delivery_generation=0, task_type="agent.run")
            queue = await channel.get_queue("chemicalops.agent")
            for _ in range(2):
                await broker.publish(exchange, message_id=uuid4().hex, body=envelope, route="agent")
            messages = [await queue.get(timeout=10) for _ in range(2)]
            await asyncio.gather(*(worker.handle(message, factory, settings, "agent", uuid4().hex, channel)
                                   for message in messages))
            assert executed == [execution.id]
            # Simulate ACK loss after the result transaction has already committed.
            await broker.publish(exchange, message_id=uuid4().hex, body=envelope, route="agent")
            replay = await queue.get(timeout=10)
            await worker.handle(replay, factory, settings, "agent", "replay", channel)
            assert executed == [execution.id]
    asyncio.run(verify())
    db.expire_all()
    assert db.get(TaskExecution, execution.id).checkpoint == {"completed_evidence": "preserved"}


def test_concurrent_publishers_claim_once(queue_engine):
    factory = sessionmaker(queue_engine, expire_on_commit=False)
    with factory() as db:
        execution = enqueue(db)
        execution_id = execution.id
        db.commit()
    def claim(owner):
        with factory() as db:
            row = service.claim_delivery(db, owner)
            return row.id if row else None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["publisher-a", "publisher-b"]))
        assert sum(result is not None for result in results) == 1
    finally:
        with factory() as db:
            db.execute(delete(TaskOutbox).where(TaskOutbox.execution_id == execution_id))
            db.execute(delete(TaskExecution).where(TaskExecution.id == execution_id))
            db.commit()
