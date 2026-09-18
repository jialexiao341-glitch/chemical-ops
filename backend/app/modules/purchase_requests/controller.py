"""采购申请与审批的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.purchase_requests import service
from app.modules.purchase_requests.schema import (
    ApprovalAction,
    CancelAction,
    PurchaseRequestCreate,
    PurchaseRequestPage,
    PurchaseRequestRead,
    PurchaseRequestUpdate,
)
from app.modules.system.model import User


router = APIRouter(prefix="/purchase-requests", tags=["采购申请"])


@router.post("", response_model=PurchaseRequestRead, status_code=status.HTTP_201_CREATED, summary="创建采购申请")
def create_request(
    data: PurchaseRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.requests.write")),
) -> PurchaseRequestRead:
    """创建采购申请草稿。"""

    return service.create_request(db, user, data)


@router.get("", response_model=PurchaseRequestPage, summary="分页查询采购申请")
def list_requests(
    keyword: str | None = Query(default=None, description="按申请编号或用途查询"),
    request_status: str | None = Query(default=None, alias="status", description="申请状态"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.requests.read")),
) -> PurchaseRequestPage:
    """按用户数据范围分页查询采购申请。"""

    items, total = service.list_requests(
        db, user, keyword=keyword, status=request_status, page=page, page_size=page_size
    )
    return PurchaseRequestPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{request_id}", response_model=PurchaseRequestRead, summary="查询采购申请详情")
def get_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.requests.read")),
) -> PurchaseRequestRead:
    """查询采购申请、明细和审批记录。"""

    return service.get_request(db, user, request_id)


@router.patch("/{request_id}", response_model=PurchaseRequestRead, summary="更新采购申请")
def update_request(
    request_id: int,
    data: PurchaseRequestUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.requests.write")),
) -> PurchaseRequestRead:
    """更新草稿或已驳回的采购申请。"""

    return service.update_request(db, user, request_id, data)


@router.post("/{request_id}/submit", response_model=PurchaseRequestRead, summary="提交采购申请")
def submit_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.requests.write")),
) -> PurchaseRequestRead:
    """提交采购申请并进入审批中状态。"""

    return service.submit_request(db, user, request_id)


@router.post("/{request_id}/approve", response_model=PurchaseRequestRead, summary="审批通过采购申请")
def approve_request(
    request_id: int,
    data: ApprovalAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.requests.approve")),
) -> PurchaseRequestRead:
    """审批通过采购申请。"""

    return service.act_on_request(db, user, request_id, data, "APPROVED")


@router.post("/{request_id}/reject", response_model=PurchaseRequestRead, summary="驳回采购申请")
def reject_request(
    request_id: int,
    data: ApprovalAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.requests.approve")),
) -> PurchaseRequestRead:
    """驳回采购申请并保留审批意见。"""

    return service.act_on_request(db, user, request_id, data, "REJECTED")


@router.post("/{request_id}/cancel", response_model=PurchaseRequestRead, summary="取消采购申请")
def cancel_request(
    request_id: int,
    data: CancelAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.requests.write")),
) -> PurchaseRequestRead:
    """取消草稿或已驳回的采购申请。"""

    return service.cancel_request(db, user, request_id, data)
