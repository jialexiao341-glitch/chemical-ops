"""技术资料抓取、解析与向量化后台流水线。"""

import subprocess
import sys
from pathlib import Path
import re
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.config import get_settings
from app.modules.chemicals.model import Chemical
from app.modules.doc_kb.model import AiDocument, AiDocumentSection
from app.modules.jobs.model import SchedulerJobRun
from app.modules.jobs.service import start_scheduled_run, update_scheduled_run
from app.modules.system import crud
from app.modules.system.model import User

ROOT = Path(__file__).resolve().parents[4]
PIPELINE_NAME = "technical_documents_pipeline"


def json_compatible_result(result: dict[str, Any]) -> dict[str, Any]:
    """将数据库与 MinIO 元数据转换为 JSON 可持久化值。"""

    return jsonable_encoder(result)


def missing_requested_types(doc_types: list[str], sources: list[dict[str, Any]]) -> list[str]:
    """返回尚未在 MinIO 中找到的所选资料类型。"""

    available_types = {source["doc_type"] for source in sources}
    return [doc_type for doc_type in doc_types if doc_type not in available_types]


def require_technical_or_admin(db: Session, user: User) -> None:
    roles = set(crud.get_user_role_codes(db, user.id))
    if not roles.intersection({"TECHNICAL", "SYS_ADMIN"}):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="仅技术研发人员和系统管理员可管理技术资料")


def minio_client():
    settings = get_settings()
    if not settings.minio_access_key or not settings.minio_secret_key:
        raise RuntimeError("MinIO 访问密钥未配置")
    from minio import Minio

    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        region=settings.minio_region,
    )


def source_object_key(cas: str, doc_type: str, extension: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{2,7}-\d{2}-\d", cas):
        raise ValueError("CAS 号格式无效")
    if doc_type == "msds" and extension in {"html", "pdf"}:
        return "chemicalops-msds", f"{cas}.{extension}"
    if doc_type == "tds" and extension in {"html", "pdf"}:
        return "chemicalops-tds", f"{cas}.{extension}"
    raise ValueError("资料类型或文件格式不受支持")


def list_source_documents(db: Session, *, cas: str | None = None) -> list[dict[str, Any]]:
    client = minio_client()
    rows: list[dict[str, Any]] = []
    bucket_types = (("chemicalops-msds", "msds"), ("chemicalops-tds", "tds"))
    for bucket, doc_type in bucket_types:
        if not client.bucket_exists(bucket):
            continue
        for obj in client.list_objects(bucket, recursive=True):
            name = (obj.object_name or "").rsplit("/", 1)[-1]
            if name.endswith("-property.html"):
                continue
            match = re.fullmatch(r"(\d{2,7}-\d{2}-\d)\.(html|pdf)", name)
            if match is None:
                continue
            cas_no, extension = match.groups()
            if cas and cas_no != cas:
                continue
            rows.append({
                "cas_no": cas_no,
                "doc_type": doc_type,
                "extension": extension,
                "object_key": obj.object_name,
                "source_bucket": bucket,
                "file_size": int(obj.size or 0),
                "updated_at": obj.last_modified,
            })

    cas_values = {row["cas_no"] for row in rows}
    names = {
        cas_no: chemical_name
        for cas_no, chemical_name in db.execute(
            select(Chemical.cas_no, Chemical.chemical_name).where(Chemical.cas_no.in_(cas_values) if cas_values else False)
        ).all()
    }
    documents = list(db.scalars(select(AiDocument).where(AiDocument.cas_no.in_(cas_values) if cas_values else False)).all())
    parsed_by_type = {(doc.cas_no, doc.doc_type): doc for doc in documents}
    for row in rows:
        document = parsed_by_type.get((row["cas_no"], row["doc_type"]))
        row.update({
            "doc_id": document.id if document else None,
            "name_zh": names.get(row["cas_no"]),
            "title": document.title if document else None,
            "parse_status": document.parse_status if document else "PENDING",
            "reject_reason": document.reject_reason if document else None,
            "section_count": document.section_count if document else 0,
            "char_count": document.char_count if document else 0,
            "ingestible": row["doc_type"] == "tds" or row["extension"] == "html",
        })
    return sorted(rows, key=lambda row: (row["cas_no"], row["doc_type"], row["extension"]))


def get_document_preview(db: Session, document_id: int) -> tuple[AiDocument, list[AiDocumentSection]] | None:
    document = db.get(AiDocument, document_id)
    if document is None or document.doc_type not in {"msds", "tds"}:
        return None
    sections = list(
        db.scalars(
            select(AiDocumentSection)
            .where(AiDocumentSection.document_id == document.id)
            .order_by(AiDocumentSection.section_no, AiDocumentSection.id)
        ).all()
    )
    return document, sections


def get_source_file(cas: str, doc_type: str, extension: str) -> tuple[bytes, str, str]:
    bucket, object_key = source_object_key(cas, doc_type, extension)
    client = minio_client()
    try:
        response = client.get_object(bucket, object_key)
    except Exception as exc:
        if getattr(exc, "code", None) in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            raise FileNotFoundError(object_key) from exc
        raise
    try:
        content = response.read()
        content_type = "application/pdf" if extension == "pdf" else "text/html; charset=utf-8"
        return content, content_type, object_key
    finally:
        response.close()
        response.release_conn()


def list_pipeline_runs(db: Session, *, limit: int = 50) -> list[SchedulerJobRun]:
    statement = (
        select(SchedulerJobRun)
        .where(SchedulerJobRun.task_name == PIPELINE_NAME)
        .order_by(desc(SchedulerJobRun.started_at), desc(SchedulerJobRun.id))
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def has_active_run(db: Session, cas: str) -> bool:
    statement = (
        select(SchedulerJobRun)
        .where(SchedulerJobRun.task_name == PIPELINE_NAME, SchedulerJobRun.status.in_(("QUEUED", "RUNNING", "RETRYING")))
        .order_by(desc(SchedulerJobRun.started_at))
    )
    runs = db.scalars(statement).all()
    return any((run.result_json or {}).get("cas_no") == cas for run in runs)


def create_pipeline_run(db: Session, run_id: str) -> SchedulerJobRun:
    return start_scheduled_run(db, run_id, task_name=PIPELINE_NAME)


def schedule_pipeline(db, user, data, background_tasks, action):
    """Persist task parameters at acceptance, with one durable execution record."""
    queued = get_settings().technical_document_execution_mode == "database"
    from uuid import uuid4
    run = start_scheduled_run(db, uuid4().hex, task_name=PIPELINE_NAME, commit=False)
    run.status = "QUEUED" if queued else "RUNNING"
    run.result_json = {"action": action, "cas_no": data.cas_no, "doc_types": data.doc_types, "stages": []}
    try:
        if queued:
            from app.modules.task_queue.service import enqueue
            enqueue(db, task_type=f"documents.{action}", business_id=run.run_id,
                    actor_id=user.id, generation=0,
                    payload={"cas_no": data.cas_no, "doc_types": data.doc_types},
                    resource_key=f"documents:{data.cas_no}")
        db.commit()
    except IntegrityError:
        db.rollback()
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="该 CAS 的资料任务仍在处理中") from None
    if not queued:
        target = execute_fetch if action == "fetch" else execute_ingest
        background_tasks.add_task(target, run.run_id, data.cas_no, data.doc_types)
    return run


def _execute_commands(run_id: str, cas: str, doc_types: list[str], action: str, commands: list[tuple[str, list[str]]]) -> None:
    db = SessionLocal()
    run: SchedulerJobRun | None = None
    stages: list[dict[str, Any]] = []
    try:
        run = db.scalar(select(SchedulerJobRun).where(SchedulerJobRun.run_id == run_id))
        if run is None:
            raise RuntimeError("流水线任务记录不存在")
        for stage, command in commands:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=900, check=False)
            output = (result.stdout + "\n" + result.stderr).strip()[-5000:]
            stages.append({"stage": stage, "status": "SUCCEEDED" if result.returncode == 0 else "FAILED", "exit_code": result.returncode, "output": output})
            run.result_json = {"action": action, "cas_no": cas, "doc_types": doc_types, "stages": stages}
            db.commit()
            if result.returncode:
                raise RuntimeError(f"{stage} 阶段失败（退出码 {result.returncode}）")
        db.expire_all()
        if action == "fetch":
            sources = [row for row in list_source_documents(db, cas=cas) if row["doc_type"] in doc_types]
            missing_types = missing_requested_types(doc_types, sources)
            result_data = {
                "action": action,
                "cas_no": cas,
                "doc_types": doc_types,
                "stages": stages,
                "files": sources,
                "missing_doc_types": missing_types,
            }
            if missing_types:
                stages[-1]["status"] = "FAILED"
                stages[-1]["missing_doc_types"] = missing_types
                result_data["stages"] = stages
                run.result_json = json_compatible_result(result_data)
                missing_label = "、".join(doc_type.upper() for doc_type in missing_types)
                update_scheduled_run(
                    db,
                    run,
                    attempt_count=1,
                    error_type=f"未能拉取全部所选资料，缺少：{missing_label}",
                )
                return
        else:
            documents = list(db.scalars(select(AiDocument).where(AiDocument.cas_no == cas, AiDocument.doc_type.in_(doc_types))).all())
            if not documents:
                raise RuntimeError("所选类型没有完成结构化处理")
            result_data = {
                "action": action,
                "cas_no": cas,
                "doc_types": doc_types,
                "stages": stages,
                "documents": [
                    {"doc_type": doc.doc_type, "parse_status": doc.parse_status, "section_count": doc.section_count, "char_count": doc.char_count, "reject_reason": doc.reject_reason}
                    for doc in documents
                ],
            }
        update_scheduled_run(db, run, attempt_count=1, result=json_compatible_result(result_data))
    except Exception as exc:
        db.rollback()
        current = db.scalar(select(SchedulerJobRun).where(SchedulerJobRun.run_id == run_id))
        if current is not None:
            current.result_json = {"action": action, "cas_no": cas, "doc_types": doc_types, "stages": stages}
            error_detail = str(exc).split("[SQL:", 1)[0].split("[parameters:", 1)[0].strip()
            update_scheduled_run(db, current, attempt_count=1, error_type=f"{type(exc).__name__}: {error_detail}")
    finally:
        db.close()


def execute_fetch(run_id: str, cas: str, doc_types: list[str]) -> None:
    python = sys.executable
    commands = [("fetch", [python, str(ROOT / "scripts" / "crawl_tds_msds.py"), "--cas", cas, "--doc-types", *doc_types])]
    _execute_commands(run_id, cas, doc_types, "fetch", commands)


def execute_ingest(run_id: str, cas: str, doc_types: list[str]) -> None:
    python = sys.executable
    commands: list[tuple[str, list[str]]] = []
    for doc_type in doc_types:
        commands.append((f"parse_{doc_type}", [python, str(ROOT / "scripts" / "parse_tds_msds.py"), "--cas", cas, "--doc-type", doc_type]))
        commands.append((f"embed_{doc_type}", [python, str(ROOT / "scripts" / "embed_sections.py"), "--cas", cas, "--doc-type", doc_type]))
    _execute_commands(run_id, cas, doc_types, "ingest", commands)
