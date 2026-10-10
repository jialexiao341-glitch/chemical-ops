"""质量验收的 HTTP 接口。"""

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from urllib.parse import quote
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.quality_acceptances import service
from app.modules.quality_acceptances import report_review
from app.modules.quality_acceptances.schema import QualityAcceptanceCreate, QualityAcceptancePage, QualityAcceptanceRead, QualityAcceptanceResult, QualityCorrectionAction, QualityCorrectionRead, QualityReportFile, QualityReportReview, QualityReportReviewRequest, QualityReportSummary, QualityReviewDecision, QualityReviewHistory, QualityReviewTarget
from app.modules.files import service as file_service
from app.modules.files.schema import FileAttachmentCreate
from app.modules.system.model import User
from app.modules.quality_acceptances.schema import QualityAssignmentOptions


router = APIRouter(prefix="/quality-acceptances", tags=["质量验收"])


@router.get("/assignment-options", response_model=QualityAssignmentOptions, summary="查询送检指派选项")
def assignment_options(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.assign")),
) -> QualityAssignmentOptions:
    return service.assignment_options(db)


@router.get("/{acceptance_id}/report-files", response_model=list[QualityReportFile], summary="查询验收报告")
def report_files(
    acceptance_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> list[QualityReportFile]:
    """列出当前用户可访问的验收单关联报告。"""
    return report_review.list_report_files(db, user, acceptance_id)


@router.get("/{acceptance_id}/review-targets", response_model=list[QualityReviewTarget], summary="查询可核对的到货明细")
def review_targets(
    acceptance_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> list[QualityReviewTarget]:
    """返回验收单可供报告核对的到货明细，供用户明确选择目标。"""
    return report_review.review_targets(db, user, acceptance_id)


@router.get("/{acceptance_id}/report-reviews", response_model=list[QualityReviewHistory], summary="查询报告核对历史")
def report_reviews(
    acceptance_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> list[QualityReviewHistory]:
    """按时间返回验收单的报告核对记录及人工复核状态。"""
    return report_review.list_review_history(db, user, acceptance_id)


@router.get("/{acceptance_id}/report-summary/{delivery_item_id}", response_model=QualityReportSummary, summary="汇总到货明细的多份报告")
def report_summary(
    acceptance_id: int,
    delivery_item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> QualityReportSummary:
    return report_review.summarize_reports(db, user, acceptance_id, delivery_item_id)


@router.get("/{acceptance_id}/report-reviews/{review_id}", response_model=QualityReportReview, summary="查询报告核对快照")
def report_review_detail(
    acceptance_id: int,
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> QualityReportReview:
    """读取一次核对时保存的结果快照，而非重新解析报告。"""
    return report_review.get_review_record(db, user, acceptance_id, review_id)


@router.post("/{acceptance_id}/report-reviews/{review_id}/decision", response_model=QualityReviewHistory, summary="记录人工复核意见")
def decide_report_review(
    acceptance_id: int,
    review_id: int,
    data: QualityReviewDecision,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.review")),
) -> QualityReviewHistory:
    """保存指定报告核对记录的人工结论和复核意见。"""
    return report_review.decide_review(db, user, acceptance_id, review_id, data)


@router.get("/{acceptance_id}/report-reviews/{review_id}/corrections", response_model=list[QualityCorrectionRead], summary="查询逐项修正记录")
def report_corrections(
    acceptance_id: int,
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> list[QualityCorrectionRead]:
    return report_review.list_corrections(db, user, acceptance_id, review_id)


@router.post("/{acceptance_id}/report-reviews/{review_id}/corrections", response_model=QualityCorrectionRead, summary="提交检测项修正说明")
def resolve_report_correction(
    acceptance_id: int,
    review_id: int,
    data: QualityCorrectionAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.write")),
) -> QualityCorrectionRead:
    return report_review.resolve_correction(db, user, acceptance_id, review_id, data)


@router.post("/{acceptance_id}/report-files", response_model=QualityReportFile, status_code=201, summary="上传验收报告")
async def upload_report_file(
    acceptance_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.write")),
) -> QualityReportFile:
    """校验验收单和附件权限后，上传并关联一份质量报告。"""
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
    """在验证报告所属验收单与读取权限后返回原始文件。"""
    value, content = report_review.read_report_file(db, user, acceptance_id, file_id)
    return Response(content=content, media_type=value.mime_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(value.file_name)}"})


@router.post("/{acceptance_id}/report-review", response_model=QualityReportReview, summary="只读核对验收报告")
async def review_report(
    acceptance_id: int,
    data: QualityReportReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.read")),
) -> QualityReportReview:
    """解析选定报告并生成核对快照；不直接提交验收结果。"""
    return await report_review.review_report(db, user, acceptance_id, data.file_id, data.delivery_item_id, data.standard_id)


@router.post("", response_model=QualityAcceptanceRead, status_code=status.HTTP_201_CREATED, summary="创建质量验收")
def create_acceptance(
    data: QualityAcceptanceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("quality.acceptances.assign")),
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
