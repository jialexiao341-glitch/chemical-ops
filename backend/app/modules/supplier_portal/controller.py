"""供应商门户订单 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.supplier_portal import service
from app.modules.supplier_portal.schema import SupplierOrderPage, SupplierOrderReject
from app.modules.system.model import User
from app.modules.purchase_orders.schema import PurchaseOrderRead


router = APIRouter(prefix="/supplier-portal/orders", tags=["供应商门户"])


@router.get("", response_model=SupplierOrderPage, summary="查询供应商采购订单")
def list_orders(order_status: str | None = Query(default=None, alias="status"), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.read"))) -> SupplierOrderPage:
    """只返回当前供应商账号绑定供应商的非草稿采购订单。"""
    items, total = service.list_orders(db, user, status=order_status, page=page, page_size=page_size)
    return SupplierOrderPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{order_id}", response_model=PurchaseOrderRead, summary="查询供应商采购订单详情")
def get_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.read"))) -> PurchaseOrderRead:
    """查询当前供应商自己的采购订单。"""
    return service.get_order(db, user, order_id)


@router.post("/{order_id}/confirm", response_model=PurchaseOrderRead, summary="供应商确认采购订单")
def confirm_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.confirm"))) -> PurchaseOrderRead:
    """供应商确认正式下单的采购订单。"""
    return service.confirm_order(db, user, order_id)


@router.post("/{order_id}/reject", response_model=PurchaseOrderRead, summary="供应商拒绝采购订单")
def reject_order(order_id: int, data: SupplierOrderReject, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.confirm"))) -> PurchaseOrderRead:
    """供应商拒绝订单并保存原因。"""
    return service.reject_order(db, user, order_id, data.reason)
