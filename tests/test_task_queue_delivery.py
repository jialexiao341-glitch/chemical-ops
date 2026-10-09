"""Real isolated MySQL tests; never create queue tables in the business database."""

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.task_queue.model import TaskExecution, TaskOutbox, TaskResourceLock
from app.modules.task_queue import service
from app.modules.task_queue import worker
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
    with engine.begin() as connection:
        for _ in range(2):
            for filename in ("041_async_task_dispatch.sql", "042_database_task_queue.sql"):
                for statement in (ROOT / "database/migrations" / filename).read_text().split(";"):
                    if statement.strip():
                        connection.exec_driver_sql(statement)
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


def test_business_record_and_execution_share_one_transaction(db):
    run_id = uuid4().hex
    run = start_scheduled_run(db, run_id, task_name="technical_documents_pipeline", commit=False)
    execution = service.enqueue(db, task_type="documents.fetch", business_id=run_id,
        actor_id=1, generation=0, payload={"cas_no": "64-17-5", "doc_types": ["msds"]})
    execution_id = execution.id
    db.rollback()
    assert db.scalar(select(SchedulerJobRun).where(SchedulerJobRun.run_id == run_id)) is None
    assert db.get(TaskExecution, execution_id) is None
    assert db.scalar(select(TaskOutbox).where(TaskOutbox.execution_id == execution_id)) is None


def test_committed_task_survives_without_worker(db):
    execution = enqueue(db)
    db.commit()
    row = db.scalar(select(TaskOutbox).where(TaskOutbox.execution_id == execution.id))
    assert row is None and execution.status == "QUEUED"


def test_resource_uniqueness_blocks_a_second_active_task(db):
    resource = uuid4().hex
    enqueue(db, resource_key=resource)
    with pytest.raises(IntegrityError):
        enqueue(db, resource_key=resource)
    db.rollback()


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


def test_retry_exhaustion_keeps_failure_in_execution(db):
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
                                            TaskOutbox.routing_key == "agent.failed")) is None


def test_unknown_task_is_not_accepted(db):
    with pytest.raises(ValueError):
        service.enqueue(db, task_type="shell.run", business_id="x", actor_id=1, generation=0, payload={})


def test_document_queue_drains_before_returning_to_legacy_path(db, monkeypatch):
    from types import SimpleNamespace
    from fastapi import BackgroundTasks
    from app.modules.jobs import technical_documents
    from app.modules.task_queue import adapters
    settings = Settings(_env_file=None, technical_document_execution_mode="database", agent_execution_mode="in_process")
    monkeypatch.setattr(technical_documents, "get_settings", lambda: settings)
    request = SimpleNamespace(cas_no="rollout-test", doc_types=["msds"])
    queued_background = BackgroundTasks()
    run = technical_documents.schedule_pipeline(db, SimpleNamespace(id=1), request, queued_background, "fetch")
    assert queued_background.tasks == [] and settings.agent_execution_mode == "in_process"
    row = db.scalar(select(TaskExecution).where(TaskExecution.business_id == run.run_id))
    claimed = service.claim_execution(db, row.id, 0, "worker", 60)
    adapters.finish(db, row.id, claimed.fencing_token, status="SUCCEEDED")
    settings.agent_execution_mode = "database"  # Enable only after document queue drained.
    assert settings.technical_document_execution_mode == "database"
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
    config = Settings(_env_file=None, technical_document_execution_mode="database")
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
            TaskOutbox.routing_key == "documents.failed")) is None


def test_claim_next_filters_queue_due_time_and_terminal_status(db):
    agent = enqueue(db)
    delayed = service.enqueue(db, task_type="documents.fetch", business_id=uuid4().hex,
        actor_id=1, generation=0, payload={})
    delayed.next_attempt_at = service.now() + timedelta(seconds=60)
    ready = service.enqueue(db, task_type="documents.ingest", business_id=uuid4().hex,
        actor_id=1, generation=0, payload={})
    db.commit()
    claimed = service.claim_next(db, "documents", "worker", 60)
    assert claimed.id == ready.id
    assert service.claim_next(db, "documents", "worker", 60) is None
    assert service.claim_next(db, "agent", "worker", 60).id == agent.id
    with pytest.raises(ValueError):
        service.claim_next(db, "unknown", "worker", 60)


def test_concurrent_workers_claim_once(queue_engine):
    factory = sessionmaker(queue_engine, expire_on_commit=False)
    with factory() as db:
        execution = enqueue(db)
        execution_id = execution.id
        db.commit()
    def claim(owner):
        with factory() as db:
            row = service.claim_next(db, "agent", owner, 60)
            return row.id if row else None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["worker-a", "worker-b"]))
        assert results.count(execution_id) == 1
        assert results.count(None) == 1
    finally:
        with factory() as db:
            db.execute(delete(TaskExecution).where(TaskExecution.id == execution_id))
            db.commit()


def test_worker_skips_a_row_locked_by_another_worker(queue_engine):
    factory = sessionmaker(queue_engine, expire_on_commit=False)
    with factory() as db:
        first, second = enqueue(db), enqueue(db)
        ids = [first.id, second.id]
        db.commit()
    try:
        with factory() as locked:
            row = locked.scalar(select(TaskExecution).where(TaskExecution.id == ids[0])
                .with_for_update())
            with factory() as other:
                claimed = service.claim_next(other, "agent", "other-worker", 60)
                assert claimed.id in ids and claimed.id != row.id
            locked.rollback()
    finally:
        with factory() as db:
            db.execute(delete(TaskExecution).where(TaskExecution.id.in_(ids)))
            db.commit()
