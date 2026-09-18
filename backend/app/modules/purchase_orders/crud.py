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


def get_by_id(db: Session, order_id: int) -> PurchaseOrder | None:
    """按主键查询订单及其明细、审批和事件。"""

    return db.scalar(select(PurchaseOrder).options(*detail_options()).where(PurchaseOrder.id == order_id))


def list_page(
    db: Session,
    *,
    buyer_id: int | None,
    keyword: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[PurchaseOrder], int]:
    """按用户范围和筛选条件分页查询采购订单。"""

    conditions = []
    if buyer_id is not None:
        conditions.append(PurchaseOrder.buyer_id == buyer_id)
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


def get_quote(db: Session, quote_id: int) -> SupplierQuote | None:
    """查询报价及报价明细。"""

    return db.scalar(
        select(SupplierQuote)
        .options(selectinload(SupplierQuote.items))
        .where(SupplierQuote.id == quote_id)
    )


def get_comparison(db: Session, comparison_id: int) -> QuoteComparison | None:
    """查询比价结果及比价明细。"""

    return db.scalar(
        select(QuoteComparison)
        .options(selectinload(QuoteComparison.items))
        .where(QuoteComparison.id == comparison_id)
    )


def get_pending_approval(db: Session, order_id: int) -> PurchaseOrderApproval | None:
    """查询订单当前待处理的审批节点。"""

    return db.scalar(
        select(PurchaseOrderApproval)
        .where(PurchaseOrderApproval.po_id == order_id, PurchaseOrderApproval.action == "PENDING")
        .order_by(PurchaseOrderApproval.sequence_no)
    )


def get_event_count(db: Session, order_id: int) -> int:
    """查询订单事件数量，用于判断是否已产生业务事件。"""

    return db.scalar(select(func.count(PurchaseOrderEvent.id)).where(PurchaseOrderEvent.po_id == order_id)) or 0
