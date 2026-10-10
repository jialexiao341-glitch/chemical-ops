"""仓库、批次、库存入库和库存流水的业务逻辑。"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.deliveries.model import Delivery
from app.modules.inventory import crud
from app.modules.inventory.model import (
    InventoryBalance,
    InventoryBalanceStatusLog,
    InventoryBatch,
    InventoryIssueItem,
    InventoryIssueRequest,
    InventoryTransaction,
    InventoryTransferItem,
    InventoryTransferRequest,
    InventoryStocktakeItem,
    InventoryStocktakeRequest,
    Warehouse,
    WarehouseLocation,
)
from app.modules.inventory.schema import (
    InboundCreate,
    InventoryIssueRequestCreate,
    InventoryIssueRequestUpdate,
    InventoryTransferRequestCreate,
    InventoryTransferRequestUpdate,
    InventoryStocktakeRequestCreate,
    InventoryStocktakeRequestUpdate,
    InventoryBalanceStatusChange,
    LocationCreate,
    WarehouseCreate,
)
from app.modules.inventory_cost.model import InventoryCostLayer
from app.modules.inventory_cost.service import allocate_outbound_cost
from app.modules.products.model import Product
from app.modules.purchase_orders.model import PurchaseOrderItem
from app.modules.purchase_requests.model import Unit
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import Department, User


def _now() -> datetime:
    """返回带时区的当前时间。"""

    return datetime.now(timezone.utc)


def _can_access_warehouse(db: Session, user: User, warehouse_id: int) -> bool:
    """按仓库负责人限制非管理员的数据范围；未配置负责人时保持兼容。"""
    roles = set(get_user_role_codes(db, user.id))
    if roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        return True
    warehouse = db.get(Warehouse, warehouse_id)
    return warehouse is not None and (warehouse.manager_id is None or warehouse.manager_id == user.id)


def _require_warehouse_scope(db: Session, user: User, warehouse_id: int) -> None:
    if not _can_access_warehouse(db, user, warehouse_id):
        raise ResourceNotFoundError(f"仓库 {warehouse_id} 不存在")


def _require_balance_for_user(db: Session, user: User, balance_id: int, *, for_update: bool = False) -> InventoryBalance:
    """读取库存余额并校验当前用户的仓库数据范围。"""
    balance = crud.get_balance_by_id(db, balance_id, for_update=for_update)
    if balance is None:
        raise ResourceNotFoundError(f"库存余额 {balance_id} 不存在")
    _require_warehouse_scope(db, user, balance.warehouse_id)
    return balance

def accessible_warehouse_ids(db: Session, user: User) -> set[int] | None:
    roles = set(get_user_role_codes(db, user.id))
    if roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        return None
    return {value.id for value in db.scalars(select(Warehouse).where(Warehouse.status == "ACTIVE", (Warehouse.manager_id == user.id) | Warehouse.manager_id.is_(None))).all()}

def create_warehouse(db: Session, user: User, data: WarehouseCreate) -> Warehouse:
    """创建仓库主数据。"""

    if db.scalar(select(Warehouse).where(Warehouse.warehouse_code == data.warehouse_code)):
        raise DuplicateResourceError(f"仓库编码 {data.warehouse_code} 已存在")
    warehouse = Warehouse(**data.model_dump())
    db.add(warehouse)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="WAREHOUSE", resource_id=warehouse.id, request_summary="创建仓库", result_status="SUCCESS")
    db.commit()
    db.refresh(warehouse)
    return warehouse


def create_location(db: Session, user: User, warehouse_id: int, data: LocationCreate) -> WarehouseLocation:
    """为仓库创建库位。"""

    warehouse = crud.get_warehouse(db, warehouse_id)
    if warehouse is None or warehouse.status != "ACTIVE":
        raise ResourceNotFoundError("仓库不存在或已停用")
    _require_warehouse_scope(db, user, warehouse_id)
    if db.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == warehouse_id, WarehouseLocation.location_code == data.location_code)):
        raise DuplicateResourceError(f"库位编码 {data.location_code} 已存在")
    location = WarehouseLocation(warehouse_id=warehouse_id, **data.model_dump())
    db.add(location)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="WAREHOUSE_LOCATION", resource_id=location.id, request_summary="创建仓库库位", result_status="SUCCESS")
    db.commit()
    db.refresh(location)
    return location


def list_warehouses(db: Session, user: User | None = None) -> list[Warehouse]:
    """查询启用仓库。"""

    statement = select(Warehouse).where(Warehouse.status == "ACTIVE")
    if user is not None and not (set(get_user_role_codes(db, user.id)) & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}):
        statement = statement.where((Warehouse.manager_id == user.id) | Warehouse.manager_id.is_(None))
    return list(db.scalars(statement.order_by(Warehouse.id)).all())


def list_locations(db: Session, warehouse_id: int, user: User | None = None) -> list[WarehouseLocation]:
    """查询仓库启用库位。"""

    if crud.get_warehouse(db, warehouse_id) is None:
        raise ResourceNotFoundError("仓库不存在")
    if user is not None:
        _require_warehouse_scope(db, user, warehouse_id)
    return list(db.scalars(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == warehouse_id, WarehouseLocation.status == "ACTIVE").order_by(WarehouseLocation.id)).all())


def freeze_balance(db: Session, user: User, balance_id: int, data: InventoryBalanceStatusChange) -> InventoryBalance:
    """锁定库存余额，冻结不改变数量。"""

    try:
        balance = _require_balance_for_user(db, user, balance_id, for_update=True)
        if balance.status == "FROZEN":
            raise BusinessValidationError("库存余额已经冻结")
        if balance.status != "AVAILABLE":
            raise BusinessValidationError("只有可用库存余额可以冻结")
        if balance.locked_quantity > 0:
            raise BusinessValidationError("存在已锁定库存，暂不能冻结该库存余额")
        previous_status = balance.status
        balance.status = "FROZEN"
        db.add(InventoryBalanceStatusLog(balance_id=balance.id, previous_status=previous_status, new_status="FROZEN", reason=data.reason, operator_id=user.id))
        add_audit_log(db, actor_id=user.id, action_type="FREEZE", resource_type="INVENTORY_BALANCE", resource_id=balance.id, request_summary="冻结库存余额", result_status="SUCCESS")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return crud.get_balance_by_id(db, balance_id)


def unfreeze_balance(db: Session, user: User, balance_id: int, data: InventoryBalanceStatusChange) -> InventoryBalance:
    """解冻库存余额，恢复为可用状态。"""

    try:
        balance = _require_balance_for_user(db, user, balance_id, for_update=True)
        if balance.status != "FROZEN":
            raise BusinessValidationError("只有已冻结库存余额可以解冻")
        balance.status = "AVAILABLE"
        db.add(InventoryBalanceStatusLog(balance_id=balance.id, previous_status="FROZEN", new_status="AVAILABLE", reason=data.reason, operator_id=user.id))
        add_audit_log(db, actor_id=user.id, action_type="UNFREEZE", resource_type="INVENTORY_BALANCE", resource_id=balance.id, request_summary="解冻库存余额", result_status="SUCCESS")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return crud.get_balance_by_id(db, balance_id)


def list_balance_status_logs(db: Session, user: User, balance_id: int, *, page: int, page_size: int):
    """查询库存余额冻结和解冻历史。"""

    _require_balance_for_user(db, user, balance_id)
    return crud.list_balance_status_logs(db, balance_id, page=page, page_size=page_size)


def create_inbound(db: Session, user: User, data: InboundCreate):
    """将已通过质量验收的到货单执行入库。"""

    # 锁住到货主单，避免同一到货单被并发重复入库。
    delivery = db.scalar(select(Delivery).where(Delivery.id == data.delivery_id).with_for_update())
    if delivery is None:
        raise ResourceNotFoundError("到货单不存在")
    # 入库必须同时满足目标仓库范围和到货单来源订单范围。
    # warehouse.inventory.write 本身不应允许把任意跨域到货单写入授权仓库。
    from app.modules.purchase_orders.service import read_order

    read_order(db, user, delivery.po_id)
    if delivery.status != "ACCEPTED":
        raise BusinessValidationError("只有质量验收通过的到货单可以入库")
    _require_warehouse_scope(db, user, data.warehouse_id)
    warehouse = crud.get_warehouse(db, data.warehouse_id)
    location = crud.get_location(db, data.location_id)
    if warehouse is None or warehouse.status != "ACTIVE":
        raise BusinessValidationError("仓库不存在或已停用")
    if location is None or location.status != "ACTIVE" or location.warehouse_id != warehouse.id:
        raise BusinessValidationError("库位不存在、已停用或不属于指定仓库")
    if not delivery.items:
        raise BusinessValidationError("到货单没有可入库明细")
    transactions = []
    balances = []
    for delivery_item in delivery.items:
        if delivery_item.actual_quantity <= 0:
            continue
        if crud.get_transaction_by_delivery_item(db, delivery_item.id) is not None:
            raise BusinessValidationError(f"到货明细 {delivery_item.line_no} 已经完成入库")
        batch_no = delivery_item.batch_no or f"{delivery.delivery_no}-{delivery_item.line_no}"
        batch = crud.get_batch(db, delivery_item.product_id, batch_no, delivery.id)
        if batch is None:
            batch = InventoryBatch(
                product_id=delivery_item.product_id,
                batch_no=batch_no,
                supplier_id=delivery.supplier_id,
                source_delivery_id=delivery.id,
                production_date=delivery_item.production_date,
                expiry_date=delivery_item.expiry_date,
                status="ACTIVE",
            )
            db.add(batch)
            db.flush()
        balance = crud.ensure_balance_for_update(
            db,
            warehouse.id,
            location.id,
            delivery_item.product_id,
            batch.id,
            delivery_item.unit_id,
        )
        if balance is None:
            raise BusinessValidationError("库存余额创建失败，请稍后重试")
        balance.quantity += delivery_item.actual_quantity
        transaction = InventoryTransaction(
            transaction_no=f"TEMP-IT-{user.id}-{delivery_item.id}",
            transaction_type="INBOUND",
            warehouse_id=warehouse.id,
            location_id=location.id,
            product_id=delivery_item.product_id,
            batch_id=batch.id,
            unit_id=delivery_item.unit_id,
            quantity=delivery_item.actual_quantity,
            delivery_item_id=delivery_item.id,
            source_type="DELIVERY",
            source_id=delivery.id,
            operator_id=user.id,
            note=data.note,
        )
        db.add(transaction)
        db.flush()
        transaction.transaction_no = f"IT{date.today():%Y%m%d}{transaction.id:06d}"
        po_item = db.get(PurchaseOrderItem, delivery_item.po_item_id)
        tax_rate = po_item.tax_rate if po_item is not None and po_item.tax_rate is not None else Decimal("0")
        unit_cost = po_item.unit_price * (Decimal("1") + tax_rate / Decimal("100")) if po_item is not None else Decimal("0")
        db.add(InventoryCostLayer(source_transaction_id=transaction.id, warehouse_id=warehouse.id, location_id=location.id, product_id=delivery_item.product_id, batch_id=batch.id, unit_id=delivery_item.unit_id, unit_cost=unit_cost, currency_code="CNY", original_quantity=delivery_item.actual_quantity, remaining_quantity=delivery_item.actual_quantity))
        transactions.append(transaction)
        balances.append(balance)
    if not transactions:
        raise BusinessValidationError("到货单没有可入库的实际数量")
    add_audit_log(db, actor_id=user.id, action_type="INBOUND", resource_type="DELIVERY", resource_id=delivery.id, request_summary="执行库存入库", result_status="SUCCESS")
    db.commit()
    return transactions, balances


def _require_issue(db: Session, issue_id: int, *, for_update: bool = False) -> InventoryIssueRequest:
    """查询库存领用申请，不存在时抛出业务异常。"""

    issue = crud.get_issue_request(db, issue_id, for_update=for_update)
    if issue is None:
        raise ResourceNotFoundError(f"库存领用申请 {issue_id} 不存在")
    return issue


def _get_issue_for_user(db: Session, user: User, issue_id: int, *, for_update: bool = False) -> InventoryIssueRequest:
    """查询领用申请并校验申请人或仓库范围。"""

    issue = _require_issue(db, issue_id, for_update=for_update)
    roles = set(get_user_role_codes(db, user.id))
    if roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        return issue
    if "WAREHOUSE" in roles:
        if not issue.items:
            raise ResourceNotFoundError(f"库存领用申请 {issue_id} 不存在")
        for item in issue.items:
            _require_warehouse_scope(db, user, item.warehouse_id)
    elif issue.applicant_id != user.id:
        raise ResourceNotFoundError(f"库存领用申请 {issue_id} 不存在")
    return issue


def _validate_issue_warehouse_scope(db: Session, user: User, items: list) -> None:
    if "WAREHOUSE" in set(get_user_role_codes(db, user.id)):
        for item in items:
            _require_warehouse_scope(db, user, item.warehouse_id)


def _validate_issue_items(db: Session, items: list) -> None:
    """校验领用明细的产品、库位、批次、单位和库存位置。"""

    slots = set()
    for item in items:
        product = db.get(Product, item.product_id)
        if product is None or product.status != "ACTIVE":
            raise BusinessValidationError(f"产品 {item.product_id} 不存在或已停用")
        warehouse = db.get(Warehouse, item.warehouse_id)
        if warehouse is None or warehouse.status != "ACTIVE":
            raise BusinessValidationError(f"仓库 {item.warehouse_id} 不存在或已停用")
        location = db.get(WarehouseLocation, item.location_id)
        if location is None or location.status != "ACTIVE" or location.warehouse_id != warehouse.id:
            raise BusinessValidationError(f"库位 {item.location_id} 不存在、已停用或不属于指定仓库")
        batch = db.get(InventoryBatch, item.batch_id)
        if batch is None or batch.status != "ACTIVE":
            raise BusinessValidationError(f"库存批次 {item.batch_id} 不存在或不可用")
        if batch.product_id != item.product_id:
            raise BusinessValidationError(f"库存批次 {item.batch_id} 不属于产品 {item.product_id}")
        unit = db.get(Unit, item.unit_id)
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError(f"计量单位 {item.unit_id} 不存在或已停用")
        slot = (item.warehouse_id, item.location_id, item.product_id, item.batch_id, item.unit_id)
        if slot in slots:
            raise BusinessValidationError("同一领用申请不能重复填写相同库存位置")
        slots.add(slot)


def _build_issue_items(issue_id: int, items: list) -> list[InventoryIssueItem]:
    """根据请求明细创建领用申请明细实体。"""

    return [
        InventoryIssueItem(issue_request_id=issue_id, line_no=index, **item.model_dump())
        for index, item in enumerate(items, start=1)
    ]


def create_issue_request(db: Session, user: User, data: InventoryIssueRequestCreate) -> InventoryIssueRequest:
    """创建库存领用申请草稿。"""

    department_id = data.department_id if data.department_id is not None else user.department_id
    if department_id is not None:
        department = db.get(Department, department_id)
        if department is None or department.status != "ACTIVE":
            raise BusinessValidationError(f"领用部门 {department_id} 不存在或已停用")
    _validate_issue_warehouse_scope(db, user, data.items)
    _validate_issue_items(db, data.items)
    issue = InventoryIssueRequest(
        issue_no="TEMP",
        applicant_id=user.id,
        department_id=department_id,
        purpose=data.purpose,
        status="DRAFT",
    )
    db.add(issue)
    db.flush()
    issue.issue_no = f"IR{date.today():%Y%m%d}{issue.id:06d}"
    issue.items = _build_issue_items(issue.id, data.items)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="INVENTORY_ISSUE_REQUEST", resource_id=issue.id, request_summary="创建库存领用申请", result_status="SUCCESS")
    db.commit()
    return _require_issue(db, issue.id)


def list_issue_requests(db: Session, user: User, *, status: str | None, page: int, page_size: int):
    """按用户数据范围分页查询库存领用申请。"""

    roles = set(get_user_role_codes(db, user.id))
    if roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        applicant_id, warehouse_ids = None, None
    elif "WAREHOUSE" in roles:
        applicant_id, warehouse_ids = None, accessible_warehouse_ids(db, user) or set()
    else:
        applicant_id, warehouse_ids = user.id, None
    return crud.list_issue_requests(db, applicant_id=applicant_id, warehouse_ids=warehouse_ids, status=status, page=page, page_size=page_size)


def list_issue_request_options(db: Session) -> list[dict]:
    """Return the minimum available-stock details needed to create an issue request."""

    rows = db.execute(
        select(
            InventoryBalance.id,
            InventoryBalance.product_id,
            Product.product_name.label("product_name"),
            InventoryBalance.warehouse_id,
            Warehouse.warehouse_name.label("warehouse_name"),
            InventoryBalance.location_id,
            WarehouseLocation.location_name.label("location_name"),
            InventoryBalance.batch_id,
            InventoryBatch.batch_no.label("batch_no"),
            InventoryBalance.unit_id,
            Unit.unit_name.label("unit_name"),
            (InventoryBalance.quantity - InventoryBalance.locked_quantity).label("available_quantity"),
        )
        .join(Product, Product.id == InventoryBalance.product_id)
        .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id)
        .join(InventoryBatch, InventoryBatch.id == InventoryBalance.batch_id)
        .join(Unit, Unit.id == InventoryBalance.unit_id)
        .where(
            InventoryBalance.status == "AVAILABLE",
            InventoryBalance.quantity > InventoryBalance.locked_quantity,
            Product.status == "ACTIVE",
            Warehouse.status == "ACTIVE",
            WarehouseLocation.status == "ACTIVE",
            InventoryBatch.status == "ACTIVE",
        )
        .order_by(Product.product_name, InventoryBatch.batch_no, Warehouse.warehouse_name)
    ).mappings().all()
    return [dict(row) for row in rows]


def get_issue_request(db: Session, user: User, issue_id: int) -> InventoryIssueRequest:
    """查询库存领用申请详情。"""

    return _get_issue_for_user(db, user, issue_id)


def update_issue_request(db: Session, user: User, issue_id: int, data: InventoryIssueRequestUpdate) -> InventoryIssueRequest:
    """修改草稿或已驳回的库存领用申请。"""

    issue = _get_issue_for_user(db, user, issue_id)
    if issue.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的领用申请可以修改")
    values = data.model_dump(exclude_unset=True)
    if "department_id" in values and data.department_id is not None:
        department = db.get(Department, data.department_id)
        if department is None or department.status != "ACTIVE":
            raise BusinessValidationError(f"领用部门 {data.department_id} 不存在或已停用")
    if data.items is not None:
        _validate_issue_warehouse_scope(db, user, data.items)
        _validate_issue_items(db, data.items)
        issue.items.clear()
        issue.items.extend(_build_issue_items(issue.id, data.items))
    for field in ("department_id", "purpose"):
        if field in values:
            setattr(issue, field, values[field])
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="INVENTORY_ISSUE_REQUEST", resource_id=issue.id, request_summary="修改库存领用申请", result_status="SUCCESS")
    db.commit()
    return _require_issue(db, issue.id)


def submit_issue_request(db: Session, user: User, issue_id: int) -> InventoryIssueRequest:
    """提交库存领用申请审批。"""

    issue = _get_issue_for_user(db, user, issue_id)
    if issue.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的领用申请可以提交")
    if not issue.items:
        raise BusinessValidationError("库存领用申请至少需要一条明细")
    issue.status = "SUBMITTED"
    issue.rejected_at = None
    issue.reject_reason = None
    add_audit_log(db, actor_id=user.id, action_type="SUBMIT", resource_type="INVENTORY_ISSUE_REQUEST", resource_id=issue.id, request_summary="提交库存领用申请审批", result_status="SUCCESS")
    db.commit()
    return _require_issue(db, issue.id)


def approve_issue_request(db: Session, user: User, issue_id: int) -> InventoryIssueRequest:
    """审批通过库存领用申请。"""

    issue = _get_issue_for_user(db, user, issue_id, for_update=True)
    if issue.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的领用申请可以审批")
    issue.status = "APPROVED"
    issue.approved_by = user.id
    issue.approved_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="APPROVE", resource_type="INVENTORY_ISSUE_REQUEST", resource_id=issue.id, request_summary="审批通过库存领用申请", result_status="SUCCESS")
    db.commit()
    return _require_issue(db, issue.id)


def reject_issue_request(db: Session, user: User, issue_id: int, reason: str) -> InventoryIssueRequest:
    """驳回库存领用申请。"""

    issue = _get_issue_for_user(db, user, issue_id, for_update=True)
    if issue.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的领用申请可以驳回")
    issue.status = "REJECTED"
    issue.rejected_at = _now()
    issue.reject_reason = reason
    add_audit_log(db, actor_id=user.id, action_type="REJECT", resource_type="INVENTORY_ISSUE_REQUEST", resource_id=issue.id, request_summary="驳回库存领用申请", result_status="SUCCESS")
    db.commit()
    return _require_issue(db, issue.id)


def cancel_issue_request(db: Session, user: User, issue_id: int) -> InventoryIssueRequest:
    """取消草稿或已驳回的库存领用申请。"""

    issue = _get_issue_for_user(db, user, issue_id)
    if issue.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的领用申请可以取消")
    issue.status = "CANCELLED"
    issue.cancelled_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="CANCEL", resource_type="INVENTORY_ISSUE_REQUEST", resource_id=issue.id, request_summary="取消库存领用申请", result_status="SUCCESS")
    db.commit()
    return _require_issue(db, issue.id)


def execute_issue_request(db: Session, user: User, issue_id: int) -> InventoryIssueRequest:
    """锁定领用申请和库存余额，执行一次库存出库。"""

    try:
        issue = _get_issue_for_user(db, user, issue_id, for_update=True)
        if issue.status != "APPROVED":
            raise BusinessValidationError("只有已审批的领用申请可以执行出库")
        if not issue.items:
            raise BusinessValidationError("库存领用申请没有可出库明细")
        for item in sorted(issue.items, key=lambda value: (value.warehouse_id, value.location_id, value.product_id, value.batch_id, value.unit_id)):
            balance = db.scalar(
                select(InventoryBalance)
                .where(
                    InventoryBalance.warehouse_id == item.warehouse_id,
                    InventoryBalance.location_id == item.location_id,
                    InventoryBalance.product_id == item.product_id,
                    InventoryBalance.batch_id == item.batch_id,
                    InventoryBalance.unit_id == item.unit_id,
                )
                .with_for_update()
            )
            if balance is None:
                raise BusinessValidationError(f"领用明细 {item.line_no} 没有对应库存余额")
            available = balance.quantity - balance.locked_quantity
            if balance.status != "AVAILABLE" or available < item.requested_quantity:
                raise BusinessValidationError(f"领用明细 {item.line_no} 可用库存不足")
            balance.quantity -= item.requested_quantity
            item.issued_quantity = item.requested_quantity
            item.status = "ISSUED"
            transaction = InventoryTransaction(
                transaction_no=f"TMP-OUT-{issue.id}-{item.id}",
                transaction_type="OUTBOUND",
                warehouse_id=item.warehouse_id,
                location_id=item.location_id,
                product_id=item.product_id,
                batch_id=item.batch_id,
                unit_id=item.unit_id,
                quantity=item.requested_quantity,
                source_type="ISSUE_REQUEST",
                source_id=issue.id,
                operator_id=user.id,
                note=issue.purpose,
            )
            db.add(transaction)
            db.flush()
            transaction.transaction_no = f"IT{date.today():%Y%m%d}{transaction.id:06d}"
            allocate_outbound_cost(db, transaction, item.requested_quantity)
        issue.status = "COMPLETED"
        issue.completed_at = _now()
        add_audit_log(db, actor_id=user.id, action_type="OUTBOUND", resource_type="INVENTORY_ISSUE_REQUEST", resource_id=issue.id, request_summary="执行库存领用出库", result_status="SUCCESS")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _require_issue(db, issue.id)


def _require_transfer(db: Session, transfer_id: int, *, for_update: bool = False) -> InventoryTransferRequest:
    """查询库存调拨申请，不存在时抛出业务异常。"""

    transfer = crud.get_transfer_request(db, transfer_id, for_update=for_update)
    if transfer is None:
        raise ResourceNotFoundError(f"库存调拨申请 {transfer_id} 不存在")
    return transfer


def _get_transfer_for_user(db: Session, user: User, transfer_id: int, *, for_update: bool = False) -> InventoryTransferRequest:
    """查询调拨申请并校验申请人数据范围。"""

    transfer = _require_transfer(db, transfer_id, for_update=for_update)
    roles = set(get_user_role_codes(db, user.id))
    if roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        return transfer
    if "WAREHOUSE" in roles:
        if not transfer.items:
            raise ResourceNotFoundError(f"库存调拨申请 {transfer_id} 不存在")
        for item in transfer.items:
            _require_warehouse_scope(db, user, item.source_warehouse_id)
            _require_warehouse_scope(db, user, item.target_warehouse_id)
    elif transfer.applicant_id != user.id:
        raise ResourceNotFoundError(f"库存调拨申请 {transfer_id} 不存在")
    return transfer


def _validate_transfer_warehouse_scope(db: Session, user: User, items: list) -> None:
    if "WAREHOUSE" in set(get_user_role_codes(db, user.id)):
        for item in items:
            _require_warehouse_scope(db, user, item.source_warehouse_id)
            _require_warehouse_scope(db, user, item.target_warehouse_id)


def _validate_transfer_items(db: Session, items: list) -> None:
    """校验调拨明细的产品、源库位、目标库位、批次和单位。"""

    source_slots = set()
    for item in items:
        product = db.get(Product, item.product_id)
        if product is None or product.status != "ACTIVE":
            raise BusinessValidationError(f"产品 {item.product_id} 不存在或已停用")
        source_warehouse = db.get(Warehouse, item.source_warehouse_id)
        target_warehouse = db.get(Warehouse, item.target_warehouse_id)
        if source_warehouse is None or source_warehouse.status != "ACTIVE":
            raise BusinessValidationError(f"源仓库 {item.source_warehouse_id} 不存在或已停用")
        if target_warehouse is None or target_warehouse.status != "ACTIVE":
            raise BusinessValidationError(f"目标仓库 {item.target_warehouse_id} 不存在或已停用")
        source_location = db.get(WarehouseLocation, item.source_location_id)
        target_location = db.get(WarehouseLocation, item.target_location_id)
        if source_location is None or source_location.status != "ACTIVE" or source_location.warehouse_id != source_warehouse.id:
            raise BusinessValidationError(f"源库位 {item.source_location_id} 不存在、已停用或不属于源仓库")
        if target_location is None or target_location.status != "ACTIVE" or target_location.warehouse_id != target_warehouse.id:
            raise BusinessValidationError(f"目标库位 {item.target_location_id} 不存在、已停用或不属于目标仓库")
        if item.source_warehouse_id == item.target_warehouse_id and item.source_location_id == item.target_location_id:
            raise BusinessValidationError("源库位和目标库位不能相同")
        batch = db.get(InventoryBatch, item.batch_id)
        if batch is None or batch.status != "ACTIVE":
            raise BusinessValidationError(f"库存批次 {item.batch_id} 不存在或不可用")
        if batch.product_id != item.product_id:
            raise BusinessValidationError(f"库存批次 {item.batch_id} 不属于产品 {item.product_id}")
        unit = db.get(Unit, item.unit_id)
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError(f"计量单位 {item.unit_id} 不存在或已停用")
        source_slot = (item.source_warehouse_id, item.source_location_id, item.product_id, item.batch_id, item.unit_id)
        if source_slot in source_slots:
            raise BusinessValidationError("同一调拨申请不能重复填写相同源库存位置")
        source_slots.add(source_slot)


def _build_transfer_items(transfer_id: int, items: list) -> list[InventoryTransferItem]:
    """根据请求明细创建库存调拨明细实体。"""

    return [
        InventoryTransferItem(transfer_request_id=transfer_id, line_no=index, **item.model_dump())
        for index, item in enumerate(items, start=1)
    ]


def create_transfer_request(db: Session, user: User, data: InventoryTransferRequestCreate) -> InventoryTransferRequest:
    """创建库存调拨申请草稿。"""

    _validate_transfer_warehouse_scope(db, user, data.items)
    _validate_transfer_items(db, data.items)
    transfer = InventoryTransferRequest(transfer_no="TEMP", applicant_id=user.id, purpose=data.purpose, status="DRAFT")
    db.add(transfer)
    db.flush()
    transfer.transfer_no = f"TR{date.today():%Y%m%d}{transfer.id:06d}"
    transfer.items = _build_transfer_items(transfer.id, data.items)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="INVENTORY_TRANSFER_REQUEST", resource_id=transfer.id, request_summary="创建库存调拨申请", result_status="SUCCESS")
    db.commit()
    return _require_transfer(db, transfer.id)


def list_transfer_requests(db: Session, user: User, *, status: str | None, page: int, page_size: int):
    """按用户数据范围分页查询库存调拨申请。"""

    roles = set(get_user_role_codes(db, user.id))
    if roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        applicant_id, warehouse_ids = None, None
    elif "WAREHOUSE" in roles:
        applicant_id, warehouse_ids = None, accessible_warehouse_ids(db, user) or set()
    else:
        applicant_id, warehouse_ids = user.id, None
    return crud.list_transfer_requests(db, applicant_id=applicant_id, warehouse_ids=warehouse_ids, status=status, page=page, page_size=page_size)


def get_transfer_request(db: Session, user: User, transfer_id: int) -> InventoryTransferRequest:
    """查询库存调拨申请详情。"""

    return _get_transfer_for_user(db, user, transfer_id)


def update_transfer_request(db: Session, user: User, transfer_id: int, data: InventoryTransferRequestUpdate) -> InventoryTransferRequest:
    """修改草稿或已驳回的库存调拨申请。"""

    transfer = _get_transfer_for_user(db, user, transfer_id)
    if transfer.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的调拨申请可以修改")
    values = data.model_dump(exclude_unset=True)
    if data.items is not None:
        _validate_transfer_warehouse_scope(db, user, data.items)
        _validate_transfer_items(db, data.items)
        transfer.items.clear()
        transfer.items.extend(_build_transfer_items(transfer.id, data.items))
    if "purpose" in values:
        transfer.purpose = values["purpose"]
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="INVENTORY_TRANSFER_REQUEST", resource_id=transfer.id, request_summary="修改库存调拨申请", result_status="SUCCESS")
    db.commit()
    return _require_transfer(db, transfer.id)


def submit_transfer_request(db: Session, user: User, transfer_id: int) -> InventoryTransferRequest:
    """提交库存调拨申请审批。"""

    transfer = _get_transfer_for_user(db, user, transfer_id)
    if transfer.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的调拨申请可以提交")
    if not transfer.items:
        raise BusinessValidationError("库存调拨申请至少需要一条明细")
    transfer.status = "SUBMITTED"
    transfer.rejected_at = None
    transfer.reject_reason = None
    add_audit_log(db, actor_id=user.id, action_type="SUBMIT", resource_type="INVENTORY_TRANSFER_REQUEST", resource_id=transfer.id, request_summary="提交库存调拨申请审批", result_status="SUCCESS")
    db.commit()
    return _require_transfer(db, transfer.id)


def approve_transfer_request(db: Session, user: User, transfer_id: int) -> InventoryTransferRequest:
    """审批通过库存调拨申请。"""

    transfer = _get_transfer_for_user(db, user, transfer_id, for_update=True)
    if transfer.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的调拨申请可以审批")
    transfer.status = "APPROVED"
    transfer.approved_by = user.id
    transfer.approved_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="APPROVE", resource_type="INVENTORY_TRANSFER_REQUEST", resource_id=transfer.id, request_summary="审批通过库存调拨申请", result_status="SUCCESS")
    db.commit()
    return _require_transfer(db, transfer.id)


def reject_transfer_request(db: Session, user: User, transfer_id: int, reason: str) -> InventoryTransferRequest:
    """驳回库存调拨申请。"""

    transfer = _get_transfer_for_user(db, user, transfer_id, for_update=True)
    if transfer.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的调拨申请可以驳回")
    transfer.status = "REJECTED"
    transfer.rejected_at = _now()
    transfer.reject_reason = reason
    add_audit_log(db, actor_id=user.id, action_type="REJECT", resource_type="INVENTORY_TRANSFER_REQUEST", resource_id=transfer.id, request_summary="驳回库存调拨申请", result_status="SUCCESS")
    db.commit()
    return _require_transfer(db, transfer.id)


def cancel_transfer_request(db: Session, user: User, transfer_id: int) -> InventoryTransferRequest:
    """取消草稿或已驳回的库存调拨申请。"""

    transfer = _get_transfer_for_user(db, user, transfer_id)
    if transfer.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的调拨申请可以取消")
    transfer.status = "CANCELLED"
    transfer.cancelled_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="CANCEL", resource_type="INVENTORY_TRANSFER_REQUEST", resource_id=transfer.id, request_summary="取消库存调拨申请", result_status="SUCCESS")
    db.commit()
    return _require_transfer(db, transfer.id)


def _ensure_transfer_target_balance(db: Session, item: InventoryTransferItem) -> None:
    """在锁定目标库存前幂等创建空余额行，避免空库位并发插入冲突。"""

    db.execute(
        insert(InventoryBalance).prefix_with("IGNORE").values(
            warehouse_id=item.target_warehouse_id,
            location_id=item.target_location_id,
            product_id=item.product_id,
            batch_id=item.batch_id,
            unit_id=item.unit_id,
            quantity=Decimal("0"),
            locked_quantity=Decimal("0"),
            status="AVAILABLE",
        )
    )


def execute_transfer_request(db: Session, user: User, transfer_id: int) -> InventoryTransferRequest:
    """锁定源、目标库存并以一个事务完成库存调拨。"""

    try:
        transfer = _get_transfer_for_user(db, user, transfer_id, for_update=True)
        if transfer.status != "APPROVED":
            raise BusinessValidationError("只有已审批的调拨申请可以执行")
        if not transfer.items:
            raise BusinessValidationError("库存调拨申请没有可执行明细")
        for item in sorted(transfer.items, key=lambda value: (value.target_warehouse_id, value.target_location_id, value.product_id, value.batch_id, value.unit_id)):
            _ensure_transfer_target_balance(db, item)
        db.flush()
        slots = set()
        for item in transfer.items:
            slots.add((item.source_warehouse_id, item.source_location_id, item.product_id, item.batch_id, item.unit_id))
            slots.add((item.target_warehouse_id, item.target_location_id, item.product_id, item.batch_id, item.unit_id))
        balances = {}
        for slot in sorted(slots):
            balance = crud.get_balance(db, *slot)
            if balance is None:
                balance = db.scalar(
                    select(InventoryBalance)
                    .where(
                        InventoryBalance.warehouse_id == slot[0],
                        InventoryBalance.location_id == slot[1],
                        InventoryBalance.product_id == slot[2],
                        InventoryBalance.batch_id == slot[3],
                        InventoryBalance.unit_id == slot[4],
                    )
                    .with_for_update()
                )
            else:
                balance = db.scalar(
                    select(InventoryBalance)
                    .where(InventoryBalance.id == balance.id)
                    .with_for_update()
                )
            if balance is None:
                raise BusinessValidationError("调拨库存余额不存在")
            balances[slot] = balance
        for item in sorted(transfer.items, key=lambda value: (value.source_warehouse_id, value.source_location_id, value.product_id, value.batch_id, value.unit_id)):
            source_slot = (item.source_warehouse_id, item.source_location_id, item.product_id, item.batch_id, item.unit_id)
            target_slot = (item.target_warehouse_id, item.target_location_id, item.product_id, item.batch_id, item.unit_id)
            source = balances[source_slot]
            target = balances[target_slot]
            available = source.quantity - source.locked_quantity
            if source.status != "AVAILABLE" or available < item.requested_quantity:
                raise BusinessValidationError(f"调拨明细 {item.line_no} 源库位可用库存不足")
            if target.status != "AVAILABLE":
                raise BusinessValidationError(f"调拨明细 {item.line_no} 目标库位不可用")
            source.quantity -= item.requested_quantity
            target.quantity += item.requested_quantity
            outbound = InventoryTransaction(
                transaction_no=f"TMP-TR-{transfer.id}-{item.id}-O",
                transaction_type="OUTBOUND",
                warehouse_id=item.source_warehouse_id,
                location_id=item.source_location_id,
                product_id=item.product_id,
                batch_id=item.batch_id,
                unit_id=item.unit_id,
                quantity=item.requested_quantity,
                source_type="INVENTORY_TRANSFER",
                source_id=transfer.id,
                operator_id=user.id,
                note=f"调拨至仓库 {item.target_warehouse_id} 库位 {item.target_location_id}：{transfer.purpose}",
            )
            inbound = InventoryTransaction(
                transaction_no=f"TMP-TR-{transfer.id}-{item.id}-I",
                transaction_type="INBOUND",
                warehouse_id=item.target_warehouse_id,
                location_id=item.target_location_id,
                product_id=item.product_id,
                batch_id=item.batch_id,
                unit_id=item.unit_id,
                quantity=item.requested_quantity,
                source_type="INVENTORY_TRANSFER",
                source_id=transfer.id,
                operator_id=user.id,
                note=f"来自仓库 {item.source_warehouse_id} 库位 {item.source_location_id}：{transfer.purpose}",
            )
            db.add_all([outbound, inbound])
            db.flush()
            outbound.transaction_no = f"IT{date.today():%Y%m%d}{outbound.id:06d}"
            inbound.transaction_no = f"IT{date.today():%Y%m%d}{inbound.id:06d}"
            transfer_cost = allocate_outbound_cost(db, outbound, item.requested_quantity)
            db.add(InventoryCostLayer(
                source_transaction_id=inbound.id,
                warehouse_id=item.target_warehouse_id,
                location_id=item.target_location_id,
                product_id=item.product_id,
                batch_id=item.batch_id,
                unit_id=item.unit_id,
                unit_cost=transfer_cost / item.requested_quantity,
                currency_code="CNY",
                original_quantity=item.requested_quantity,
                remaining_quantity=item.requested_quantity,
            ))
            item.transferred_quantity = item.requested_quantity
            item.status = "TRANSFERRED"
        transfer.status = "COMPLETED"
        transfer.completed_at = _now()
        add_audit_log(db, actor_id=user.id, action_type="TRANSFER", resource_type="INVENTORY_TRANSFER_REQUEST", resource_id=transfer.id, request_summary="执行库存调拨", result_status="SUCCESS")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _require_transfer(db, transfer.id)


def _require_stocktake(db: Session, stocktake_id: int, *, for_update: bool = False) -> InventoryStocktakeRequest:
    """查询库存盘点申请，不存在时抛出业务异常。"""

    stocktake = crud.get_stocktake_request(db, stocktake_id, for_update=for_update)
    if stocktake is None:
        raise ResourceNotFoundError(f"库存盘点申请 {stocktake_id} 不存在")
    return stocktake


def _get_stocktake_for_user(db: Session, user: User, stocktake_id: int, *, for_update: bool = False) -> InventoryStocktakeRequest:
    """查询盘点申请并校验申请人数据范围。"""

    stocktake = _require_stocktake(db, stocktake_id, for_update=for_update)
    roles = set(get_user_role_codes(db, user.id))
    if roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        return stocktake
    if "WAREHOUSE" in roles:
        _require_warehouse_scope(db, user, stocktake.warehouse_id)
    elif stocktake.applicant_id != user.id:
        raise ResourceNotFoundError(f"库存盘点申请 {stocktake_id} 不存在")
    return stocktake


def _validate_stocktake_items(db: Session, warehouse_id: int, location_id: int | None, items: list) -> None:
    """校验盘点明细的仓库、库位、产品、批次和单位。"""

    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None or warehouse.status != "ACTIVE":
        raise BusinessValidationError(f"盘点仓库 {warehouse_id} 不存在或已停用")
    if location_id is not None:
        location = db.get(WarehouseLocation, location_id)
        if location is None or location.status != "ACTIVE" or location.warehouse_id != warehouse_id:
            raise BusinessValidationError(f"盘点库位 {location_id} 不存在、已停用或不属于指定仓库")
    slots = set()
    for item in items:
        product = db.get(Product, item.product_id)
        if product is None or product.status != "ACTIVE":
            raise BusinessValidationError(f"产品 {item.product_id} 不存在或已停用")
        item_location = db.get(WarehouseLocation, item.location_id)
        if item_location is None or item_location.status != "ACTIVE" or item_location.warehouse_id != warehouse_id:
            raise BusinessValidationError(f"盘点库位 {item.location_id} 不存在、已停用或不属于指定仓库")
        if location_id is not None and item.location_id != location_id:
            raise BusinessValidationError(f"盘点明细库位 {item.location_id} 与盘点单指定库位不一致")
        batch = db.get(InventoryBatch, item.batch_id)
        if batch is None or batch.status != "ACTIVE":
            raise BusinessValidationError(f"库存批次 {item.batch_id} 不存在或不可用")
        if batch.product_id != item.product_id:
            raise BusinessValidationError(f"库存批次 {item.batch_id} 不属于产品 {item.product_id}")
        unit = db.get(Unit, item.unit_id)
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError(f"计量单位 {item.unit_id} 不存在或已停用")
        slot = (item.location_id, item.product_id, item.batch_id, item.unit_id)
        if slot in slots:
            raise BusinessValidationError("同一盘点申请不能重复填写相同库存位置")
        slots.add(slot)


def _build_stocktake_items(db: Session, stocktake_id: int, items: list) -> list[InventoryStocktakeItem]:
    """创建盘点明细并保存提交时的账面数量快照。"""

    result = []
    for index, item in enumerate(items, start=1):
        balance = db.scalar(
            select(InventoryBalance).where(
                InventoryBalance.location_id == item.location_id,
                InventoryBalance.product_id == item.product_id,
                InventoryBalance.batch_id == item.batch_id,
                InventoryBalance.unit_id == item.unit_id,
            )
        )
        result.append(
            InventoryStocktakeItem(
                stocktake_request_id=stocktake_id,
                line_no=index,
                product_id=item.product_id,
                location_id=item.location_id,
                batch_id=item.batch_id,
                unit_id=item.unit_id,
                book_quantity=balance.quantity if balance is not None else Decimal("0"),
                counted_quantity=item.counted_quantity,
                note=item.note,
            )
        )
    return result


def create_stocktake_request(db: Session, user: User, data: InventoryStocktakeRequestCreate) -> InventoryStocktakeRequest:
    """创建库存盘点申请草稿并保存账面数量快照。"""

    if "WAREHOUSE" in set(get_user_role_codes(db, user.id)):
        _require_warehouse_scope(db, user, data.warehouse_id)
    _validate_stocktake_items(db, data.warehouse_id, data.location_id, data.items)
    stocktake = InventoryStocktakeRequest(
        stocktake_no="TEMP", applicant_id=user.id, warehouse_id=data.warehouse_id, location_id=data.location_id, purpose=data.purpose, status="DRAFT"
    )
    db.add(stocktake)
    db.flush()
    stocktake.stocktake_no = f"ST{date.today():%Y%m%d}{stocktake.id:06d}"
    stocktake.items = _build_stocktake_items(db, stocktake.id, data.items)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="INVENTORY_STOCKTAKE_REQUEST", resource_id=stocktake.id, request_summary="创建库存盘点申请", result_status="SUCCESS")
    db.commit()
    return _require_stocktake(db, stocktake.id)


def list_stocktake_requests(db: Session, user: User, *, status: str | None, page: int, page_size: int):
    """按用户数据范围分页查询库存盘点申请。"""

    roles = set(get_user_role_codes(db, user.id))
    if roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        applicant_id, warehouse_ids = None, None
    elif "WAREHOUSE" in roles:
        applicant_id, warehouse_ids = None, accessible_warehouse_ids(db, user) or set()
    else:
        applicant_id, warehouse_ids = user.id, None
    return crud.list_stocktake_requests(db, applicant_id=applicant_id, warehouse_ids=warehouse_ids, status=status, page=page, page_size=page_size)


def get_stocktake_request(db: Session, user: User, stocktake_id: int) -> InventoryStocktakeRequest:
    """查询库存盘点申请详情。"""

    return _get_stocktake_for_user(db, user, stocktake_id)


def update_stocktake_request(db: Session, user: User, stocktake_id: int, data: InventoryStocktakeRequestUpdate) -> InventoryStocktakeRequest:
    """修改草稿或已驳回的库存盘点申请。"""

    stocktake = _get_stocktake_for_user(db, user, stocktake_id)
    if stocktake.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的盘点申请可以修改")
    values = data.model_dump(exclude_unset=True)
    if data.items is not None:
        if "WAREHOUSE" in set(get_user_role_codes(db, user.id)):
            _require_warehouse_scope(db, user, stocktake.warehouse_id)
        _validate_stocktake_items(db, stocktake.warehouse_id, stocktake.location_id, data.items)
        stocktake.items.clear()
        stocktake.items.extend(_build_stocktake_items(db, stocktake.id, data.items))
    if "purpose" in values:
        stocktake.purpose = values["purpose"]
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="INVENTORY_STOCKTAKE_REQUEST", resource_id=stocktake.id, request_summary="修改库存盘点申请", result_status="SUCCESS")
    db.commit()
    return _require_stocktake(db, stocktake.id)


def submit_stocktake_request(db: Session, user: User, stocktake_id: int) -> InventoryStocktakeRequest:
    """提交库存盘点申请审批。"""

    stocktake = _get_stocktake_for_user(db, user, stocktake_id)
    if stocktake.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的盘点申请可以提交")
    if not stocktake.items:
        raise BusinessValidationError("库存盘点申请至少需要一条明细")
    stocktake.status = "SUBMITTED"
    stocktake.rejected_at = None
    stocktake.reject_reason = None
    add_audit_log(db, actor_id=user.id, action_type="SUBMIT", resource_type="INVENTORY_STOCKTAKE_REQUEST", resource_id=stocktake.id, request_summary="提交库存盘点申请审批", result_status="SUCCESS")
    db.commit()
    return _require_stocktake(db, stocktake.id)


def approve_stocktake_request(db: Session, user: User, stocktake_id: int) -> InventoryStocktakeRequest:
    """审批通过库存盘点申请。"""

    stocktake = _get_stocktake_for_user(db, user, stocktake_id, for_update=True)
    if stocktake.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的盘点申请可以审批")
    stocktake.status = "APPROVED"
    stocktake.approved_by = user.id
    stocktake.approved_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="APPROVE", resource_type="INVENTORY_STOCKTAKE_REQUEST", resource_id=stocktake.id, request_summary="审批通过库存盘点申请", result_status="SUCCESS")
    db.commit()
    return _require_stocktake(db, stocktake.id)


def reject_stocktake_request(db: Session, user: User, stocktake_id: int, reason: str) -> InventoryStocktakeRequest:
    """驳回库存盘点申请。"""

    stocktake = _get_stocktake_for_user(db, user, stocktake_id, for_update=True)
    if stocktake.status != "SUBMITTED":
        raise BusinessValidationError("只有待审批的盘点申请可以驳回")
    stocktake.status = "REJECTED"
    stocktake.rejected_at = _now()
    stocktake.reject_reason = reason
    add_audit_log(db, actor_id=user.id, action_type="REJECT", resource_type="INVENTORY_STOCKTAKE_REQUEST", resource_id=stocktake.id, request_summary="驳回库存盘点申请", result_status="SUCCESS")
    db.commit()
    return _require_stocktake(db, stocktake.id)


def cancel_stocktake_request(db: Session, user: User, stocktake_id: int) -> InventoryStocktakeRequest:
    """取消草稿或已驳回的库存盘点申请。"""

    stocktake = _get_stocktake_for_user(db, user, stocktake_id)
    if stocktake.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的盘点申请可以取消")
    stocktake.status = "CANCELLED"
    stocktake.cancelled_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="CANCEL", resource_type="INVENTORY_STOCKTAKE_REQUEST", resource_id=stocktake.id, request_summary="取消库存盘点申请", result_status="SUCCESS")
    db.commit()
    return _require_stocktake(db, stocktake.id)


def _ensure_stocktake_balance(db: Session, item: InventoryStocktakeItem, warehouse_id: int) -> None:
    """为实盘数量大于零且尚无余额的库存位置创建零余额行。"""

    db.execute(
        insert(InventoryBalance).prefix_with("IGNORE").values(
            warehouse_id=warehouse_id,
            location_id=item.location_id,
            product_id=item.product_id,
            batch_id=item.batch_id,
            unit_id=item.unit_id,
            quantity=Decimal("0"),
            locked_quantity=Decimal("0"),
            status="AVAILABLE",
        )
    )


def execute_stocktake_request(db: Session, user: User, stocktake_id: int) -> InventoryStocktakeRequest:
    """锁定库存余额，校验账面快照后一次性完成盘点差异调整。"""

    try:
        stocktake = _get_stocktake_for_user(db, user, stocktake_id, for_update=True)
        if stocktake.status != "APPROVED":
            raise BusinessValidationError("只有已审批的盘点申请可以执行")
        if not stocktake.items:
            raise BusinessValidationError("库存盘点申请没有可执行明细")
        for item in sorted(stocktake.items, key=lambda value: (value.location_id, value.product_id, value.batch_id, value.unit_id)):
            if item.counted_quantity > 0:
                _ensure_stocktake_balance(db, item, stocktake.warehouse_id)
        db.flush()
        for item in sorted(stocktake.items, key=lambda value: (value.location_id, value.product_id, value.batch_id, value.unit_id)):
            balance = db.scalar(
                select(InventoryBalance)
                .where(
                    InventoryBalance.warehouse_id == stocktake.warehouse_id,
                    InventoryBalance.location_id == item.location_id,
                    InventoryBalance.product_id == item.product_id,
                    InventoryBalance.batch_id == item.batch_id,
                    InventoryBalance.unit_id == item.unit_id,
                )
                .with_for_update()
            )
            if balance is None:
                if item.book_quantity != 0 or item.counted_quantity != 0:
                    raise BusinessValidationError(f"盘点明细 {item.line_no} 库存余额不存在，请重新盘点")
                item.difference_quantity = Decimal("0")
                item.status = "ADJUSTED"
                continue
            if balance.quantity != item.book_quantity:
                raise BusinessValidationError(f"盘点明细 {item.line_no} 账面库存已变化，请重新盘点")
            if item.counted_quantity < balance.locked_quantity:
                raise BusinessValidationError(f"盘点明细 {item.line_no} 实盘数量不能低于已锁定库存")
            if balance.status != "AVAILABLE" and item.counted_quantity != item.book_quantity:
                raise BusinessValidationError(f"盘点明细 {item.line_no} 库存状态不可调整")
            difference = item.counted_quantity - item.book_quantity
            balance.quantity = item.counted_quantity
            item.difference_quantity = difference
            item.status = "ADJUSTED"
            if difference != 0:
                transaction = InventoryTransaction(
                    transaction_no=f"TMP-ST-{stocktake.id}-{item.id}",
                    transaction_type="ADJUSTMENT",
                    warehouse_id=stocktake.warehouse_id,
                    location_id=item.location_id,
                    product_id=item.product_id,
                    batch_id=item.batch_id,
                    unit_id=item.unit_id,
                    quantity=abs(difference),
                    source_type="INVENTORY_STOCKTAKE",
                    source_id=stocktake.id,
                    operator_id=user.id,
                    note=f"库存盘点{'盘盈' if difference > 0 else '盘亏'}：{stocktake.purpose}",
                )
                db.add(transaction)
                db.flush()
                transaction.transaction_no = f"IT{date.today():%Y%m%d}{transaction.id:06d}"
        stocktake.status = "COMPLETED"
        stocktake.completed_at = _now()
        add_audit_log(db, actor_id=user.id, action_type="STOCKTAKE", resource_type="INVENTORY_STOCKTAKE_REQUEST", resource_id=stocktake.id, request_summary="执行库存盘点差异调整", result_status="SUCCESS")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _require_stocktake(db, stocktake.id)
