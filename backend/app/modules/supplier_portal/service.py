"""供应商门户订单查询和供应商确认逻辑。"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderEvent
from app.modules.supplier_portal.model import SupplierPortalAccount
from app.modules.system.audit import add_audit_log
from app.modules.system.model import User


def _supplier_id(db: Session, user: User) -> int:
    """读取当前登录用户绑定的供应商。"""
    account = db.scalar(select(SupplierPortalAccount).where(SupplierPortalAccount.user_id == user.id, SupplierPortalAccount.status == "ACTIVE"))
    if account is None:
        raise AuthorizationError("当前用户未绑定有效的供应商门户账号")
    return account.supplier_id


def _require_order(db: Session, user: User, order_id: int, *, for_update: bool = False) -> PurchaseOrder:
    """查询供应商自己的采购订单。"""
    supplier_id = _supplier_id(db, user)
    statement = select(PurchaseOrder).options(selectinload(PurchaseOrder.items), selectinload(PurchaseOrder.approvals), selectinload(PurchaseOrder.events)).where(PurchaseOrder.id == order_id, PurchaseOrder.supplier_id == supplier_id)
    if for_update:
        statement = statement.with_for_update()
    order = db.scalar(statement)
    if order is None:
        raise ResourceNotFoundError(f"采购订单 {order_id} 不存在")
    return order


def list_orders(db: Session, user: User, *, status: str | None, page: int, page_size: int):
    """分页查询当前供应商的非草稿订单。"""
    supplier_id = _supplier_id(db, user)
    conditions = [PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.status != "DRAFT"]
    if status:
        conditions.append(PurchaseOrder.status == status)
    total = db.scalar(select(func.count(PurchaseOrder.id)).where(*conditions)) or 0
    items = list(db.scalars(select(PurchaseOrder).options(selectinload(PurchaseOrder.items), selectinload(PurchaseOrder.approvals), selectinload(PurchaseOrder.events)).where(*conditions).order_by(PurchaseOrder.id.desc()).offset((page - 1) * page_size).limit(page_size)).all())
    return items, total


def get_order(db: Session, user: User, order_id: int) -> PurchaseOrder:
    """查询供应商自己的订单详情。"""
    return _require_order(db, user, order_id)


def confirm_order(db: Session, user: User, order_id: int) -> PurchaseOrder:
    """供应商确认已正式下单的采购订单。"""
    order = _require_order(db, user, order_id, for_update=True)
    if order.status not in {"ORDERED", "PARTIAL", "COMPLETED"}:
        raise BusinessValidationError("只有已正式下单的采购订单可以由供应商确认")
    if order.supplier_confirmed_at is not None:
        raise BusinessValidationError("该采购订单已经完成供应商确认")
    order.supplier_confirmed_at = datetime.now(timezone.utc)
    order.events.append(PurchaseOrderEvent(operator_id=user.id, event_type="SUPPLIER_CONFIRMED", from_status=order.status, to_status=order.status, event_note="供应商确认采购订单"))
    add_audit_log(db, actor_id=user.id, action_type="CONFIRM", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary="供应商确认采购订单", result_status="SUCCESS")
    db.commit()
    return _require_order(db, user, order.id)


def reject_order(db: Session, user: User, order_id: int, reason: str) -> PurchaseOrder:
    """供应商拒绝采购订单并保留订单事件。"""
    order = _require_order(db, user, order_id, for_update=True)
    if order.status not in {"ORDERED", "PARTIAL", "COMPLETED"}:
        raise BusinessValidationError("只有已正式下单的采购订单可以由供应商拒绝")
    if order.supplier_confirmed_at is not None:
        raise BusinessValidationError("已确认的采购订单不能再拒绝")
    order.events.append(PurchaseOrderEvent(operator_id=user.id, event_type="SUPPLIER_REJECTED", from_status=order.status, to_status=order.status, event_note=reason))
    add_audit_log(db, actor_id=user.id, action_type="REJECT", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary=f"供应商拒绝采购订单：{reason}", result_status="SUCCESS")
    db.commit()
    return _require_order(db, user, order.id)
