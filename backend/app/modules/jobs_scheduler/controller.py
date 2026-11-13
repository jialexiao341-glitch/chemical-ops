"""后台扫描任务 HTTP 接口。"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.core.rate_limit import limit_document
from app.modules.jobs_scheduler import service
from app.modules.jobs_scheduler.schema import SchedulerJobRunRead, TechnicalDocumentPipelineCreate, TechnicalDocumentPreviewRead, TechnicalDocumentRead, TechnicalDocumentSourceRead, WikiVersionCreate, WikiSourceUpdate
from app.modules.jobs_scheduler import technical_documents
from app.modules.chemicals_master.model import Chemical
from app.modules.system_management.model import User


router = APIRouter(prefix="/jobs", tags=["后台任务"])


@router.get('/chemical-wiki', summary='查询化学品百科目录')
def chemical_wiki_list(db: Session = Depends(get_db), user: User = Depends(require_permission('master.chemicals.read'))):
    technical_documents.require_technical_or_admin(db, user)
    from app.modules.jobs_scheduler import wiki_release
    try:
        return wiki_release.list_entries(wiki_release.DATA_ROOT)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=503, detail='百科资料不可用或配对异常') from exc


@router.get('/chemical-wiki/{source_id}', summary='查看化学品百科及原文')
def chemical_wiki_detail(source_id: int, db: Session = Depends(get_db),
                         user: User = Depends(require_permission('master.chemicals.read'))):
    technical_documents.require_technical_or_admin(db, user)
    from app.modules.jobs_scheduler import wiki_release, wiki_versions, wiki_source
    try:
        baseline = wiki_release.get_entry(wiki_release.DATA_ROOT, source_id)
        versions = wiki_versions.history(db, source_id)
        current = versions[0] if versions else None
        content = current.content if current else baseline
        return {**content, 'version': current.version if current else 0,
                'note': current.note if current else '',
                'source_status': wiki_source.current_source_status(db, content, wiki_release.DATA_ROOT)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='百科资料不存在') from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=503, detail='百科资料配对异常') from exc


@router.get('/chemical-wiki/{source_id}/versions', summary='查询化学品百科维护历史')
def chemical_wiki_version_history(source_id: int, db: Session = Depends(get_db),
                                  user: User = Depends(require_permission('master.chemicals.read'))):
    technical_documents.require_technical_or_admin(db, user)
    from app.modules.jobs_scheduler import wiki_release, wiki_versions
    try:
        wiki_release.get_entry(wiki_release.DATA_ROOT, source_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='百科资料不存在') from exc
    versions = wiki_versions.history(db, source_id)
    return [{'version': item.version, 'note': item.note, 'actor_id': item.actor_id,
             'created_at': item.created_at} for item in versions if item.version > 0]


@router.get('/chemical-wiki/{source_id}/versions/{version}', summary='查看百科历史版本')
def chemical_wiki_version_detail(source_id: int, version: int, db: Session = Depends(get_db),
                                 user: User = Depends(require_permission('master.chemicals.read'))):
    technical_documents.require_technical_or_admin(db, user)
    from app.modules.jobs_scheduler import wiki_release, wiki_versions, wiki_source
    try:
        baseline = wiki_release.get_entry(wiki_release.DATA_ROOT, source_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='百科资料不存在') from exc
    item = next((item for item in wiki_versions.history(db, source_id) if item.version == version), None)
    if version != 0 and item is None:
        raise HTTPException(status_code=404, detail='百科版本不存在')
    content = item.content if item else baseline
    return {**content, 'version': version, 'note': item.note if item else '',
            'source_status': wiki_source.current_source_status(db, content, wiki_release.DATA_ROOT)}


@router.get('/chemical-wiki/{source_id}/sources', summary='查询可用于更新的安全资料')
def chemical_wiki_sources(source_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_permission('master.chemicals.write'))):
    technical_documents.require_technical_or_admin(db, user)
    from app.modules.jobs_scheduler import wiki_release
    from app.modules.doc_kb.model import AiDocument
    try:
        baseline = wiki_release.get_entry(wiki_release.DATA_ROOT, source_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='百科资料不存在') from exc
    msds = baseline['msds']
    if msds.get('cas_valid_checksum') is not True:
        return []
    rows = db.scalars(select(AiDocument).where(AiDocument.cas_no == msds['cas_candidate'],
                      AiDocument.doc_type == 'msds', AiDocument.parse_status == 'PARSED').order_by(AiDocument.id)).all()
    return [{'id': row.id, 'title': row.title, 'cas_no': row.cas_no, 'object_key': row.object_key,
             'source_url': row.source_url, 'updated_at': row.updated_at} for row in rows]


@router.post('/chemical-wiki/{source_id}/source', summary='使用已入库的安全资料更新百科来源')
def chemical_wiki_update_source(source_id: int, data: WikiSourceUpdate, db: Session = Depends(get_db),
                                user: User = Depends(require_permission('master.chemicals.write'))):
    technical_documents.require_technical_or_admin(db, user)
    from app.modules.jobs_scheduler import wiki_release, wiki_versions, wiki_source
    try:
        baseline = wiki_release.get_entry(wiki_release.DATA_ROOT, source_id)
        versions = wiki_versions.history(db, source_id)
        current = versions[0] if versions else None
        document, sections = wiki_source.load_source(db, data.document_id, lock=True)
        if document is None:
            raise HTTPException(status_code=404, detail='原始资料不存在')
        pair = wiki_source.build_source_pair(current.content if current else baseline, document, sections)
        result = wiki_versions.create_version(db, source_id, data.expected_version, pair,
                                               current.note if current else '', actor_id=user.id, baseline=baseline)
        db.commit()
        return {'version': result.version}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='百科资料不存在') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/chemical-wiki/{source_id}/versions', summary='保存化学品百科维护说明')
def chemical_wiki_add_version(source_id: int, data: WikiVersionCreate, db: Session = Depends(get_db),
                              user: User = Depends(require_permission('master.chemicals.write'))):
    technical_documents.require_technical_or_admin(db, user)
    from app.modules.jobs_scheduler import wiki_release, wiki_versions
    try:
        baseline = wiki_release.get_entry(wiki_release.DATA_ROOT, source_id)
        versions = wiki_versions.history(db, source_id)
        pair = versions[0].content if versions else baseline
        if data.items is not None:
            from copy import deepcopy
            pair = deepcopy(pair)
            rows = {row['row']: row['cells'] for row in pair['msds']['rows']}
            sections = set(pair['technical']['sections'])
            items = []
            seen = set()
            for item in data.items:
                key = (item.source_row, item.source_cell)
                cells = rows.get(item.source_row, [])
                index = item.source_cell - 1
                if item.section not in sections or key in seen or index >= len(cells) or not cells[index].strip():
                    raise ValueError('资料字段或来源位置无效')
                seen.add(key)
                items.append({'section': item.section, 'text': cells[index], 'source_row': item.source_row, 'source_cell': item.source_cell})
            pair['technical']['items'] = items
        version = wiki_versions.create_version(db, source_id, data.expected_version, pair, data.note, actor_id=user.id, baseline=baseline)
        db.commit()
        return {'version': version.version, 'note': version.note}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='百科资料不存在') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.post("/technical-documents/fetch", response_model=SchedulerJobRunRead, summary="仅抓取并保存 TDS/MSDS 至 MinIO", dependencies=[Depends(limit_document)])
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
    return technical_documents.schedule_pipeline(db, user, data, background_tasks, "fetch")


@router.post("/technical-documents/ingest", response_model=SchedulerJobRunRead, summary="解析 MinIO 资料并写入结构化及向量知识库", dependencies=[Depends(limit_document)])
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
    return technical_documents.schedule_pipeline(db, user, data, background_tasks, "ingest")


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

    return service.run_manual_alert_scan(db, user)


@router.get("/alert-scan/status", summary="查看业务提醒扫描状态")
def alert_scan_status(request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("operations.exceptions.read"))):
    from app.core.config import get_settings
    settings = get_settings()
    task = getattr(request.app.state, "business_alert_scheduler_task", None)
    latest = service.latest_alert_run(db)
    return {
        "scheduler_enabled": settings.business_alerts_scheduler_enabled,
        "scheduler_running": task is not None and not task.done(),
        "interval_seconds": max(1, settings.overdue_scan_interval_seconds),
        "last_run": SchedulerJobRunRead.model_validate(latest).model_dump(mode="json") if latest else None,
    }


@router.get("/runs", response_model=list[SchedulerJobRunRead], summary="查询后台任务运行历史")
def list_job_runs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("operations.exceptions.read")),
) -> list[SchedulerJobRunRead]:
    """返回最近的后台扫描运行结果，不包含单据正文或个人数据。"""

    return service.list_job_runs(db, limit=limit)
