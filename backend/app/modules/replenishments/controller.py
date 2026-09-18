"""供应商补货申请 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.replenishments import service
from app.modules.replenishments.schema import ReplenishmentComplete, ReplenishmentCreate, ReplenishmentPage, ReplenishmentRead, ReplenishmentReject
from app.modules.system.model import User


router = APIRouter(prefix="/replenishments", tags=["供应商补货"])


@router.post("", response_model=ReplenishmentRead, status_code=status.HTTP_201_CREATED, summary="创建补货申请")
def create_replenishment(data: ReplenishmentCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("procurement.replenishment.write"))) -> ReplenishmentRead:
    """创建供应商补货草稿。"""
    return service.create_replenishment(db, user, data)


@router.get("", response_model=ReplenishmentPage, summary="分页查询补货申请")
def list_replenishments(replenishment_status: str | None = Query(default=None, alias="status", pattern="^(DRAFT|SUBMITTED|APPROVED|REJECTED|CANCELLED|COMPLETED)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("procurement.replenishment.read"))) -> ReplenishmentPage:
    """按状态查询补货申请。"""
    items, total = service.list_replenishments(db, user, status=replenishment_status, page=page, page_size=page_size)
    return ReplenishmentPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{replenishment_id}", response_model=ReplenishmentRead, summary="查询补货申请详情")
def get_replenishment(replenishment_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("procurement.replenishment.read"))) -> ReplenishmentRead:
    """查询补货申请详情。"""
    return service.get_replenishment(db, user, replenishment_id)


@router.post("/{replenishment_id}/submit", response_model=ReplenishmentRead, summary="提交补货申请")
def submit_replenishment(replenishment_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("procurement.replenishment.write"))) -> ReplenishmentRead:
    """提交补货审批。"""
    return service.submit_replenishment(db, user, replenishment_id)


@router.post("/{replenishment_id}/approve", response_model=ReplenishmentRead, summary="审批补货申请")
def approve_replenishment(replenishment_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("procurement.replenishment.approve"))) -> ReplenishmentRead:
    """审批补货申请。"""
    return service.approve_replenishment(db, user, replenishment_id)


@router.post("/{replenishment_id}/reject", response_model=ReplenishmentRead, summary="驳回补货申请")
def reject_replenishment(replenishment_id: int, data: ReplenishmentReject, db: Session = Depends(get_db), user: User = Depends(require_permission("procurement.replenishment.approve"))) -> ReplenishmentRead:
    """驳回补货申请并保存原因。"""
    return service.reject_replenishment(db, user, replenishment_id, data.reason)


@router.post("/{replenishment_id}/cancel", response_model=ReplenishmentRead, summary="取消补货申请")
def cancel_replenishment(replenishment_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("procurement.replenishment.write"))) -> ReplenishmentRead:
    """取消草稿或已驳回补货申请。"""
    return service.cancel_replenishment(db, user, replenishment_id)


@router.post("/{replenishment_id}/complete", response_model=ReplenishmentRead, summary="完成补货申请")
def complete_replenishment(replenishment_id: int, data: ReplenishmentComplete, db: Session = Depends(get_db), user: User = Depends(require_permission("procurement.replenishment.write"))) -> ReplenishmentRead:
    """关联实际采购订单并完成补货申请。"""
    return service.complete_replenishment(db, user, replenishment_id, data)
