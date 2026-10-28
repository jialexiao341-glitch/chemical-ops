"""采购订单模块的数据访问操作。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderApproval, PurchaseOrderEvent
from app.modules.rfqs.model import QuoteComparison, SupplierQuote


def detail_options():
    """返回采购订单详情需要的关联预加载配置。"""

    return (
        selectinload(PurchaseOrder.items),
        selectinload(PurchaseOrder.approvals),
        selectinload(PurchaseOrder.events),
    )


def get_by_id(db: Session, order_id: int, *, for_update: bool = False) -> PurchaseOrder | None:
    """按主键查询订单及其明细、审批和事件。"""

    statement = select(PurchaseOrder).options(*detail_options()).where(PurchaseOrder.id == order_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_page(
    db: Session,
    *,
    scope_condition,
    keyword: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[PurchaseOrder], int]:
    """按用户范围和筛选条件分页查询采购订单。"""

    conditions = [scope_condition]
    if keyword:
        conditions.append(PurchaseOrder.po_no.like(f"%{keyword}%"))
    if status:
        conditions.append(PurchaseOrder.status == status)
    total = db.scalar(select(func.count(PurchaseOrder.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(PurchaseOrder)
            .options(*detail_options())
            .where(*conditions)
            .order_by(PurchaseOrder.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_quote(db: Session, quote_id: int, *, for_update: bool = False) -> SupplierQuote | None:
    """查询报价及报价明细；订单确认时锁定并刷新当前报价状态。"""

    statement = (
        select(SupplierQuote)
        .options(selectinload(SupplierQuote.items))
        .where(SupplierQuote.id == quote_id)
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return db.scalar(statement)


def get_comparison(db: Session, comparison_id: int) -> QuoteComparison | None:
    """查询比价结果及比价明细。"""

    return db.scalar(
        select(QuoteComparison)
        .options(selectinload(QuoteComparison.items))
        .where(QuoteComparison.id == comparison_id)
    )


def get_pending_approval(db: Session, order_id: int, *, for_update: bool = False) -> PurchaseOrderApproval | None:
    """查询订单当前待处理的审批节点。"""

    statement = (
        select(PurchaseOrderApproval)
        .where(PurchaseOrderApproval.po_id == order_id, PurchaseOrderApproval.action == "PENDING")
        .order_by(PurchaseOrderApproval.sequence_no)
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def get_event_count(db: Session, order_id: int) -> int:
    """查询订单事件数量，用于判断是否已产生业务事件。"""

    return db.scalar(select(func.count(PurchaseOrderEvent.id)).where(PurchaseOrderEvent.po_id == order_id)) or 0
