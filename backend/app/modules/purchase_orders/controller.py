"""采购订单的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.purchase_orders import service
from app.modules.purchase_orders import followup_service
from app.modules.purchase_orders.followup_schema import FollowupPage, FollowupRead, FollowupSend
from app.modules.purchase_orders.schema import (
    PurchaseOrderApprovalAction,
    PurchaseOrderCancelAction,
    PurchaseOrderCreate,
    PurchaseOrderPage,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
)
from app.modules.system.model import User


router = APIRouter(prefix="/purchase-orders", tags=["采购订单"])


@router.get('/followups/{followup_id}', response_model=FollowupRead, summary='读取授权催办及订单引用')
def resolve_followup(followup_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission('procurement.orders.read'))):
    return followup_service.resolve_followup(db, user, followup_id)


@router.get('/{order_id}/followups', response_model=FollowupPage, summary='查询订单催办历史')
def list_followups(order_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   db: Session = Depends(get_db), user: User = Depends(require_permission('procurement.orders.read'))):
    return followup_service.list_followups(db, user, order_id, page=page, page_size=page_size)


@router.post('/{order_id}/followups', response_model=FollowupRead, summary='确认向供应商门户发送已保存催办')
def send_followup(order_id: int, data: FollowupSend, db: Session = Depends(get_db),
                  user: User = Depends(require_permission('procurement.orders.write'))):
    return followup_service.send_followup(db, user, order_id, data)


@router.post("", response_model=PurchaseOrderRead, status_code=status.HTTP_201_CREATED, summary="生成采购订单")
def create_order(
    data: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.orders.write")),
) -> PurchaseOrderRead:
    """根据已确认的中选报价生成采购订单草稿。"""

    return service.create_order(db, user, data)


@router.get("", response_model=PurchaseOrderPage, summary="分页查询采购订单")
def list_orders(
    keyword: str | None = Query(default=None, description="按订单编号查询"),
    order_status: str | None = Query(default=None, alias="status", description="订单状态"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.orders.read")),
) -> PurchaseOrderPage:
    """按用户数据范围分页查询采购订单。"""

    items, total = service.list_orders(db, user, keyword=keyword, status=order_status, page=page, page_size=page_size)
    return PurchaseOrderPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{order_id}", response_model=PurchaseOrderRead, summary="查询采购订单详情")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.orders.read")),
) -> PurchaseOrderRead:
    """查询采购订单、明细、审批和事件。"""

    return service.read_order(db, user, order_id)


@router.patch("/{order_id}", response_model=PurchaseOrderRead, summary="更新采购订单草稿")
def update_order(
    order_id: int,
    data: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.orders.write")),
) -> PurchaseOrderRead:
    """更新草稿状态的采购订单。"""

    return service.update_order(db, user, order_id, data)


@router.post("/{order_id}/submit", response_model=PurchaseOrderRead, summary="提交采购订单审批")
def submit_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.orders.write")),
) -> PurchaseOrderRead:
    """提交订单并创建采购经理审批节点。"""

    return service.submit_order(db, user, order_id)


@router.post("/{order_id}/approve", response_model=PurchaseOrderRead, summary="审批通过采购订单")
def approve_order(
    order_id: int,
    data: PurchaseOrderApprovalAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.orders.approve")),
) -> PurchaseOrderRead:
    """审批通过采购订单。"""

    return service.act_on_order(db, user, order_id, data, "APPROVED")


@router.post("/{order_id}/reject", response_model=PurchaseOrderRead, summary="驳回采购订单")
def reject_order(
    order_id: int,
    data: PurchaseOrderApprovalAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.orders.approve")),
) -> PurchaseOrderRead:
    """驳回采购订单并保留审批意见。"""

    return service.act_on_order(db, user, order_id, data, "DRAFT")


@router.post("/{order_id}/place", response_model=PurchaseOrderRead, summary="正式下单")
def place_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.orders.write")),
) -> PurchaseOrderRead:
    """将已审批采购订单置为已下单，并回写采购申请数量。"""

    return service.place_order(db, user, order_id)


@router.post("/{order_id}/cancel", response_model=PurchaseOrderRead, summary="取消采购订单")
def cancel_order(
    order_id: int,
    data: PurchaseOrderCancelAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.orders.write")),
) -> PurchaseOrderRead:
    """取消尚未正式下单的采购订单。"""

    return service.cancel_order(db, user, order_id, data)
