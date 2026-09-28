"""质量验收的 HTTP 接口。"""

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from urllib.parse import quote
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.quality_acceptances import service
from app.modules.quality_acceptances import report_review
from app.modules.quality_acceptances.schema import QualityAcceptanceCreate, QualityAcceptancePage, QualityAcceptanceRead, QualityAcceptanceResult, QualityReportFile, QualityReportReview, QualityReportReviewRequest
from app.modules.files import service as file_service
from app.modules.files.schema import FileAttachmentCreate
from app.modules.system.model import User


router = APIRouter(prefix="/quality-acceptances", tags=["质量验收"])


@router.get("/{acceptance_id}/report-files", response_model=list[QualityReportFile], summary="查询验收报告")
def report_files(
    acceptance_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> list[QualityReportFile]:
    return report_review.list_report_files(db, user, acceptance_id)


@router.post("/{acceptance_id}/report-files", response_model=QualityReportFile, status_code=201, summary="上传验收报告")
async def upload_report_file(
    acceptance_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.write")),
) -> QualityReportFile:
    service.get_acceptance(db, user, acceptance_id)
    # 上传前按现有附件权限检查，避免文件已存储却无法关联。
    file_service.list_attachments(db, user, "QUALITY_ACCEPTANCE", acceptance_id, page=1, page_size=1)
    settings = file_service.get_settings()
    content = await file.read(settings.document_max_size_mb * 1024 * 1024 + 1)
    value = file_service.upload_file(db, user, file_name=file.filename or "", mime_type=file.content_type or "application/octet-stream", content=content, file_category="QUALITY_REPORT", access_level="INTERNAL")
    file_service.attach_file(db, user, value.id, FileAttachmentCreate(resource_type="QUALITY_ACCEPTANCE", resource_id=acceptance_id))
    return QualityReportFile(id=value.id, file_name=value.file_name, uploaded_at=value.uploaded_at)


@router.get("/{acceptance_id}/report-files/{file_id}/download", summary="下载验收报告")
def download_report_file(
    acceptance_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> Response:
    value, content = report_review.read_report_file(db, user, acceptance_id, file_id)
    return Response(content=content, media_type=value.mime_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(value.file_name)}"})


@router.post("/{acceptance_id}/report-review", response_model=QualityReportReview, summary="只读核对验收报告")
async def review_report(
    acceptance_id: int,
    data: QualityReportReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> QualityReportReview:
    return await report_review.review_report(db, user, acceptance_id, data.file_id)


@router.post("", response_model=QualityAcceptanceRead, status_code=status.HTTP_201_CREATED, summary="创建质量验收")
def create_acceptance(
    data: QualityAcceptanceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.write")),
) -> QualityAcceptanceRead:
    """为已收货到货单创建待检验记录。"""

    return service.create_acceptance(db, user, data)


@router.get("", response_model=QualityAcceptancePage, summary="分页查询质量验收")
def list_acceptances(
    acceptance_result: str | None = Query(default=None, alias="result", description="验收结果"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> QualityAcceptancePage:
    """按用户数据范围分页查询验收记录。"""

    items, total = service.list_acceptances(db, user, result=acceptance_result, page=page, page_size=page_size)
    return QualityAcceptancePage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{acceptance_id}", response_model=QualityAcceptanceRead, summary="查询质量验收详情")
def get_acceptance(
    acceptance_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> QualityAcceptanceRead:
    """查询一条质量验收记录。"""

    return service.get_acceptance(db, user, acceptance_id)


@router.post("/{acceptance_id}/result", response_model=QualityAcceptanceRead, summary="提交质量验收结果")
def submit_result(
    acceptance_id: int,
    data: QualityAcceptanceResult,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.write")),
) -> QualityAcceptanceRead:
    """提交检测结果并同步到货状态。"""

    return service.submit_result(db, user, acceptance_id, data)
