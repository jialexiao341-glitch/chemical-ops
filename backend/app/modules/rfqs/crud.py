"""询价模块的数据访问操作。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.modules.purchase_requests.model import PurchaseRequest, PurchaseRequestItem, Unit
from app.modules.products.model import Product
from app.modules.rfqs.model import (
    QuoteComparison,
    RFQ,
    RFQItem,
    RFQSupplier,
    SupplierQuote,
    SupplierQuoteItem,
)
from app.modules.suppliers.model import Supplier


def detail_options():
    """返回询价详情需要的关联预加载配置。"""

    return (
        selectinload(RFQ.items),
        selectinload(RFQ.suppliers),
        selectinload(RFQ.quotes).selectinload(SupplierQuote.items),
        selectinload(RFQ.comparisons).selectinload(QuoteComparison.items),
    )


def get_by_id(db: Session, rfq_id: int) -> RFQ | None:
    """按主键查询询价单及其嵌套数据。"""

    return db.scalar(select(RFQ).options(*detail_options()).where(RFQ.id == rfq_id))


def list_page(
    db: Session,
    *,
    requester_id: int | None,
    keyword: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[RFQ], int]:
    """按用户范围和筛选条件返回询价分页数据。"""

    conditions = []
    if requester_id is not None:
        conditions.append(RFQ.requester_id == requester_id)
    if keyword:
        conditions.append(RFQ.rfq_no.like(f"%{keyword}%"))
    if status:
        conditions.append(RFQ.status == status)

    total = db.scalar(select(func.count(RFQ.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(RFQ)
            .options(*detail_options())
            .where(*conditions)
            .order_by(RFQ.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_request(db: Session, request_id: int) -> PurchaseRequest | None:
    """查询采购申请。"""

    return db.scalar(
        select(PurchaseRequest)
        .options(selectinload(PurchaseRequest.items))
        .where(PurchaseRequest.id == request_id)
    )


def get_request_item(db: Session, item_id: int) -> PurchaseRequestItem | None:
    """查询采购申请明细。"""

    return db.get(PurchaseRequestItem, item_id)


def get_product(db: Session, product_id: int) -> Product | None:
    """查询产品主数据。"""

    return db.get(Product, product_id)


def get_supplier(db: Session, supplier_id: int) -> Supplier | None:
    """查询供应商主数据。"""

    return db.get(Supplier, supplier_id)


def get_unit(db: Session, unit_id: int) -> Unit | None:
    """查询计量单位。"""

    return db.get(Unit, unit_id)


def get_quote(db: Session, quote_id: int) -> SupplierQuote | None:
    """查询报价及报价明细。"""

    return db.scalar(
        select(SupplierQuote)
        .options(selectinload(SupplierQuote.items))
        .where(SupplierQuote.id == quote_id)
    )


def get_comparison(db: Session, rfq_id: int, comparison_id: int) -> QuoteComparison | None:
    """查询指定询价单下的比价结果。"""

    return db.scalar(
        select(QuoteComparison)
        .options(selectinload(QuoteComparison.items))
        .where(QuoteComparison.id == comparison_id, QuoteComparison.rfq_id == rfq_id)
    )


def get_latest_comparison(db: Session, rfq_id: int) -> QuoteComparison | None:
    """查询询价单最近一次比价结果。"""

    return db.scalar(
        select(QuoteComparison)
        .options(selectinload(QuoteComparison.items))
        .where(QuoteComparison.rfq_id == rfq_id)
        .order_by(QuoteComparison.id.desc())
        .limit(1)
    )


def get_invitation(db: Session, rfq_id: int, supplier_id: int) -> RFQSupplier | None:
    """查询询价单与供应商的邀请关系。"""

    return db.get(RFQSupplier, {"rfq_id": rfq_id, "supplier_id": supplier_id})
