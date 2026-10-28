"""到货登记、收货确认和采购订单数量回写的业务逻辑。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.deliveries import crud
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.deliveries.schema import DeliveryCreate, DeliveryReceive
from app.modules.purchase_orders.scope import order_read_condition
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderEvent
from app.modules.operation_exceptions.service import create_automatic_exception
from app.modules.notifications.service import notify_users
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    """返回当前本地时间。"""

    return datetime.now()


def _can_manage_all(db: Session, user: User) -> bool:
    """判断用户是否可以查看全部到货记录。"""

    # 到货单没有独立仓库归属，只能继承采购订单的数据范围。
    # 仓库岗位负责收货，但该职责不应扩大为跨部门读取全部订单。
    return bool({"SYS_ADMIN", "PROCUREMENT_MANAGER"} & set(get_user_role_codes(db, user.id)))


def _require_delivery(db: Session, delivery_id: int, *, for_update: bool = False) -> Delivery:
    """查询到货单，不存在时抛出业务异常。"""

    delivery = crud.get_by_id(db, delivery_id, for_update=for_update)
    if delivery is None:
        raise ResourceNotFoundError(f"到货单 {delivery_id} 不存在")
    return delivery


def _require_order(db: Session, user: User, po_id: int, *, for_update: bool = False) -> PurchaseOrder:
    """查询采购订单并校验用户数据范围。"""

    order = crud.get_order(db, po_id, for_update=for_update)
    if order is None:
        raise ResourceNotFoundError(f"采购订单 {po_id} 不存在")
    if not _can_manage_all(db, user) and not ((user.department_id is not None and order.department_id == user.department_id) or (user.department_id is None and order.buyer_id == user.id)):
        raise ResourceNotFoundError(f"采购订单 {po_id} 不存在")
    from sqlalchemy import literal
    from app.modules.system.data_scope import department_scope_condition
    if not db.scalar(select(department_scope_condition(user, get_user_role_codes(db, user.id), literal(order.department_id)))):
        raise ResourceNotFoundError(f"采购订单 {po_id} 不存在")
    return order


def _check_dates(production_date: date | None, expiry_date: date | None) -> None:
    """校验生产日期和失效日期的先后关系。"""

    if production_date and expiry_date and production_date > expiry_date:
        raise BusinessValidationError("生产日期不能晚于失效日期")


def create_delivery(db: Session, user: User, data: DeliveryCreate) -> Delivery:
    """为已下单采购订单登记到货计划。"""

    order = _require_order(db, user, data.po_id, for_update=True)
    if order.status not in {"ORDERED", "PARTIAL"}:
        raise BusinessValidationError("只有已下单或部分到货的采购订单可以登记到货")
    po_items = {item.id: item for item in order.items}
    input_ids = [item.po_item_id for item in data.items]
    if len(input_ids) != len(set(input_ids)):
        raise BusinessValidationError("到货明细不能重复引用采购订单明细")
    if not set(input_ids).issubset(po_items):
        raise BusinessValidationError("到货明细必须引用当前采购订单明细")
    for item in data.items:
        po_item = po_items[item.po_item_id]
        remaining = po_item.order_quantity - po_item.received_quantity
        if item.planned_quantity > remaining:
            raise BusinessValidationError(f"订单明细 {po_item.line_no} 剩余未收数量不足")
        _check_dates(item.production_date, item.expiry_date)
    delivery = Delivery(
        delivery_no=f"TEMP-D-{user.id}-{int(_now().timestamp())}",
        po_id=order.id,
        supplier_id=order.supplier_id,
        shipment_date=data.shipment_date,
        expected_arrival_date=data.expected_arrival_date,
        logistics_company=data.logistics_company,
        tracking_no=data.tracking_no,
        status="IN_TRANSIT",
        note=data.note,
    )
    delivery.items = [
        DeliveryItem(
            line_no=index,
            product_id=po_items[item.po_item_id].product_id,
            po_item_id=item.po_item_id,
            batch_no=item.batch_no,
            package_spec=item.package_spec,
            planned_quantity=item.planned_quantity,
            actual_quantity=0,
            short_quantity=0,
            unit_id=po_items[item.po_item_id].unit_id,
            production_date=item.production_date,
            expiry_date=item.expiry_date,
            document_complete=1 if item.document_complete else 0,
            note=item.note,
        )
        for index, item in enumerate(data.items, start=1)
    ]
    db.add(delivery)
    db.flush()
    delivery.delivery_no = f"DL{date.today():%Y%m%d}{delivery.id:06d}"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="DELIVERY", resource_id=delivery.id, request_summary="登记到货计划", result_status="SUCCESS")
    db.commit()
    return _require_delivery(db, delivery.id)


def list_deliveries(db: Session, user: User, *, keyword: str | None, status: str | None, page: int, page_size: int):
    """按用户数据范围分页查询到货单。"""

    roles = set(get_user_role_codes(db, user.id))
    po_ids = {order.id for order in db.scalars(select(PurchaseOrder).where(order_read_condition(user, roles))).all()}
    return crud.list_page(db, po_ids=po_ids, keyword=keyword, status=status, page=page, page_size=page_size)


def get_delivery(db: Session, user: User, delivery_id: int) -> Delivery:
    """查询到货单详情并校验关联订单数据范围。"""

    delivery = _require_delivery(db, delivery_id)
    from app.modules.purchase_orders.service import read_order
    read_order(db, user, delivery.po_id)
    return delivery


def get_delivery_by_no(db: Session, user: User, delivery_no: str) -> Delivery | None:
    """按精确到货单号读取记录，并复用详情服务校验关联订单的数据范围。"""

    delivery_id = db.scalar(select(Delivery.id).where(Delivery.delivery_no == delivery_no))
    if delivery_id is None:
        return None
    return get_delivery(db, user, delivery_id)


def receive_delivery(db: Session, user: User, delivery_id: int, data: DeliveryReceive) -> Delivery:
    """确认到货，累计采购订单收货数量并更新订单状态。"""

    # 先锁到货单，再锁采购订单，串行化同一到货单和同一订单的并发收货。
    delivery = _require_delivery(db, delivery_id, for_update=True)
    order = _require_order(db, user, delivery.po_id, for_update=True)
    if delivery.status != "IN_TRANSIT":
        raise BusinessValidationError("只有运输中的到货单可以确认收货")
    delivery_items = {item.id: item for item in delivery.items}
    input_ids = [item.delivery_item_id for item in data.items]
    if set(input_ids) != set(delivery_items) or len(input_ids) != len(set(input_ids)):
        raise BusinessValidationError("收货明细必须完整且不能重复")
    po_items = {item.id: item for item in order.items}
    for item in data.items:
        delivery_item = delivery_items[item.delivery_item_id]
        po_item = po_items[delivery_item.po_item_id]
        if item.actual_quantity + item.short_quantity > delivery_item.planned_quantity:
            raise BusinessValidationError(f"到货明细 {delivery_item.line_no} 的实收和短交数量不能超过计划数量")
        if po_item.received_quantity + item.actual_quantity > po_item.order_quantity:
            raise BusinessValidationError(f"订单明细 {po_item.line_no} 的累计收货数量不能超过订购数量")
    for item in data.items:
        delivery_item = delivery_items[item.delivery_item_id]
        po_item = po_items[delivery_item.po_item_id]
        delivery_item.actual_quantity = item.actual_quantity
        delivery_item.short_quantity = item.short_quantity
        po_item.received_quantity += item.actual_quantity
        po_item.status = "FULFILLED" if po_item.received_quantity >= po_item.order_quantity else "PARTIAL"
    delivery.status = "RECEIVED"
    delivery.actual_arrival_date = data.actual_arrival_date or date.today()
    delivery.received_by = user.id
    delivery.received_at = _now()
    previous = order.status
    order.status = "COMPLETED" if all(item.received_quantity >= item.order_quantity for item in order.items) else "PARTIAL"
    order.events.append(
        PurchaseOrderEvent(
            operator_id=user.id,
            event_type="COMPLETED" if order.status == "COMPLETED" else "PARTIAL_RECEIVED",
            from_status=previous,
            to_status=order.status,
            event_note="确认到货并回写采购订单收货数量",
        )
    )
    short_items = [item for item in delivery.items if item.short_quantity > 0]
    if short_items:
        short_lines = "、".join(f"第{item.line_no}行短交 {item.short_quantity}" for item in short_items)
        exception = create_automatic_exception(
            db,
            user,
            exception_type="SHORT_DELIVERY",
            source_type="DELIVERY",
            source_id=delivery.id,
            po_id=order.id,
            delivery_id=delivery.id,
            owner_id=order.buyer_id,
            severity="HIGH",
            description=f"到货单 {delivery.delivery_no} 存在短交：{short_lines}",
        )
        if exception is not None:
            notify_users(
                db,
                recipient_ids=[order.buyer_id],
                role_codes=["PROCUREMENT_MANAGER", "WAREHOUSE"],
                notification_type="EXCEPTION_CREATED",
                title="发现短交异常",
                content=exception.description,
                related_type="OPERATION_EXCEPTION",
                related_id=exception.id,
            )
    add_audit_log(db, actor_id=user.id, action_type="RECEIVE", resource_type="DELIVERY", resource_id=delivery.id, request_summary="确认收货", result_status="SUCCESS")
    db.commit()
    return _require_delivery(db, delivery.id)
