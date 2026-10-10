"""供应商补货申请的状态流转。"""

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.products.model import Product
from app.modules.purchase_orders.service import get_order
from app.modules.deliveries.service import get_delivery
from app.modules.purchase_requests.model import Unit
from app.modules.replenishments.model import ReplenishmentItem, ReplenishmentRequest
from app.modules.replenishments.schema import ReplenishmentComplete, ReplenishmentCreate
from app.modules.suppliers.model import Supplier
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    """返回当前时间。"""
    return datetime.now(timezone.utc)


def _can_manage_all(db: Session, user: User) -> bool:
    """判断用户是否可以处理全部补货申请。"""
    return bool({"SYS_ADMIN", "PROCUREMENT_MANAGER"} & set(get_user_role_codes(db, user.id)))


def _require(db: Session, replenishment_id: int, *, for_update: bool = False) -> ReplenishmentRequest:
    """查询补货申请及明细。"""
    statement = select(ReplenishmentRequest).options(selectinload(ReplenishmentRequest.items)).where(ReplenishmentRequest.id == replenishment_id)
    if for_update:
        statement = statement.with_for_update()
    value = db.scalar(statement)
    if value is None:
        raise ResourceNotFoundError(f"补货申请 {replenishment_id} 不存在")
    return value


def create_replenishment(db: Session, user: User, data: ReplenishmentCreate) -> ReplenishmentRequest:
    """创建补货申请草稿。"""
    supplier = db.get(Supplier, data.supplier_id)
    if supplier is None or supplier.status != "ACTIVE":
        raise BusinessValidationError("补货供应商不存在或已停用")
    if data.source_po_id is not None:
        order = get_order(db, user, data.source_po_id)
        if order.supplier_id != data.supplier_id:
            raise BusinessValidationError("来源采购订单不存在或不属于指定供应商")
    if data.source_delivery_id is not None:
        delivery = get_delivery(db, user, data.source_delivery_id)
        get_order(db, user, delivery.po_id)
        if delivery.supplier_id != data.supplier_id or (data.source_po_id is not None and delivery.po_id != data.source_po_id):
            raise BusinessValidationError("来源到货单不存在或与供应商、采购订单不匹配")
    products = {item.product_id: db.get(Product, item.product_id) for item in data.items}
    units = {item.unit_id: db.get(Unit, item.unit_id) for item in data.items}
    for item in data.items:
        if products[item.product_id] is None or products[item.product_id].status != "ACTIVE":
            raise BusinessValidationError(f"产品 {item.product_id} 不存在或已停用")
        if units[item.unit_id] is None or units[item.unit_id].status != "ACTIVE":
            raise BusinessValidationError(f"计量单位 {item.unit_id} 不存在或已停用")
    value = ReplenishmentRequest(replenishment_no=f"TEMP-RP-{uuid4().hex[:12]}", supplier_id=data.supplier_id, source_po_id=data.source_po_id, source_delivery_id=data.source_delivery_id, applicant_id=user.id, reason=data.reason, status="DRAFT")
    value.items = [ReplenishmentItem(line_no=i, **item.model_dump()) for i, item in enumerate(data.items, start=1)]
    db.add(value)
    db.flush()
    value.replenishment_no = f"RP{date.today():%Y%m%d}{value.id:06d}"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="REPLENISHMENT_REQUEST", resource_id=value.id, request_summary="创建供应商补货申请", result_status="SUCCESS")
    db.commit()
    return _require(db, value.id)


def list_replenishments(db: Session, user: User, *, status: str | None, page: int, page_size: int):
    """分页查询补货申请。"""
    conditions = [] if _can_manage_all(db, user) else [ReplenishmentRequest.applicant_id == user.id]
    if status:
        conditions.append(ReplenishmentRequest.status == status)
    total = db.scalar(select(func.count(ReplenishmentRequest.id)).where(*conditions)) or 0
    items = list(db.scalars(select(ReplenishmentRequest).options(selectinload(ReplenishmentRequest.items)).where(*conditions).order_by(ReplenishmentRequest.id.desc()).offset((page - 1) * page_size).limit(page_size)).all())
    return items, total


def get_replenishment(db: Session, user: User, replenishment_id: int) -> ReplenishmentRequest:
    """查询补货详情。"""
    value = _require(db, replenishment_id)
    if not _can_manage_all(db, user) and value.applicant_id != user.id:
        raise ResourceNotFoundError(f"补货申请 {replenishment_id} 不存在")
    return value


def submit_replenishment(db: Session, user: User, replenishment_id: int) -> ReplenishmentRequest:
    """提交补货审批。"""
    value = get_replenishment(db, user, replenishment_id)
    if value.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的补货申请可以提交")
    value.status = "SUBMITTED"
    value.reject_reason = None
    db.commit()
    return _require(db, value.id)


def approve_replenishment(db: Session, user: User, replenishment_id: int) -> ReplenishmentRequest:
    """审批补货申请。"""
    value = _require(db, replenishment_id, for_update=True)
    if value.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的补货申请可以审批")
    if value.applicant_id == user.id:
        raise BusinessValidationError("不能审批本人经办的补货申请")
    value.status = "APPROVED"
    value.approved_by = user.id
    value.approved_at = _now()
    db.commit()
    return _require(db, value.id)


def reject_replenishment(db: Session, user: User, replenishment_id: int, reason: str) -> ReplenishmentRequest:
    """驳回补货申请。"""
    value = _require(db, replenishment_id, for_update=True)
    if value.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的补货申请可以驳回")
    if value.applicant_id == user.id:
        raise BusinessValidationError("不能审批本人经办的补货申请")
    value.status = "REJECTED"
    value.rejected_at = _now()
    value.reject_reason = reason
    db.commit()
    return _require(db, value.id)


def cancel_replenishment(db: Session, user: User, replenishment_id: int) -> ReplenishmentRequest:
    """取消草稿或驳回补货申请。"""
    value = get_replenishment(db, user, replenishment_id)
    if value.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的补货申请可以取消")
    value.status = "CANCELLED"
    value.cancelled_at = _now()
    db.commit()
    return _require(db, value.id)


def complete_replenishment(db: Session, user: User, replenishment_id: int, data: ReplenishmentComplete) -> ReplenishmentRequest:
    """将已审批补货申请关联到实际采购订单并标记完成。"""
    get_replenishment(db, user, replenishment_id)
    value = _require(db, replenishment_id, for_update=True)
    if value.status != "APPROVED":
        raise BusinessValidationError("只有已审批的补货申请可以完成")
    order = get_order(db, user, data.fulfillment_po_id)
    if order.supplier_id != value.supplier_id or order.status not in {"ORDERED", "PARTIAL", "COMPLETED"}:
        raise BusinessValidationError("实际补货采购订单不存在、不属于供应商或尚未正式下单")
    value.fulfillment_po_id = order.id
    value.status = "COMPLETED"
    value.completed_at = _now()
    for item in value.items:
        item.status = "FULFILLED"
    add_audit_log(db, actor_id=user.id, action_type="COMPLETE", resource_type="REPLENISHMENT_REQUEST", resource_id=value.id, request_summary="关联采购订单完成补货申请", result_status="SUCCESS")
    db.commit()
    return _require(db, value.id)
