"""供应商退货的状态流转和库存原子扣减。"""

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, case, exists, false, func, select, true
from sqlalchemy.orm import Session, selectinload

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.inventory.model import InventoryBalance, InventoryBatch, InventoryTransaction, Warehouse, WarehouseLocation
from app.modules.inventory_returns.model import InventoryReturnItem, InventoryReturnRequest
from app.modules.inventory_returns.schema import ReturnCreate, ReturnSourceRead
from app.modules.inventory import service as inventory_service
from app.modules.inventory_cost.service import allocate_outbound_cost
from app.modules.products.model import Product
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderItem
from app.modules.purchase_requests.model import Unit
from app.modules.suppliers.model import Supplier
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    """返回带时区的当前时间。"""
    return datetime.now(timezone.utc)


def _ensure_return_scope(db: Session, user: User, value: InventoryReturnRequest) -> None:
    """退货整单必须完全落在用户可见的仓库范围内。"""
    roles = set(get_user_role_codes(db, user.id))
    if db.scalar(select(InventoryReturnRequest.id).where(
        InventoryReturnRequest.id == value.id, _return_department_scope(user, roles)
    )) is None:
        raise ResourceNotFoundError(f"退货申请 {value.id} 不存在")
    if roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        return
    if "WAREHOUSE" in roles:
        for item in value.items:
            inventory_service._require_warehouse_scope(db, user, item.warehouse_id)
        return
    if value.applicant_id != user.id:
        raise ResourceNotFoundError(f"退货申请 {value.id} 不存在")


def _describe_items(db: Session, requests: list[InventoryReturnRequest]) -> None:
    items = [item for request in requests for item in request.items]
    products = {row.id:row.product_name for row in db.scalars(select(Product).where(Product.id.in_({item.product_id for item in items})))} if items else {}
    units = {row.id:row.unit_name for row in db.scalars(select(Unit).where(Unit.id.in_({item.unit_id for item in items})))} if items else {}
    delivery_numbers = dict(db.execute(select(DeliveryItem.id, Delivery.delivery_no).join(Delivery).where(DeliveryItem.id.in_({item.source_delivery_item_id for item in items if item.source_delivery_item_id}))).all()) if items else {}
    order_numbers = dict(db.execute(select(PurchaseOrderItem.id, PurchaseOrder.po_no).join(PurchaseOrder).where(PurchaseOrderItem.id.in_({item.source_po_item_id for item in items if item.source_po_item_id}))).all()) if items else {}
    for item in items:
        item.product_name = products.get(item.product_id)
        item.unit_name = units.get(item.unit_id)
        item.source_delivery_no = delivery_numbers.get(item.source_delivery_item_id)
        item.source_po_no = order_numbers.get(item.source_po_item_id)


def _require(db: Session, return_id: int, *, for_update: bool = False) -> InventoryReturnRequest:
    """查询退货申请及明细。"""
    statement = select(InventoryReturnRequest).options(selectinload(InventoryReturnRequest.items)).where(InventoryReturnRequest.id == return_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    value = db.scalar(statement)
    if value is None:
        raise ResourceNotFoundError(f"退货申请 {return_id} 不存在")
    _describe_items(db, [value])
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


def list_return_sources(db: Session, user: User, balance_id: int) -> list[ReturnSourceRead]:
    """只在库存批次记录的来源到货单内列出可核对明细，不猜测来源。"""
    balance = inventory_service._require_balance_for_user(db, user, balance_id)
    batch = db.get(InventoryBatch, balance.batch_id)
    if batch is None or batch.source_delivery_id is None:
        return []
    delivery = db.get(Delivery, batch.source_delivery_id)
    order = db.get(PurchaseOrder, delivery.po_id) if delivery else None
    supplier = db.get(Supplier, delivery.supplier_id) if delivery else None
    unit = db.get(Unit, balance.unit_id)
    if not delivery or not order or not supplier or not unit:
        return []
    rows = db.scalars(select(DeliveryItem).where(DeliveryItem.delivery_id == delivery.id, DeliveryItem.product_id == balance.product_id, DeliveryItem.unit_id == balance.unit_id)).all()
    results = []
    for row in rows:
        if (row.batch_no or f"{delivery.delivery_no}-{row.line_no}") != batch.batch_no:
            continue
        line = db.get(PurchaseOrderItem, row.po_item_id)
        if line is None:
            continue
        returned = db.scalar(select(func.coalesce(func.sum(InventoryReturnItem.returned_quantity), 0)).join(InventoryReturnRequest).where(InventoryReturnItem.source_delivery_item_id == row.id, InventoryReturnRequest.status == "COMPLETED")) or 0
        results.append(ReturnSourceRead(source_delivery_item_id=row.id, source_po_item_id=line.id, delivery_id=delivery.id, po_id=order.id, supplier_id=supplier.id, supplier_name=supplier.supplier_name, po_no=order.po_no, delivery_no=delivery.delivery_no, line_no=row.line_no, product_name=line.product_name_snapshot, batch_no=batch.batch_no, unit_name=unit.unit_name, received_quantity=row.actual_quantity, returned_quantity=returned))
    return results


def _validate_sources(db: Session, user: User, data: ReturnCreate, *, executing_id: int | None = None) -> None:
    """绑定来源并核对剩余收货量，执行时在来源订单锁内再次调用。"""
    for item in data.items:
        inventory_service._require_warehouse_scope(db, user, item.warehouse_id)
        batch = db.get(InventoryBatch, item.batch_id)
        if batch.supplier_id is not None and batch.supplier_id != data.supplier_id:
            raise BusinessValidationError("库存批次不属于退货供应商")
        if batch.source_delivery_id is not None:
            original = db.get(Delivery, batch.source_delivery_id)
            if original is None or original.supplier_id != data.supplier_id or (data.po_id is not None and original.po_id != data.po_id) or (data.delivery_id is not None and original.id != data.delivery_id):
                raise BusinessValidationError("退货主单的采购订单或到货来源与库存批次不匹配")
        source = db.get(DeliveryItem, item.source_delivery_item_id) if item.source_delivery_item_id else None
        if item.source_delivery_item_id and source is None:
            raise BusinessValidationError("来源到货明细不存在")
        if source is not None:
            delivery = db.get(Delivery, source.delivery_id)
            if (source.product_id != item.product_id or source.unit_id != item.unit_id or delivery.supplier_id != data.supplier_id
                    or (data.delivery_id is not None and delivery.id != data.delivery_id)
                    or (batch.source_delivery_id is not None and delivery.id != batch.source_delivery_id)
                    or (source.batch_no or f"{delivery.delivery_no}-{source.line_no}") != batch.batch_no):
                raise BusinessValidationError("来源到货明细与供应商、产品、单位或库存批次不匹配")
            if item.source_po_item_id is not None and item.source_po_item_id != source.po_item_id:
                raise BusinessValidationError("来源订单行与到货明细不匹配")
            item.source_po_item_id = source.po_item_id
        line = db.get(PurchaseOrderItem, item.source_po_item_id) if item.source_po_item_id else None
        if item.source_po_item_id and line is None:
            raise BusinessValidationError("来源订单行不存在")
        if line is None:
            continue  # 历史未关联退货仍可走库存流程，但不会自动分摊到财务行。
        order = db.get(PurchaseOrder, line.po_id)
        if (line.product_id != item.product_id or line.unit_id != item.unit_id or order.supplier_id != data.supplier_id
                or (data.po_id is not None and order.id != data.po_id)):
            raise BusinessValidationError("来源订单行与供应商、产品、单位或采购订单不匹配")
        if batch.source_delivery_id is not None:
            batch_delivery = db.get(Delivery, batch.source_delivery_id)
            if batch_delivery is None or batch_delivery.po_id != line.po_id or (data.delivery_id is not None and batch_delivery.id != data.delivery_id):
                raise BusinessValidationError("来源订单行与库存批次的到货单不匹配")
            matches = db.scalars(select(DeliveryItem).where(DeliveryItem.delivery_id == batch_delivery.id, DeliveryItem.po_item_id == line.id, DeliveryItem.product_id == item.product_id, DeliveryItem.unit_id == item.unit_id)).all()
            match = any((row.batch_no or f"{batch_delivery.delivery_no}-{row.line_no}") == batch.batch_no for row in matches)
            if source is None and not match:
                raise BusinessValidationError("库存批次没有属于来源订单行的到货明细")
        if source is not None:
            capacity = source.actual_quantity
            predicate = InventoryReturnItem.source_delivery_item_id == source.id
            current_total = sum(x.requested_quantity for x in data.items if x.source_delivery_item_id == source.id)
        else:
            capacity = db.scalar(select(func.coalesce(func.sum(DeliveryItem.actual_quantity), 0)).join(Delivery).where(DeliveryItem.po_item_id == line.id, Delivery.status.in_({"RECEIVED", "INSPECTING", "ACCEPTED", "EXCEPTION"}))) or 0
            predicate = InventoryReturnItem.source_po_item_id == line.id
            current_total = sum(x.requested_quantity for x in data.items if x.source_po_item_id == line.id)
        used_query = select(InventoryReturnItem.returned_quantity).join(InventoryReturnRequest).where(predicate, InventoryReturnRequest.status == "COMPLETED")
        if executing_id is not None:
            used_query = used_query.where(InventoryReturnRequest.id != executing_id)
        used = sum(db.scalars(used_query.with_for_update() if executing_id is not None else used_query), 0)
        if used + current_total > capacity:
            raise BusinessValidationError("累计退货数量不能超过来源已收货数量")
    # 到货明细级和订单行级来源可混用，仍须共同遵守订单行累计收货上限。
    for line_id in {item.source_po_item_id for item in data.items if item.source_po_item_id is not None}:
        capacity = db.scalar(select(func.coalesce(func.sum(DeliveryItem.actual_quantity), 0)).join(Delivery).where(DeliveryItem.po_item_id == line_id, Delivery.status != "IN_TRANSIT")) or 0
        used_query = select(InventoryReturnItem.returned_quantity).join(InventoryReturnRequest).where(InventoryReturnItem.source_po_item_id == line_id, InventoryReturnRequest.status == "COMPLETED")
        if executing_id is not None:
            used_query = used_query.where(InventoryReturnRequest.id != executing_id)
        used = sum(db.scalars(used_query.with_for_update() if executing_id is not None else used_query), 0)
        requested = sum(item.requested_quantity for item in data.items if item.source_po_item_id == line_id)
        if used + requested > capacity:
            raise BusinessValidationError("累计退货数量不能超过来源订单行已收货数量")


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
    _validate_sources(db, user, data)
    source_lines = [db.get(PurchaseOrderItem, item.source_po_item_id) for item in data.items if item.source_po_item_id]
    po_ids = {line.po_id for line in source_lines}
    delivery_ids = {db.get(DeliveryItem, item.source_delivery_item_id).delivery_id for item in data.items if item.source_delivery_item_id}
    if data.po_id is None and len(po_ids) == 1 and len(source_lines) == len(data.items):
        data.po_id = next(iter(po_ids))
    if data.delivery_id is None and len(delivery_ids) == 1 and all(item.source_delivery_item_id for item in data.items):
        data.delivery_id = next(iter(delivery_ids))
    value = InventoryReturnRequest(return_no=f"TEMP-IR-{uuid4().hex[:12]}", supplier_id=data.supplier_id, po_id=data.po_id, delivery_id=data.delivery_id, applicant_id=user.id, reason=data.reason, status="DRAFT")
    value.items = [InventoryReturnItem(line_no=i, **item.model_dump()) for i, item in enumerate(data.items, start=1)]
    db.add(value)
    db.flush()
    value.return_no = f"IR{date.today():%Y%m%d}{value.id:06d}"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="INVENTORY_RETURN_REQUEST", resource_id=value.id, request_summary="创建供应商退货申请", result_status="SUCCESS")
    db.commit()
    return _require(db, value.id)


def _return_department_scope(user: User, roles: set[str]):
    from app.modules.system.data_scope import department_scope_condition
    order_department = select(PurchaseOrder.department_id).where(PurchaseOrder.id == InventoryReturnRequest.po_id).scalar_subquery()
    delivery_department = select(PurchaseOrder.department_id).join(Delivery, Delivery.po_id == PurchaseOrder.id).where(Delivery.id == InventoryReturnRequest.delivery_id).scalar_subquery()
    applicant_department = select(User.department_id).where(User.id == InventoryReturnRequest.applicant_id).scalar_subquery()
    header_department = case((InventoryReturnRequest.po_id.is_not(None), order_department),
                             (InventoryReturnRequest.delivery_id.is_not(None), delivery_department),
                             else_=applicant_department)
    cap = department_scope_condition(user, roles, PurchaseOrder.department_id)
    out_of_scope_order = select(InventoryReturnItem.id).join(PurchaseOrderItem, PurchaseOrderItem.id == InventoryReturnItem.source_po_item_id).join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.po_id).where(
        InventoryReturnItem.return_request_id == InventoryReturnRequest.id, ~func.coalesce(cap, false()))
    out_of_scope_delivery = select(InventoryReturnItem.id).join(DeliveryItem, DeliveryItem.id == InventoryReturnItem.source_delivery_item_id).join(Delivery, Delivery.id == DeliveryItem.delivery_id).join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id).where(
        InventoryReturnItem.return_request_id == InventoryReturnRequest.id, ~func.coalesce(cap, false()))
    out_of_scope_batch = select(InventoryReturnItem.id).join(InventoryBatch, InventoryBatch.id == InventoryReturnItem.batch_id).join(Delivery, Delivery.id == InventoryBatch.source_delivery_id).join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id).where(
        InventoryReturnItem.return_request_id == InventoryReturnRequest.id, ~func.coalesce(cap, false()))
    return and_(department_scope_condition(user, roles, header_department), ~exists(out_of_scope_order), ~exists(out_of_scope_delivery), ~exists(out_of_scope_batch))


def return_read_condition(db: Session, user: User, *, roles: set[str] | None = None):
    """生成与退货详情一致的人员或仓库范围，供关联查询复用。"""
    roles = set(get_user_role_codes(db, user.id)) if roles is None else roles
    if roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        base = true()
    elif "WAREHOUSE" in roles:
        warehouse_ids = inventory_service.accessible_warehouse_ids(db, user) or set()
        if not warehouse_ids:
            base = false()
        else:
            outside_scope = select(InventoryReturnItem.id).where(
                InventoryReturnItem.return_request_id == InventoryReturnRequest.id,
                InventoryReturnItem.warehouse_id.not_in(warehouse_ids),
            )
            base = ~exists(outside_scope)
    else:
        base = InventoryReturnRequest.applicant_id == user.id
    return and_(base, _return_department_scope(user, roles))


def list_returns(db: Session, user: User, *, status: str | None, page: int, page_size: int):
    """分页查询退货申请。"""
    conditions = [return_read_condition(db, user)]
    if status:
        conditions.append(InventoryReturnRequest.status == status)
    total = db.scalar(select(func.count(InventoryReturnRequest.id)).where(*conditions)) or 0
    items = list(db.scalars(select(InventoryReturnRequest).options(selectinload(InventoryReturnRequest.items)).where(*conditions).order_by(InventoryReturnRequest.id.desc()).offset((page - 1) * page_size).limit(page_size)).all())
    _describe_items(db, items)
    return items, total


def get_return(db: Session, user: User, return_id: int) -> InventoryReturnRequest:
    """查询退货详情并校验申请人数据范围。"""
    value = _require(db, return_id)
    _ensure_return_scope(db, user, value)
    return value


def _lock_source_orders(db: Session, value: InventoryReturnRequest) -> None:
    """统一先锁来源订单，再锁退货主单，与对账确认互斥。"""
    identifiers = {db.get(PurchaseOrderItem, item.source_po_item_id).po_id for item in value.items if item.source_po_item_id is not None}
    if value.po_id:
        identifiers.add(value.po_id)
    deliveries = {db.get(InventoryBatch, item.batch_id).source_delivery_id for item in value.items}
    if value.delivery_id:
        deliveries.add(value.delivery_id)
    identifiers.update(db.scalars(select(Delivery.po_id).where(Delivery.id.in_([identifier for identifier in deliveries if identifier]))))
    for identifier in sorted(identifiers):
        db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == identifier).with_for_update())


def submit_return(db: Session, user: User, return_id: int) -> InventoryReturnRequest:
    """提交退货审批。"""
    value = get_return(db, user, return_id)
    _lock_source_orders(db, value)
    value = _require(db, return_id, for_update=True)
    if value.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的退货申请可以提交")
    value.status = "SUBMITTED"
    value.reject_reason = None
    db.commit()
    return _require(db, value.id)


def approve_return(db: Session, user: User, return_id: int) -> InventoryReturnRequest:
    """审批退货申请。"""
    _lock_source_orders(db, get_return(db, user, return_id))
    value = _require(db, return_id, for_update=True)
    _ensure_return_scope(db, user, value)
    if value.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的退货申请可以审批")
    if value.applicant_id == user.id:
        raise BusinessValidationError("不能审批本人经办的退货申请")
    value.status = "APPROVED"
    value.approved_by = user.id
    value.approved_at = _now()
    db.commit()
    return _require(db, value.id)


def reject_return(db: Session, user: User, return_id: int, reason: str) -> InventoryReturnRequest:
    """驳回退货申请。"""
    _lock_source_orders(db, get_return(db, user, return_id))
    value = _require(db, return_id, for_update=True)
    _ensure_return_scope(db, user, value)
    if value.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的退货申请可以驳回")
    if value.applicant_id == user.id:
        raise BusinessValidationError("不能审批本人经办的退货申请")
    value.status = "REJECTED"
    value.rejected_at = _now()
    value.reject_reason = reason
    db.commit()
    return _require(db, value.id)


def cancel_return(db: Session, user: User, return_id: int) -> InventoryReturnRequest:
    """取消草稿或驳回退货申请。"""
    value = get_return(db, user, return_id)
    _lock_source_orders(db, value)
    value = _require(db, return_id, for_update=True)
    if value.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的退货申请可以取消")
    value.status = "CANCELLED"
    value.cancelled_at = _now()
    db.commit()
    return _require(db, value.id)


def execute_return(db: Session, user: User, return_id: int) -> InventoryReturnRequest:
    """锁定退货申请和库存余额，原子执行库存退货出库。"""
    try:
        value = get_return(db, user, return_id)
        if value.status != "APPROVED":
            raise BusinessValidationError("只有已审批的退货申请可以执行")
        _lock_source_orders(db, value)
        value = _require(db, return_id, for_update=True)
        _ensure_return_scope(db, user, value)
        if value.status != "APPROVED":
            raise BusinessValidationError("只有已审批的退货申请可以执行")
        payload = ReturnCreate(supplier_id=value.supplier_id, po_id=value.po_id, delivery_id=value.delivery_id, reason=value.reason, items=[{key: getattr(item, key) for key in ("product_id", "warehouse_id", "location_id", "batch_id", "unit_id", "requested_quantity", "source_delivery_item_id", "source_po_item_id")} for item in value.items])
        _validate_items(db, payload)
        _validate_sources(db, user, payload, executing_id=value.id)
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
