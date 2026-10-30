"""Whitelisted execution adapters; never accept commands from message payloads."""

import asyncio
import hashlib
import subprocess
import sys
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.task_queue import adapters, context, service
from app.modules.task_queue.model import TaskExecution
from app.modules.system import crud

ROOT = Path(__file__).resolve().parents[4]


class PermanentTaskError(RuntimeError):
    pass


def source_hash(db, cas, doc_types):
    from app.modules.jobs import technical_documents as documents
    digest = hashlib.sha256()
    sources = [row for row in documents.list_source_documents(db, cas=cas) if row["doc_type"] in doc_types]
    for row in sorted(sources, key=lambda row: (row["doc_type"], row["extension"])):
        content, _, _ = documents.get_source_file(cas, row["doc_type"], row["extension"])
        digest.update(row["object_key"].encode())
        digest.update(content)
    return digest.hexdigest()


def document_permission(db, actor_id):
    from app.modules.jobs.technical_documents import require_technical_or_admin
    user = crud.get_user(db, actor_id)
    if user is None or user.status != "ACTIVE" or "master.chemicals.write" not in crud.get_user_permission_codes(db, actor_id):
        raise PermanentTaskError("PERMISSION_DENIED")
    require_technical_or_admin(db, user)
    return user


def run_documents(execution_id, token):
    from app.modules.jobs import technical_documents as documents
    from app.modules.jobs.model import SchedulerJobRun
    from app.modules.doc_kb.model import AiDocument
    settings = get_settings()
    with SessionLocal() as db:
        execution = service.locked_execution(db, execution_id, token)
        payload = execution.payload
        run_id = execution.business_id
        cas, doc_types = payload["cas_no"], payload["doc_types"]
        action = "fetch" if execution.task_type == "documents.fetch" else "ingest"
        document_permission(db, execution.actor_id)
        actor_id = execution.actor_id
        run = db.scalar(select(SchedulerJobRun).where(SchedulerJobRun.run_id == run_id))
        if run is None:
            raise PermanentTaskError("BUSINESS_TASK_MISSING")
        run.status = "RUNNING"
        checkpoints = dict(execution.checkpoint.get("stages", {}))
        db.commit()
        commands = [("fetch", [sys.executable, str(ROOT / "scripts/crawl_tds_msds.py"),
                                "--cas", cas, "--doc-types", *doc_types])]
        if action == "ingest":
            commands = [(f"{step}_{kind}", [sys.executable, str(ROOT / "scripts" / script),
                         "--cas", cas, "--doc-type", kind])
                        for kind in doc_types for step, script in
                        (("parse", "parse_tds_msds.py"), ("embed", "embed_sections.py"))]
        stages = []
        for stage, command in commands:
            service.locked_execution(db, execution_id, token)
            document_permission(db, actor_id)
            fingerprint = source_hash(db, cas, doc_types)
            db.commit()
            saved = checkpoints.get(stage)
            if saved and saved.get("source_hash") == fingerprint:
                stages.append(saved["result"])
                continue
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=900, check=False)
            output = (result.stdout + "\n" + result.stderr).strip()[-5000:]
            for key, value in settings.model_dump().items():
                if value and any(label in key for label in ("password", "secret", "api_key")):
                    output = output.replace(str(value), "[redacted]")
            stage_result = {"stage": stage, "status": "SUCCEEDED" if result.returncode == 0 else "FAILED",
                            "exit_code": result.returncode, "output": output}
            stages.append(stage_result)
            execution = service.locked_execution(db, execution_id, token)
            run.result_json = {"action": action, "cas_no": cas, "doc_types": doc_types, "stages": stages}
            if result.returncode != 0:
                db.commit()
                if result.returncode in {2, 78}:
                    raise PermanentTaskError("DOCUMENT_STAGE_REJECTED")
                raise RuntimeError("DOCUMENT_STAGE_INTERRUPTED")
            if stage.startswith("parse_"):
                kind = stage.removeprefix("parse_")
                document = db.scalar(select(AiDocument).where(AiDocument.cas_no == cas, AiDocument.doc_type == kind))
                if document is None or document.parse_status != "PARSED":
                    db.commit()
                    raise PermanentTaskError("DOCUMENT_PARSE_REJECTED")
            current_hash = source_hash(db, cas, doc_types)
            if action == "ingest" and current_hash != fingerprint:
                db.commit()
                raise PermanentTaskError("DOCUMENT_SOURCE_CHANGED")
            checkpoints[stage] = {"source_hash": current_hash, "result": stage_result}
            execution.checkpoint = {**execution.checkpoint, "stages": checkpoints}
            db.commit()
        service.locked_execution(db, execution_id, token)
        if action == "fetch":
            sources = [row for row in documents.list_source_documents(db, cas=cas) if row["doc_type"] in doc_types]
            missing = documents.missing_requested_types(doc_types, sources)
            run.result_json = documents.json_compatible_result({**run.result_json, "files": sources,
                                                               "missing_doc_types": missing})
            if missing:
                adapters.finish(db, execution_id, token, status="FAILED", error_code="DOCUMENT_SOURCE_MISSING")
                return
        else:
            parsed = list(db.scalars(select(AiDocument).where(AiDocument.cas_no == cas,
                                                           AiDocument.doc_type.in_(doc_types))).all())
            if not parsed:
                raise PermanentTaskError("DOCUMENT_PARSE_REJECTED")
            run.result_json = {**run.result_json, "documents": [
                {"doc_type": doc.doc_type, "parse_status": doc.parse_status, "section_count": doc.section_count,
                 "char_count": doc.char_count, "reject_reason": doc.reject_reason} for doc in parsed]}
        adapters.finish(db, execution_id, token, status="SUCCEEDED")


async def run():
    execution_id, token = context.identity()
    settings = get_settings()
    try:
        with SessionLocal() as db:
            execution = service.locked_execution(db, execution_id, token)
            task_type, business_id, actor_id, revision = (
                execution.task_type, execution.business_id, execution.actor_id, execution.business_revision)
            db.commit()
        if task_type.startswith("documents."):
            run_documents(execution_id, token)
        elif task_type == "agent.run":
            from app.modules.ai.agent_runtime import run_prepared_task
            await run_prepared_task(business_id, actor_id, revision)
        else:
            raise PermanentTaskError("UNKNOWN_TASK_TYPE")
    except service.ExecutionLost:
        return
    except Exception as exc:
        permanent = isinstance(exc, (PermanentTaskError, HTTPException, ValueError))
        # Store only controlled error codes, never SQL parameters or connection URLs.
        code = str(exc) if isinstance(exc, PermanentTaskError) else "PERMISSION_DENIED" if isinstance(exc, HTTPException) else "TASK_EXECUTION_ERROR"
        with SessionLocal() as db:
            try:
                adapters.finish(db, execution_id, token, status="FAILED", retryable=not permanent,
                                max_attempts=settings.task_max_attempts, error_code=code)
            except service.ExecutionLost:
                db.rollback()
