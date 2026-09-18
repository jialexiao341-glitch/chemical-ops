"""质量验收的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.quality_acceptances import service
from app.modules.quality_acceptances.schema import QualityAcceptanceCreate, QualityAcceptancePage, QualityAcceptanceRead, QualityAcceptanceResult
from app.modules.system.model import User


router = APIRouter(prefix="/quality-acceptances", tags=["质量验收"])


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
