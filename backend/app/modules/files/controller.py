"""文件上传、下载和附件关联 HTTP 接口。"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from urllib.parse import quote

from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.files import service
from app.modules.files.schema import FileAttachmentCreate, FileAttachmentPage, FileAttachmentRead, FileRead
from app.modules.system.model import User


router = APIRouter(prefix="/files", tags=["文件管理"])


@router.post("", response_model=FileRead, status_code=201, summary="上传文件")
async def upload_file(file: UploadFile = File(...), file_category: str = Form(default="OTHER", max_length=32), access_level: str = Form(default="INTERNAL"), db: Session = Depends(get_db), user: User = Depends(require_permission("system.files.write"))) -> FileRead:
    """校验文件类型和大小后写入开发环境本地对象存储。"""
    settings = service.get_settings()
    content = await file.read(settings.document_max_size_mb * 1024 * 1024 + 1)
    return service.upload_file(db, user, file_name=file.filename or "", mime_type=file.content_type or "application/octet-stream", content=content, file_category=file_category, access_level=access_level)


@router.get("/{file_id}", response_model=FileRead, summary="查询文件元数据")
def get_file(file_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("system.files.read"))) -> FileRead:
    """查询文件元数据，不直接暴露本地路径。"""
    return service.get_file(db, user, file_id)


@router.get("/{file_id}/download", summary="下载文件")
def download_file(file_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("system.files.download"))) -> Response:
    """校验文件对象存在后下载文件。"""
    value, content = service.read_file(db, user, file_id)
    return Response(content=content, media_type=value.mime_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(value.file_name)}"})


@router.post("/{file_id}/attachments", response_model=FileAttachmentRead, status_code=201, summary="关联业务附件")
def attach_file(file_id: int, data: FileAttachmentCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("system.files.attach"))) -> FileAttachmentRead:
    """将文件绑定到采购订单、到货单、异常或财务等业务资源。"""
    return service.attach_file(db, user, file_id, data)


@router.get("/attachments/{resource_type}/{resource_id}", response_model=FileAttachmentPage, summary="查询业务附件")
def list_attachments(resource_type: str, resource_id: int, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("system.files.read"))) -> FileAttachmentPage:
    """分页查询业务对象的附件关联。"""
    items, total = service.list_attachments(db, user, resource_type, resource_id, page=page, page_size=page_size)
    return FileAttachmentPage(items=items, total=total, page=page, page_size=page_size)
