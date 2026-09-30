"""供应商退货 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.inventory_returns import service
from app.modules.inventory_returns.schema import ReturnCreate, ReturnPage, ReturnRead, ReturnReject, ReturnSourceRead
from app.modules.system.model import User


router = APIRouter(prefix="/inventory/returns", tags=["供应商退货"])


@router.post("", response_model=ReturnRead, status_code=status.HTTP_201_CREATED, summary="创建退货申请")
def create_return(data: ReturnCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.return.write"))) -> ReturnRead:
    """创建供应商退货草稿。"""
    return service.create_return(db, user, data)


@router.get("", response_model=ReturnPage, summary="分页查询退货申请")
def list_returns(return_status: str | None = Query(default=None, alias="status", pattern="^(DRAFT|SUBMITTED|APPROVED|REJECTED|CANCELLED|COMPLETED)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.return.read"))) -> ReturnPage:
    """按状态查询退货申请。"""
    items, total = service.list_returns(db, user, status=return_status, page=page, page_size=page_size)
    return ReturnPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/sources", response_model=list[ReturnSourceRead], summary="查询库存余额对应的可核对退货来源")
def list_return_sources(balance_id: int = Query(gt=0), db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.return.write"))):
    return service.list_return_sources(db, user, balance_id)


@router.get("/{return_id}", response_model=ReturnRead, summary="查询退货申请详情")
def get_return(return_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.return.read"))) -> ReturnRead:
    """查询退货申请详情。"""
    return service.get_return(db, user, return_id)


@router.post("/{return_id}/submit", response_model=ReturnRead, summary="提交退货申请")
def submit_return(return_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.return.write"))) -> ReturnRead:
    """提交退货审批。"""
    return service.submit_return(db, user, return_id)


@router.post("/{return_id}/approve", response_model=ReturnRead, summary="审批退货申请")
def approve_return(return_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.return.approve"))) -> ReturnRead:
    """审批退货申请。"""
    return service.approve_return(db, user, return_id)


@router.post("/{return_id}/reject", response_model=ReturnRead, summary="驳回退货申请")
def reject_return(return_id: int, data: ReturnReject, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.return.approve"))) -> ReturnRead:
    """驳回退货申请并保存原因。"""
    return service.reject_return(db, user, return_id, data.reason)


@router.post("/{return_id}/cancel", response_model=ReturnRead, summary="取消退货申请")
def cancel_return(return_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.return.write"))) -> ReturnRead:
    """取消草稿或已驳回退货申请。"""
    return service.cancel_return(db, user, return_id)


@router.post("/{return_id}/execute", response_model=ReturnRead, summary="执行退货出库")
def execute_return(return_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.return.write"))) -> ReturnRead:
    """锁定库存并执行供应商退货出库。"""
    return service.execute_return(db, user, return_id)
