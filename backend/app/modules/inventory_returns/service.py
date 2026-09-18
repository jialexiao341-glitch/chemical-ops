"""供应商退货的状态流转和库存原子扣减。"""

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.deliveries.model import Delivery
from app.modules.inventory.model import InventoryBalance, InventoryBatch, InventoryTransaction, Warehouse, WarehouseLocation
from app.modules.inventory_returns.model import InventoryReturnItem, InventoryReturnRequest
from app.modules.inventory_returns.schema import ReturnCreate
from app.modules.inventory_cost.service import allocate_outbound_cost
from app.modules.products.model import Product
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_requests.model import Unit
from app.modules.suppliers.model import Supplier
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    """返回带时区的当前时间。"""
    return datetime.now(timezone.utc)


def _can_manage_all(db: Session, user: User) -> bool:
    """判断用户是否可以处理全部退货申请。"""
    return bool({"SYS_ADMIN", "PROCUREMENT_MANAGER", "WAREHOUSE"} & set(get_user_role_codes(db, user.id)))


def _require(db: Session, return_id: int, *, for_update: bool = False) -> InventoryReturnRequest:
    """查询退货申请及明细。"""
    statement = select(InventoryReturnRequest).options(selectinload(InventoryReturnRequest.items)).where(InventoryReturnRequest.id == return_id)
    if for_update:
        statement = statement.with_for_update()
    value = db.scalar(statement)
    if value is None:
        raise ResourceNotFoundError(f"退货申请 {return_id} 不存在")
    return value


def _validate_items(db: Session, data: ReturnCreate) -> None:
    """校验退货明细引用的主数据和库存位置。"""
    slots = set()
    for item in data.items:
        product = db.get(Product, item.product_id)
        warehouse = db.get(Warehouse, item.warehouse_id)
        location = db.get(WarehouseLocation, item.location_id)
        batch = db.get(InventoryBatch, item.batch_id)
        unit = db.get(Unit, item.unit_id)
        if product is None or product.status != "ACTIVE":
            raise BusinessValidationError(f"产品 {item.product_id} 不存在或已停用")
        if warehouse is None or warehouse.status != "ACTIVE":
            raise BusinessValidationError(f"仓库 {item.warehouse_id} 不存在或已停用")
        if location is None or location.status != "ACTIVE" or location.warehouse_id != warehouse.id:
            raise BusinessValidationError(f"库位 {item.location_id} 不存在、已停用或不属于指定仓库")
        if batch is None or batch.status != "ACTIVE" or batch.product_id != item.product_id:
            raise BusinessValidationError(f"库存批次 {item.batch_id} 不存在、不可用或不属于当前产品")
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError(f"计量单位 {item.unit_id} 不存在或已停用")
        slot = (item.warehouse_id, item.location_id, item.product_id, item.batch_id, item.unit_id)
        if slot in slots:
            raise BusinessValidationError("同一退货申请不能重复填写相同库存位置")
        slots.add(slot)


def create_return(db: Session, user: User, data: ReturnCreate) -> InventoryReturnRequest:
    """创建供应商退货草稿。"""
    supplier = db.get(Supplier, data.supplier_id)
    if supplier is None or supplier.status != "ACTIVE":
        raise BusinessValidationError("退货供应商不存在或已停用")
    if data.po_id is not None:
        order = db.get(PurchaseOrder, data.po_id)
        if order is None or order.supplier_id != data.supplier_id:
            raise BusinessValidationError("来源采购订单不存在或不属于指定供应商")
    if data.delivery_id is not None:
        delivery = db.get(Delivery, data.delivery_id)
        if delivery is None or delivery.supplier_id != data.supplier_id or (data.po_id is not None and delivery.po_id != data.po_id):
            raise BusinessValidationError("来源到货单不存在或与供应商、采购订单不匹配")
    _validate_items(db, data)
    value = InventoryReturnRequest(return_no=f"TEMP-IR-{uuid4().hex[:12]}", supplier_id=data.supplier_id, po_id=data.po_id, delivery_id=data.delivery_id, applicant_id=user.id, reason=data.reason, status="DRAFT")
    value.items = [InventoryReturnItem(line_no=i, **item.model_dump()) for i, item in enumerate(data.items, start=1)]
    db.add(value)
    db.flush()
    value.return_no = f"IR{date.today():%Y%m%d}{value.id:06d}"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="INVENTORY_RETURN_REQUEST", resource_id=value.id, request_summary="创建供应商退货申请", result_status="SUCCESS")
    db.commit()
    return _require(db, value.id)


def list_returns(db: Session, user: User, *, status: str | None, page: int, page_size: int):
    """分页查询退货申请。"""
    conditions = [] if _can_manage_all(db, user) else [InventoryReturnRequest.applicant_id == user.id]
    if status:
        conditions.append(InventoryReturnRequest.status == status)
    total = db.scalar(select(func.count(InventoryReturnRequest.id)).where(*conditions)) or 0
    items = list(db.scalars(select(InventoryReturnRequest).options(selectinload(InventoryReturnRequest.items)).where(*conditions).order_by(InventoryReturnRequest.id.desc()).offset((page - 1) * page_size).limit(page_size)).all())
    return items, total


def get_return(db: Session, user: User, return_id: int) -> InventoryReturnRequest:
    """查询退货详情并校验申请人数据范围。"""
    value = _require(db, return_id)
    if not _can_manage_all(db, user) and value.applicant_id != user.id:
        raise ResourceNotFoundError(f"退货申请 {return_id} 不存在")
    return value


def submit_return(db: Session, user: User, return_id: int) -> InventoryReturnRequest:
    """提交退货审批。"""
    value = get_return(db, user, return_id)
    if value.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的退货申请可以提交")
    value.status = "SUBMITTED"
    value.reject_reason = None
    db.commit()
    return _require(db, value.id)


def approve_return(db: Session, user: User, return_id: int) -> InventoryReturnRequest:
    """审批退货申请。"""
    value = _require(db, return_id, for_update=True)
    if value.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的退货申请可以审批")
    value.status = "APPROVED"
    value.approved_by = user.id
    value.approved_at = _now()
    db.commit()
    return _require(db, value.id)


def reject_return(db: Session, user: User, return_id: int, reason: str) -> InventoryReturnRequest:
    """驳回退货申请。"""
    value = _require(db, return_id, for_update=True)
    if value.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的退货申请可以驳回")
    value.status = "REJECTED"
    value.rejected_at = _now()
    value.reject_reason = reason
    db.commit()
    return _require(db, value.id)


def cancel_return(db: Session, user: User, return_id: int) -> InventoryReturnRequest:
    """取消草稿或驳回退货申请。"""
    value = get_return(db, user, return_id)
    if value.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的退货申请可以取消")
    value.status = "CANCELLED"
    value.cancelled_at = _now()
    db.commit()
    return _require(db, value.id)


def execute_return(db: Session, user: User, return_id: int) -> InventoryReturnRequest:
    """锁定退货申请和库存余额，原子执行库存退货出库。"""
    try:
        value = _require(db, return_id, for_update=True)
        if value.status != "APPROVED":
            raise BusinessValidationError("只有已审批的退货申请可以执行")
        for item in sorted(value.items, key=lambda x: (x.warehouse_id, x.location_id, x.product_id, x.batch_id, x.unit_id)):
            balance = db.scalar(select(InventoryBalance).where(InventoryBalance.warehouse_id == item.warehouse_id, InventoryBalance.location_id == item.location_id, InventoryBalance.product_id == item.product_id, InventoryBalance.batch_id == item.batch_id, InventoryBalance.unit_id == item.unit_id).with_for_update())
            if balance is None:
                raise BusinessValidationError(f"退货明细 {item.line_no} 没有对应库存余额")
            if balance.status != "AVAILABLE" or balance.quantity - balance.locked_quantity < item.requested_quantity:
                raise BusinessValidationError(f"退货明细 {item.line_no} 可用库存不足或已冻结")
            balance.quantity -= item.requested_quantity
            item.returned_quantity = item.requested_quantity
            item.status = "RETURNED"
            transaction = InventoryTransaction(transaction_no=f"TEMP-RET-{value.id}-{item.id}", transaction_type="OUTBOUND", warehouse_id=item.warehouse_id, location_id=item.location_id, product_id=item.product_id, batch_id=item.batch_id, unit_id=item.unit_id, quantity=item.requested_quantity, source_type="INVENTORY_RETURN", source_id=value.id, operator_id=user.id, note=value.reason)
            db.add(transaction)
            db.flush()
            transaction.transaction_no = f"IT{date.today():%Y%m%d}{transaction.id:06d}"
            allocate_outbound_cost(db, transaction, item.requested_quantity)
        value.status = "COMPLETED"
        value.completed_at = _now()
        add_audit_log(db, actor_id=user.id, action_type="OUTBOUND", resource_type="INVENTORY_RETURN_REQUEST", resource_id=value.id, request_summary="执行供应商退货出库", result_status="SUCCESS")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _require(db, value.id)
