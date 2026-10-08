"""Task adapter acceptance with real isolated MySQL and explicit script substitutes."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.modules.doc_kb.model import AiDocument
from app.modules.jobs import technical_documents as documents
from app.modules.jobs.model import SchedulerJobRun
from app.modules.task_queue import context, execution, service
from app.modules.task_queue.model import TaskExecution
from tests.test_task_queue_delivery import queue_engine, db


@pytest.fixture
def task_environment(db, monkeypatch):
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(execution, "SessionLocal", factory)
    monkeypatch.setattr(execution, "document_permission", lambda *_args: None)
    monkeypatch.setattr(execution, "source_hash", lambda *_args: "valid-input")
    return factory


def accept(db, monkeypatch, action="ingest", types=None):
    run_id = uuid4().hex
    cas = "test-" + uuid4().hex[:12]
    db.add(SchedulerJobRun(run_id=run_id, task_name="technical_documents_pipeline", status="QUEUED",
        result_json={"cas_no": cas, "action": action, "doc_types": types or ["msds"], "stages": []}))
    row = service.enqueue(db, task_type=f"documents.{action}", business_id=run_id,
        actor_id=1, generation=0, payload={"cas_no": cas, "doc_types": types or ["msds"]})
    db.commit()
    claim(db, row, monkeypatch)
    return row, run_id, cas


def claim(db, row, monkeypatch):
    current = service.claim_execution(db, row.id, row.delivery_generation, "acceptance", 60)
    monkeypatch.setenv("CHEMICALOPS_EXECUTION_ID", current.id)
    monkeypatch.setenv("CHEMICALOPS_EXECUTION_TOKEN", str(current.fencing_token))


@pytest.mark.parametrize("source_changed", [False, True])
def test_parse_checkpoint_survives_vector_failure_and_skips_valid_stage(db, task_environment, monkeypatch, source_changed):
    row, run_id, cas = accept(db, monkeypatch)
    db.add(AiDocument(cas_no=cas, doc_type="msds", source_bucket="test", object_key="test.html", parse_status="PARSED"))
    db.commit()
    calls = []
    def script(command, **kwargs):
        assert kwargs["timeout"] == 900
        calls.append(command[1])
        failed = "embed_sections" in command[1] and sum("embed_sections" in call for call in calls) == 1
        return SimpleNamespace(returncode=1 if failed else 0, stdout="substitute stage", stderr="")
    monkeypatch.setattr(execution.subprocess, "run", script)
    asyncio.run(execution.run())
    db.expire_all()
    row = db.get(TaskExecution, row.id)
    assert row.status == "RETRYING" and "parse_msds" in row.checkpoint["stages"]
    assert row.business_id == run_id
    row.next_attempt_at = None
    db.commit()
    if source_changed:
        monkeypatch.setattr(execution, "source_hash", lambda *_args: "changed-input")
    claim(db, row, monkeypatch)
    asyncio.run(execution.run())
    db.expire_all()
    assert db.get(TaskExecution, row.id).status == "SUCCEEDED"
    assert sum("parse_tds_msds" in call for call in calls) == (2 if source_changed else 1)
    assert sum("embed_sections" in call for call in calls) == 2
    run = db.scalar(select(SchedulerJobRun).where(SchedulerJobRun.run_id == run_id))
    assert run.status == "SUCCEEDED" and run.run_id == run_id


def test_partial_fetch_is_permanent_failure_with_preserved_files(db, task_environment, monkeypatch):
    row, run_id, cas = accept(db, monkeypatch, action="fetch", types=["msds", "tds"])
    monkeypatch.setattr(execution.subprocess, "run", lambda *args, **kwargs:
        SimpleNamespace(returncode=0, stdout="substitute fetched msds", stderr=""))
    monkeypatch.setattr(documents, "list_source_documents", lambda *args, **kwargs:
        [{"doc_type": "msds", "object_key": cas + ".html"}])
    asyncio.run(execution.run())
    db.expire_all()
    assert db.get(TaskExecution, row.id).status == "FAILED"
    assert db.get(TaskExecution, row.id).attempt_count == 1
    run = db.scalar(select(SchedulerJobRun).where(SchedulerJobRun.run_id == run_id))
    assert run.result_json["missing_doc_types"] == ["tds"]
    assert run.result_json["files"][0]["doc_type"] == "msds"


def test_revoked_permission_never_starts_scripts(db, task_environment, monkeypatch):
    row, _, _ = accept(db, monkeypatch)
    def denied(*_args):
        raise execution.PermanentTaskError("PERMISSION_DENIED")
    monkeypatch.setattr(execution, "document_permission", denied)
    monkeypatch.setattr(execution.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("unauthorized script executed"))
    asyncio.run(execution.run())
    db.expire_all()
    assert db.get(TaskExecution, row.id).error_code == "PERMISSION_DENIED"
    assert db.get(TaskExecution, row.id).status == "FAILED"


def test_invalidated_token_stops_before_stage(db, task_environment, monkeypatch):
    row, _, _ = accept(db, monkeypatch)
    row.fencing_token += 1
    db.commit()
    monkeypatch.setattr(execution.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("obsolete script executed"))
    asyncio.run(execution.run())
    db.expire_all()
    assert db.get(TaskExecution, row.id).status == "RUNNING"
    assert db.get(TaskExecution, row.id).checkpoint == {}
    from app.modules.doc_kb import service as doc_service
    with pytest.raises(service.ExecutionLost):
        doc_service.store_parsed(db, cas="token-test", doc_type="msds", bucket="test", object_key="test.html",
            parsed=doc_service.ParsedDoc(cas="token-test", doc_type="msds"))
