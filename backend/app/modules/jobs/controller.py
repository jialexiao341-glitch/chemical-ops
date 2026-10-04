"""后台扫描任务 HTTP 接口。"""

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.jobs import service
from app.modules.jobs.schema import SchedulerJobRunRead, TechnicalDocumentPipelineCreate, TechnicalDocumentPreviewRead, TechnicalDocumentRead, TechnicalDocumentSourceRead
from app.modules.jobs import technical_documents
from app.modules.chemicals.model import Chemical
from app.modules.system.model import User


router = APIRouter(prefix="/jobs", tags=["后台任务"])


@router.get("/technical-documents", response_model=list[TechnicalDocumentSourceRead], summary="查询 TDS/MSDS 原始资料")
def technical_document_list(
    cas_no: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("master.chemicals.read")),
) -> list[TechnicalDocumentSourceRead]:
    technical_documents.require_technical_or_admin(db, user)
    try:
        return technical_documents.list_source_documents(db, cas=cas_no)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="无法读取 MinIO 技术资料列表") from exc


@router.get("/technical-documents/runs", response_model=list[SchedulerJobRunRead], summary="查询技术资料处理任务")
def technical_document_runs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("master.chemicals.read")),
) -> list[SchedulerJobRunRead]:
    technical_documents.require_technical_or_admin(db, user)
    return technical_documents.list_pipeline_runs(db, limit=limit)


@router.get("/technical-documents/{document_id}/preview", response_model=TechnicalDocumentPreviewRead, summary="预览结构化技术资料")
def technical_document_preview(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("master.chemicals.read")),
) -> TechnicalDocumentPreviewRead:
    technical_documents.require_technical_or_admin(db, user)
    result = technical_documents.get_document_preview(db, document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="技术资料不存在")
    document, sections = result
    return TechnicalDocumentPreviewRead(
        **TechnicalDocumentRead.model_validate(document).model_dump(),
        meta_json=document.meta_json,
        sections=sections,
    )


@router.get("/technical-documents/source-file", summary="预览 MinIO 原始资料文件")
def technical_document_source_file(
    cas_no: str = Query(pattern=r"^\d{2,7}-\d{2}-\d$"),
    doc_type: str = Query(pattern="^(msds|tds)$"),
    extension: str = Query(pattern="^(html|pdf)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("master.chemicals.read")),
) -> Response:
    technical_documents.require_technical_or_admin(db, user)
    try:
        content, media_type, object_key = technical_documents.get_source_file(cas_no, doc_type, extension)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MinIO 中没有该原始资料") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="读取 MinIO 原始资料失败") from exc
    if extension == "html":
        from app.modules.doc_kb.service import html_to_text

        content = html_to_text(content.decode("utf-8", errors="replace")).encode("utf-8")
        media_type = "text/plain; charset=utf-8"
    headers = {
        "Content-Disposition": f'inline; filename="{object_key.rsplit("/", 1)[-1]}"',
        "X-Content-Type-Options": "nosniff",
    }
    if extension == "html":
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return Response(content=content, media_type=media_type, headers=headers)


@router.post("/technical-documents/fetch", response_model=SchedulerJobRunRead, summary="仅抓取并保存 TDS/MSDS 至 MinIO")
def start_technical_document_fetch(
    data: TechnicalDocumentPipelineCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("master.chemicals.write")),
) -> SchedulerJobRunRead:
    technical_documents.require_technical_or_admin(db, user)
    chemical = db.scalar(select(Chemical).where(Chemical.cas_no == data.cas_no, Chemical.status == "ACTIVE"))
    if chemical is None:
        raise HTTPException(status_code=404, detail="未找到启用状态的化学品 CAS 号")
    if technical_documents.has_active_run(db, data.cas_no):
        raise HTTPException(status_code=409, detail="该 CAS 的资料任务仍在处理中")
    run = technical_documents.create_pipeline_run(db, uuid4().hex)
    background_tasks.add_task(technical_documents.execute_fetch, run.run_id, data.cas_no, data.doc_types)
    return run


@router.post("/technical-documents/ingest", response_model=SchedulerJobRunRead, summary="解析 MinIO 资料并写入结构化及向量知识库")
def start_technical_document_ingest(
    data: TechnicalDocumentPipelineCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("master.chemicals.write")),
) -> SchedulerJobRunRead:
    technical_documents.require_technical_or_admin(db, user)
    chemical = db.scalar(select(Chemical).where(Chemical.cas_no == data.cas_no, Chemical.status == "ACTIVE"))
    if chemical is None:
        raise HTTPException(status_code=404, detail="未找到启用状态的化学品 CAS 号")
    if technical_documents.has_active_run(db, data.cas_no):
        raise HTTPException(status_code=409, detail="该 CAS 的资料任务仍在处理中")
    try:
        available = technical_documents.list_source_documents(db, cas=data.cas_no)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="无法读取 MinIO 技术资料列表") from exc
    available_types = {row["doc_type"] for row in available if row["ingestible"]}
    missing_types = set(data.doc_types) - available_types
    if missing_types:
        missing_label = "、".join(sorted(value.upper() for value in missing_types))
        raise HTTPException(status_code=409, detail=f"请先将 {missing_label} 文件拉取到 MinIO")
    run = technical_documents.create_pipeline_run(db, uuid4().hex)
    background_tasks.add_task(technical_documents.execute_ingest, run.run_id, data.cas_no, data.doc_types)
    return run


@router.post("/overdue-scan", response_model=dict[str, int], summary="扫描逾期到货")
def overdue_scan(db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> dict[str, int]:
    """手工触发一次逾期到货扫描；生产环境可由定时任务调用同一服务。"""
    return service.scan_overdue_deliveries(db, user)


@router.post("/inventory-expiry-scan", response_model=dict[str, int], summary="扫描临期库存批次")
def inventory_expiry_scan(db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> dict[str, int]:
    """手工触发一次临期库存扫描。"""

    return service.scan_expiring_inventory(db, user)


@router.post("/alert-scan", response_model=dict[str, int], summary="扫描业务主动提醒")
def alert_scan(db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> dict[str, int]:
    """手工运行所有已配置的确定性业务提醒规则。"""

    return service.scan_active_alerts(db, user)


@router.get("/runs", response_model=list[SchedulerJobRunRead], summary="查询后台任务运行历史")
def list_job_runs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("operations.exceptions.read")),
) -> list[SchedulerJobRunRead]:
    """返回最近的后台扫描运行结果，不包含单据正文或个人数据。"""

    return service.list_job_runs(db, limit=limit)
