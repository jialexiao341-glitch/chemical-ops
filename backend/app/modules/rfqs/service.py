"""询价、供应商报价、比价和定标的业务逻辑。"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.purchase_requests.service import get_request as get_scoped_purchase_request
from app.modules.rfqs import crud
from app.modules.rfqs.model import QuoteComparison, QuoteComparisonItem, RFQ, RFQItem, RFQSupplier, SupplierQuote, SupplierQuoteItem
from app.modules.rfqs.schema import (
    QuoteSelection,
    RFQCreate,
    RFQItemCreate,
    RFQUpdate,
    SupplierQuoteCreate,
)
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    """返回当前本地时间。"""

    return datetime.now()


def _ensure_unique(values: list[int], label: str) -> None:
    """检查列表中是否存在重复主键。"""

    if len(values) != len(set(values)):
        raise BusinessValidationError(f"{label}不能重复")


def _validate_item_refs(db: Session, items: list[RFQItemCreate], source_request_id: int | None) -> None:
    """校验询价明细关联的采购申请、产品和计量单位。"""

    source_items = {}
    if source_request_id is not None:
        request = crud.get_request(db, source_request_id)
        if request is None:
            raise ResourceNotFoundError("来源采购申请不存在")
        if request.status != "APPROVED":
            raise BusinessValidationError("只有已审批的采购申请才能发起询价")
        source_items = {item.id: item for item in request.items}

    for item in items:
        if item.source_request_item_id is not None:
            source_item = source_items.get(item.source_request_item_id)
            if source_item is None:
                raise BusinessValidationError("询价明细引用的采购申请明细不属于来源申请")
        if item.product_id is not None:
            product = crud.get_product(db, item.product_id)
            if product is None:
                raise ResourceNotFoundError(f"产品 {item.product_id} 不存在")
            if product.status != "ACTIVE":
                raise BusinessValidationError(f"产品 {product.product_code} 当前不可采购")
        unit = crud.get_unit(db, item.unit_id)
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError(f"计量单位 {item.unit_id} 不存在或已停用")


def _validate_suppliers(db: Session, supplier_ids: list[int]) -> None:
    """校验邀请供应商是否存在且启用。"""

    _ensure_unique(supplier_ids, "供应商")
    for supplier_id in supplier_ids:
        supplier = crud.get_supplier(db, supplier_id)
        if supplier is None:
            raise ResourceNotFoundError(f"供应商 {supplier_id} 不存在")
        if supplier.status != "ACTIVE":
            raise BusinessValidationError(f"供应商 {supplier.supplier_code} 当前不可询价")


def _replace_items(db: Session, rfq: RFQ, items: list[RFQItemCreate]) -> None:
    """替换询价单明细。"""

    rfq.items.clear()
    for line_no, item in enumerate(items, start=1):
        rfq.items.append(RFQItem(line_no=line_no, **item.model_dump()))


def _replace_suppliers(rfq: RFQ, supplier_ids: list[int]) -> None:
    """替换询价单邀请供应商。"""

    rfq.suppliers.clear()
    for supplier_id in supplier_ids:
        rfq.suppliers.append(RFQSupplier(supplier_id=supplier_id, invitation_channel="MANUAL"))


def create_rfq(db: Session, user: User, data: RFQCreate, *, commit: bool = True) -> RFQ:
    """创建询价草稿。"""

    if data.source_request_id is not None:
        get_scoped_purchase_request(db, user, data.source_request_id)
    _validate_item_refs(db, data.items, data.source_request_id)
    _validate_suppliers(db, data.supplier_ids)
    rfq = RFQ(
        rfq_no=f"TEMP-{user.id}-{int(_now().timestamp())}",
        source_request_id=data.source_request_id,
        requester_id=user.id,
        quote_deadline=data.quote_deadline,
        requested_delivery_date=data.requested_delivery_date,
        delivery_requirements=data.delivery_requirements,
    )
    _replace_items(db, rfq, data.items)
    _replace_suppliers(rfq, data.supplier_ids)
    db.add(rfq)
    db.flush()
    rfq.rfq_no = f"RFQ{date.today():%Y%m%d}{rfq.id:06d}"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="RFQ", resource_id=rfq.id, request_summary="创建询价草稿", result_status="SUCCESS")
    if commit:
        db.commit()
        return crud.get_by_id(db, rfq.id)
    return rfq


def list_rfqs(db: Session, user: User, *, keyword: str | None, status: str | None, page: int, page_size: int):
    """按用户数据范围分页查询询价单。"""

    requester_id = None if bool({"SYS_ADMIN", "PROCUREMENT_MANAGER"} & set(get_user_role_codes(db, user.id))) else user.id
    return crud.list_page(db, requester_id=requester_id, keyword=keyword, status=status, page=page, page_size=page_size)


def get_rfq(db: Session, user: User, rfq_id: int, *, for_update: bool = False) -> RFQ:
    """查询询价详情并执行基础数据范围校验。"""

    rfq = crud.get_by_id(db, rfq_id, for_update=for_update)
    if rfq is None:
        raise ResourceNotFoundError("询价单不存在")
    if rfq.requester_id != user.id:
        if not bool({"SYS_ADMIN", "PROCUREMENT_MANAGER"} & set(get_user_role_codes(db, user.id))):
            raise BusinessValidationError("无权查看其他用户创建的询价单")
    return rfq


def update_rfq(db: Session, user: User, rfq_id: int, data: RFQUpdate) -> RFQ:
    """更新询价草稿。"""

    rfq = get_rfq(db, user, rfq_id)
    if rfq.status != "DRAFT":
        raise BusinessValidationError("只有草稿状态的询价单可以修改")
    values = data.model_dump(exclude_unset=True)
    if "items" in values:
        if rfq.source_request_id is not None:
            get_scoped_purchase_request(db, user, rfq.source_request_id)
        _validate_item_refs(db, data.items or [], rfq.source_request_id)
        _replace_items(db, rfq, data.items or [])
        values.pop("items")
    if "supplier_ids" in values:
        _validate_suppliers(db, data.supplier_ids or [])
        _replace_suppliers(rfq, data.supplier_ids or [])
        values.pop("supplier_ids")
    for key, value in values.items():
        setattr(rfq, key, value)
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="RFQ", resource_id=rfq.id, request_summary="更新询价草稿", result_status="SUCCESS")
    db.commit()
    return crud.get_by_id(db, rfq.id)


def send_rfq(db: Session, user: User, rfq_id: int, *, commit: bool = True) -> RFQ:
    """发送询价并进入等待报价状态。"""

    rfq = get_rfq(db, user, rfq_id, for_update=True)
    if rfq.status != "DRAFT":
        raise BusinessValidationError("只有草稿状态的询价单可以发送")
    if not rfq.items or not rfq.suppliers:
        raise BusinessValidationError("询价单必须包含明细和邀请供应商")
    rfq.status = "SENT"
    rfq.sent_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="SEND", resource_type="RFQ", resource_id=rfq.id, request_summary="发送询价单", result_status="SUCCESS")
    if commit:
        db.commit()
        return crud.get_by_id(db, rfq.id)
    db.flush()
    return rfq


def create_quote(db: Session, user: User, rfq_id: int, data: SupplierQuoteCreate) -> RFQ:
    """录入一份供应商报价，并更新供应商响应状态。"""

    rfq = get_rfq(db, user, rfq_id)
    return create_quote_for_supplier(db, user, rfq, data.supplier_id, data)


def create_quote_for_supplier(
    db: Session,
    user: User,
    rfq: RFQ,
    supplier_id: int,
    data: SupplierQuoteCreate,
) -> RFQ:
    """为已邀请的供应商创建一版报价；调用方负责授权询价范围。"""

    if rfq.status not in {"SENT", "RESPONDING"}:
        raise BusinessValidationError("当前询价单不接受供应商报价")
    supplier = crud.get_supplier(db, supplier_id)
    if supplier is None:
        raise ResourceNotFoundError("供应商不存在")
    if supplier.status != "ACTIVE":
        raise BusinessValidationError("供应商已停用，不能录入报价")
    invitation = crud.get_invitation(db, rfq.id, supplier_id)
    if invitation is None:
        raise BusinessValidationError("该供应商未被邀请参与本次询价")
    item_ids = {item.id for item in rfq.items}
    seen_item_ids = [item.rfq_item_id for item in data.items]
    _ensure_unique(seen_item_ids, "报价明细")
    if not set(seen_item_ids).issubset(item_ids):
        raise BusinessValidationError("报价明细必须引用当前询价单明细")
    for item in data.items:
        unit = crud.get_unit(db, item.unit_id)
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError(f"报价计量单位 {item.unit_id} 不存在或已停用")
        if item.moq_unit_id is not None:
            moq_unit = crud.get_unit(db, item.moq_unit_id)
            if moq_unit is None or moq_unit.status != "ACTIVE":
                raise BusinessValidationError(f"最小起订量单位 {item.moq_unit_id} 不存在或已停用")
    existing_version = db.scalar(
        select(SupplierQuote.quote_version)
        .where(SupplierQuote.rfq_id == rfq.id, SupplierQuote.supplier_id == supplier_id)
        .order_by(SupplierQuote.quote_version.desc())
    )
    quote = SupplierQuote(
        quote_no=f"TEMP-Q-{rfq.id}-{supplier_id}-{int(_now().timestamp())}",
        rfq_id=rfq.id,
        supplier_id=supplier_id,
        quote_version=(existing_version or 0) + 1,
        quote_date=data.quote_date or date.today(),
        valid_until=data.valid_until,
        currency_code=data.currency_code,
        status="SUBMITTED",
        source_file_id=data.source_file_id,
        received_by=user.id,
        note=data.note,
    )
    quote.items = [SupplierQuoteItem(**item.model_dump()) for item in data.items]
    db.add(quote)
    db.flush()
    quote.quote_no = f"Q{date.today():%Y%m%d}{quote.id:06d}"
    invitation.response_status = "RESPONDED"
    invitation.response_at = _now()
    rfq.status = "RESPONDING"
    add_audit_log(db, actor_id=user.id, action_type="SUBMIT_QUOTE", resource_type="RFQ", resource_id=rfq.id, request_summary=f"录入供应商 {supplier.supplier_code} 报价", result_status="SUCCESS")
    db.commit()
    return crud.get_by_id(db, rfq.id)


def build_comparison(db: Session, user: User, rfq_id: int) -> QuoteComparison:
    """按各明细最低报价生成一份比价快照。"""

    rfq = get_rfq(db, user, rfq_id)
    quotes = [quote for quote in rfq.quotes if quote.status == "SUBMITTED"]
    if not quotes:
        raise BusinessValidationError("当前询价单还没有可比较的报价")
    comparison = QuoteComparison(
        comparison_no=f"TEMP-C-{rfq.id}-{int(_now().timestamp())}",
        rfq_id=rfq.id,
        created_by=user.id,
        conclusion="按每个询价明细的供应商含税前单价从低到高排序，最终以定标原因为准。",
        status="DRAFT",
    )
    db.add(comparison)
    db.flush()
    comparison.comparison_no = f"QC{date.today():%Y%m%d}{comparison.id:06d}"
    candidates = defaultdict(list)
    for quote in quotes:
        for item in quote.items:
            candidates[item.rfq_item_id].append((quote, item))
    for rfq_item_id, entries in candidates.items():
        entries.sort(key=lambda pair: pair[1].unit_price)
        for rank, (quote, item) in enumerate(entries, start=1):
            comparison.items.append(
                QuoteComparisonItem(
                    quote_id=quote.id,
                    rfq_item_id=rfq_item_id,
                    supplier_id=quote.supplier_id,
                    quoted_unit_price=item.unit_price,
                    total_amount=item.unit_price * item.quoted_quantity,
                    moq_quantity=item.moq_quantity,
                    lead_days=item.lead_days,
                    payment_terms=item.payment_terms,
                    rank_no=rank,
                    selection_flag=1 if rank == 1 else 0,
                    note=item.note,
                )
            )
    add_audit_log(db, actor_id=user.id, action_type="COMPARE", resource_type="RFQ", resource_id=rfq.id, request_summary="生成供应商报价比较结果", result_status="SUCCESS")
    db.commit()
    return crud.get_comparison(db, rfq.id, comparison.id)


def get_latest_comparison(db: Session, user: User, rfq_id: int) -> QuoteComparison:
    """查询询价单最近一次已生成的比价结果。"""

    get_rfq(db, user, rfq_id)
    comparison = crud.get_latest_comparison(db, rfq_id)
    if comparison is None:
        raise ResourceNotFoundError("当前询价单还没有比价结果")
    return comparison


def select_quote(db: Session, user: User, rfq_id: int, data: QuoteSelection, *, commit: bool = True) -> RFQ:
    """确认中选报价，关闭询价单并拒绝其他未中选报价。"""

    # 固定锁序：询价单 -> 比价单；锁定读取刷新已有 identity map。
    db.scalar(select(RFQ).where(RFQ.id == rfq_id).with_for_update().execution_options(populate_existing=True))
    rfq = get_rfq(db, user, rfq_id)
    if rfq.status == "CLOSED":
        raise DuplicateResourceError("询价单已经完成定标，不能重复确认")
    comparison = db.scalar(select(QuoteComparison).where(
        QuoteComparison.id == data.comparison_id, QuoteComparison.rfq_id == rfq.id,
    ).with_for_update().execution_options(populate_existing=True))
    if comparison is None:
        raise ResourceNotFoundError("比价结果不存在")
    if comparison.status != "DRAFT":
        raise DuplicateResourceError("该比价结果已经确认或取消")
    quote = crud.get_quote(db, data.quote_id, for_update=True)
    if quote is None or quote.rfq_id != rfq.id:
        raise BusinessValidationError("中选报价不属于当前询价单")
    if quote.status != "SUBMITTED":
        raise BusinessValidationError("只有已提交的报价可以中选")
    if quote.id not in {item.quote_id for item in comparison.items}:
        raise BusinessValidationError("中选报价不在该比价结果快照中")
    comparison.selected_quote_id = quote.id
    comparison.selection_reason = data.selection_reason
    comparison.status = "CONFIRMED"
    comparison.confirmed_by = user.id
    comparison.confirmed_at = _now()
    for item in comparison.items:
        item.selection_flag = 1 if item.quote_id == quote.id else 0
    for other_quote in rfq.quotes:
        if other_quote.id == quote.id:
            other_quote.status = "SELECTED"
        elif other_quote.status == "SUBMITTED":
            other_quote.status = "REJECTED"
    rfq.status = "CLOSED"
    rfq.closed_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="SELECT_QUOTE", resource_type="RFQ", resource_id=rfq.id, request_summary=f"确认中选报价 {quote.quote_no}", result_status="SUCCESS")
    if commit:
        db.commit()
        return crud.get_by_id(db, rfq.id)
    db.flush()
    return rfq
