"""到货模块的数据访问操作。"""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderItem


def get_by_id(db: Session, delivery_id: int, *, for_update: bool = False) -> Delivery | None:
    """按主键查询到货单及明细，可选锁定到货主单及子表明细。"""

    statement = select(Delivery).options(selectinload(Delivery.items)).where(Delivery.id == delivery_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    delivery = db.scalar(statement)
    if delivery is not None and for_update:
        items = list(
            db.scalars(
                select(DeliveryItem)
                .where(DeliveryItem.delivery_id == delivery.id)
                .order_by(DeliveryItem.line_no, DeliveryItem.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        set_committed_value(delivery, "items", items)
    return delivery


def list_page(
    db: Session,
    *,
    po_ids: Select,
    keyword: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Delivery], int]:
    """按订单范围和筛选条件分页查询到货单。"""

    conditions = [Delivery.po_id.in_(po_ids)]
    if keyword:
        conditions.append(Delivery.delivery_no.like(f"%{keyword}%"))
    if status:
        conditions.append(Delivery.status == status)
    total = db.scalar(select(func.count(Delivery.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(Delivery)
            .options(selectinload(Delivery.items))
            .where(*conditions)
            .order_by(Delivery.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_order(db: Session, po_id: int, *, for_update: bool = False) -> PurchaseOrder | None:
    """查询采购订单、明细和事件，可选锁定订单主单及子表明细。"""

    from app.modules.purchase_orders.crud import detail_options

    statement = select(PurchaseOrder).options(*detail_options()).where(PurchaseOrder.id == po_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    order = db.scalar(statement)
    if order is not None and for_update:
        items = list(
            db.scalars(
                select(PurchaseOrderItem)
                .where(PurchaseOrderItem.po_id == order.id)
                .order_by(PurchaseOrderItem.line_no, PurchaseOrderItem.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        set_committed_value(order, "items", items)
    return order


def get_item(db: Session, delivery_item_id: int) -> DeliveryItem | None:
    """查询到货明细。"""

    return db.get(DeliveryItem, delivery_item_id)
