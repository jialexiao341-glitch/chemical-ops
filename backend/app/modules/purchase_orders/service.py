"""采购订单生成、审批、下单和取消的业务逻辑。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.errors import BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.purchase_orders.scope import order_read_condition
from app.modules.purchase_orders import crud
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderApproval, PurchaseOrderEvent, PurchaseOrderItem
from app.modules.purchase_orders.schema import (
    PurchaseOrderApprovalAction,
    PurchaseOrderCancelAction,
    PurchaseOrderCreate,
    PurchaseOrderUpdate,
)
from app.modules.purchase_requests.model import PurchaseRequest, PurchaseRequestItem
from app.modules.purchase_requests.service import get_request as get_scoped_purchase_request
from app.modules.rfqs.model import RFQ, RFQItem, QuoteComparison, SupplierQuoteItem
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    """返回当前本地时间。"""

    return datetime.now()


def _can_manage_all(db: Session, user: User) -> bool:
    """判断用户是否可以查看和处理全部采购订单。"""

    return bool({"SYS_ADMIN", "PROCUREMENT_MANAGER"} & set(get_user_role_codes(db, user.id)))


def _require_order(db: Session, order_id: int, *, for_update: bool = False) -> PurchaseOrder:
    """查询采购订单，不存在时抛出业务异常。"""

    order = crud.get_by_id(db, order_id, for_update=for_update)
    if order is None:
        raise ResourceNotFoundError(f"采购订单 {order_id} 不存在")
    return order


def _validate_request_item_quantities(rfq_items, quote_items, request_items) -> None:
    """对可能拆成多条询价行的同一申请行汇总校验剩余量。"""

    quoted_by_request_item: dict[int, Decimal] = {}
    request_item_by_id = {item.id: item for item in request_items}
    for rfq_item_id, quote_item in quote_items.items():
        request_item_id = rfq_items[rfq_item_id].source_request_item_id
        if request_item_id is None:
            continue
        request_item = request_item_by_id.get(request_item_id)
        if request_item is None:
            raise BusinessValidationError("询价来源采购申请明细不存在")
        quoted_by_request_item[request_item_id] = (
            quoted_by_request_item.get(request_item_id, Decimal("0")) + quote_item.quoted_quantity
        )

    for request_item_id, quoted_quantity in quoted_by_request_item.items():
        request_item = request_item_by_id[request_item_id]
        remaining = request_item.quantity - request_item.fulfilled_quantity
        if quoted_quantity > remaining:
            raise BusinessValidationError(f"采购申请明细 {request_item_id} 剩余可采购数量不足")


def _add_event(db: Session, order: PurchaseOrder, user_id: int, event_type: str, from_status: str | None, to_status: str | None, note: str) -> None:
    """向当前事务追加一条订单事件。"""

    order.events.append(
        PurchaseOrderEvent(
            operator_id=user_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            event_note=note,
        )
    )


def _validate_source(db: Session, user: User, data: PurchaseOrderCreate, *, for_update: bool = True):
    """校验比价结果、中选报价和产品明细可以生成采购订单。"""

    rfq_id = db.scalar(select(QuoteComparison.rfq_id).where(QuoteComparison.id == data.comparison_id))
    if rfq_id is not None:
        rfq_query = select(RFQ).where(RFQ.id == rfq_id)
        db.scalar(rfq_query.with_for_update() if for_update else rfq_query)
    comparison_query = select(QuoteComparison).where(QuoteComparison.id == data.comparison_id).execution_options(populate_existing=True)
    comparison = db.scalar(comparison_query.with_for_update() if for_update else comparison_query)
    if comparison is None:
        raise ResourceNotFoundError("报价比较结果不存在")
    if comparison.status != "CONFIRMED" or comparison.selected_quote_id != data.quote_id:
        raise BusinessValidationError("只能根据已确认且与中选报价一致的比价结果生成订单")
    quote = crud.get_quote(db, data.quote_id, for_update=for_update)
    if quote is None:
        raise ResourceNotFoundError("供应商报价不存在")
    if quote.status != "SELECTED" or quote.rfq is None:
        raise BusinessValidationError("报价尚未被确认中选")
    if quote.rfq.source_request_id is None:
        raise BusinessValidationError("只有关联采购申请的询价才能生成订单")
    source_request = get_scoped_purchase_request(db, user, quote.rfq.source_request_id, for_update=for_update)
    if source_request.status != "APPROVED":
        raise BusinessValidationError("来源采购申请不存在或未审批通过")
    if not quote.items:
        raise BusinessValidationError("中选报价没有报价明细")
    rfq_items = {item.id: item for item in quote.rfq.items}
    quote_items = {item.rfq_item_id: item for item in quote.items}
    if set(rfq_items) != set(quote_items):
        raise BusinessValidationError("中选报价必须覆盖询价单全部明细")
    _validate_request_item_quantities(rfq_items, quote_items, source_request.items)
    for rfq_item_id, quote_item in quote_items.items():
        rfq_item = rfq_items[rfq_item_id]
        if rfq_item.product_id is None:
            raise BusinessValidationError(f"询价明细 {rfq_item.line_no} 尚未关联产品主数据，不能生成采购订单")
    return comparison, quote, source_request, rfq_items, quote_items


def create_order(db: Session, user: User, data: PurchaseOrderCreate, *, commit: bool = True) -> PurchaseOrder:
    """根据已确认的中选报价生成采购订单草稿。"""

    comparison, quote, source_request, rfq_items, quote_items = _validate_source(db, user, data)
    existing_order = db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.source_comparison_id == comparison.id).with_for_update())
    if existing_order is not None:
        raise DuplicateResourceError("该比价结果已经生成采购订单，不能重复下单")
    order = PurchaseOrder(
        po_no=f"TEMP-PO-{user.id}-{int(_now().timestamp())}",
        supplier_id=quote.supplier_id,
        source_comparison_id=comparison.id,
        source_quote_id=quote.id,
        source_request_id=quote.rfq.source_request_id,
        department_id=source_request.department_id,
        buyer_id=user.id,
        currency_code=quote.currency_code,
        delivery_address=data.delivery_address,
        expected_arrival_date=data.expected_arrival_date,
        note=data.note,
        status="DRAFT",
    )
    total = Decimal("0")
    for line_no, rfq_item_id in enumerate(sorted(quote_items, key=lambda value: rfq_items[value].line_no), start=1):
        rfq_item = rfq_items[rfq_item_id]
        quote_item = quote_items[rfq_item_id]
        tax_rate = quote_item.tax_rate or Decimal("0")
        total += quote_item.unit_price * quote_item.quoted_quantity * (Decimal("1") + tax_rate / Decimal("100"))
        order.items.append(
            PurchaseOrderItem(
                line_no=line_no,
                product_id=rfq_item.product_id,
                supplier_product_id=quote_item.supplier_product_id,
                source_quote_item_id=quote_item.id,
                product_name_snapshot=rfq_item.requested_name,
                supplier_model_snapshot=quote_item.supplier_model,
                order_quantity=quote_item.quoted_quantity,
                unit_id=quote_item.unit_id,
                unit_price=quote_item.unit_price,
                tax_rate=quote_item.tax_rate,
                payment_terms_snapshot=quote_item.payment_terms,
                planned_arrival_date=data.expected_arrival_date or rfq_item.required_delivery_date,
            )
        )
    order.order_amount = total
    try:
        # The savepoint lets proposal execution translate a concurrent unique-key
        # collision without rolling back the proposal framework's outer transaction.
        with db.begin_nested():
            db.add(order)
            db.flush()
    except IntegrityError as exc:
        if "uk_purchase_order_comparison" in str(exc.orig):
            raise DuplicateResourceError("该比价结果已经生成采购订单，不能重复下单") from exc
        raise
    order.po_no = f"PO{date.today():%Y%m%d}{order.id:06d}"
    _add_event(db, order, user.id, "CREATED", None, "DRAFT", "由中选报价生成采购订单草稿")
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary="根据中选报价生成采购订单", result_status="SUCCESS")
    db.flush()
    if not commit:
        return order
    db.commit()
    return _require_order(db, order.id)


def list_orders(db: Session, user: User, *, keyword: str | None, status: str | None, page: int, page_size: int):
    """按用户数据范围分页查询采购订单。"""

    scope = order_read_condition(user, get_user_role_codes(db, user.id))
    return crud.list_page(db, scope_condition=scope, keyword=keyword, status=status, page=page, page_size=page_size)


def read_order(db: Session, user: User, order_id: int) -> PurchaseOrder:
    """读取订单来源；写操作继续使用 get_order 的采购范围。"""
    order = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == order_id, order_read_condition(user, get_user_role_codes(db, user.id))))
    if order is None:
        raise ResourceNotFoundError(f"采购订单 {order_id} 不存在")
    return order


def _assert_order_scope(db: Session, user: User, order: PurchaseOrder) -> None:
    if not _can_manage_all(db, user) and order.buyer_id != user.id:
        raise ResourceNotFoundError(f"采购订单 {order.id} 不存在")
    from app.modules.system.data_scope import department_scope_condition
    from sqlalchemy import literal
    roles = get_user_role_codes(db, user.id)
    if not db.scalar(select(department_scope_condition(user, roles, literal(order.department_id)))):
        raise ResourceNotFoundError(f"采购订单 {order.id} 不存在")


def get_order(db: Session, user: User, order_id: int, *, for_update: bool = False) -> PurchaseOrder:
    """查询订单详情并执行数据范围校验。"""

    order = _require_order(db, order_id, for_update=for_update)
    _assert_order_scope(db, user, order)
    return order


def get_order_by_no(db: Session, user: User, po_no: str, *, for_update: bool = False) -> PurchaseOrder:
    """按准确订单号读取订单并执行与详情一致的数据范围校验。"""

    statement = select(PurchaseOrder).where(PurchaseOrder.po_no == po_no)
    if for_update:
        statement = statement.with_for_update()
    order = db.scalar(statement)
    if order is None:
        raise ResourceNotFoundError(f"采购订单 {po_no} 不存在")
    _assert_order_scope(db, user, order)
    return order


def update_order(db: Session, user: User, order_id: int, data: PurchaseOrderUpdate) -> PurchaseOrder:
    """更新采购订单草稿。"""

    order = get_order(db, user, order_id, for_update=True)
    if order.status != "DRAFT":
        raise BusinessValidationError("只有草稿状态的采购订单可以修改")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(order, key, value)
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary="更新采购订单草稿", result_status="SUCCESS")
    db.commit()
    return _require_order(db, order.id)


def submit_order(db: Session, user: User, order_id: int, *, commit: bool = True) -> PurchaseOrder:
    """提交采购订单并创建采购经理审批节点；可由调用方在同一事务内提交。"""

    order = get_order(db, user, order_id, for_update=True)
    if order.status != "DRAFT":
        raise BusinessValidationError("只有草稿状态的采购订单可以提交")
    if not order.items:
        raise BusinessValidationError("采购订单必须包含明细")
    previous = order.status
    order.status = "APPROVING"
    approval = db.scalar(
        select(PurchaseOrderApproval).where(PurchaseOrderApproval.po_id == order.id, PurchaseOrderApproval.sequence_no == 1)
    )
    if approval is None:
        order.approvals.append(PurchaseOrderApproval(sequence_no=1, node_code="PROCUREMENT_MANAGER", node_name="采购经理审批", action="PENDING"))
    else:
        approval.action = "PENDING"
        approval.approver_id = None
        approval.opinion = None
        approval.acted_at = None
    _add_event(db, order, user.id, "SUBMITTED", previous, "APPROVING", "提交采购订单审批")
    add_audit_log(db, actor_id=user.id, action_type="SUBMIT", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary="提交采购订单审批", result_status="SUCCESS")
    if commit:
        db.commit()
    else:
        db.flush()
    return _require_order(db, order.id)


def act_on_order(db: Session, user: User, order_id: int, data: PurchaseOrderApprovalAction, target_status: str) -> PurchaseOrder:
    """处理采购订单审批通过或驳回。"""

    order = get_order(db, user, order_id, for_update=True)
    if order.status != "APPROVING":
        raise BusinessValidationError("只有审批中的采购订单可以处理")
    if order.buyer_id == user.id:
        raise BusinessValidationError("不能审批本人经办的采购订单")
    approval = crud.get_pending_approval(db, order.id, for_update=True)
    if approval is None:
        raise BusinessValidationError("当前订单没有待处理审批节点")
    approval.action = "APPROVED" if target_status == "APPROVED" else "REJECTED"
    approval.approver_id = user.id
    approval.opinion = data.opinion
    approval.acted_at = _now()
    previous = order.status
    order.status = target_status
    if target_status == "APPROVED":
        order.approved_at = _now()
    _add_event(db, order, user.id, approval.action, previous, target_status, data.opinion or "处理采购订单审批")
    add_audit_log(db, actor_id=user.id, action_type=approval.action, resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary="处理采购订单审批", result_status="SUCCESS")
    db.commit()
    return _require_order(db, order.id)


def place_order(db: Session, user: User, order_id: int) -> PurchaseOrder:
    """将已审批订单置为已下单，并回写采购申请已采购数量。"""

    order = get_order(db, user, order_id, for_update=True)
    if order.status != "APPROVED":
        raise BusinessValidationError("只有已审批的采购订单可以下单")
    previous = order.status
    order.status = "ORDERED"
    order.order_date = date.today()
    for item in order.items:
        source = db.scalar(select(SupplierQuoteItem).where(SupplierQuoteItem.id == item.source_quote_item_id)) if item.source_quote_item_id else None
        if source is None:
            continue
        rfq_item = db.get(RFQItem, source.rfq_item_id)
        if rfq_item and rfq_item.source_request_item_id:
            request_item = db.get(PurchaseRequestItem, rfq_item.source_request_item_id)
            if request_item:
                request_item.fulfilled_quantity += item.order_quantity
                request_item.status = "FULFILLED" if request_item.fulfilled_quantity >= request_item.quantity else "PARTIAL"
    _add_event(db, order, user.id, "ORDERED", previous, "ORDERED", "采购订单正式下单")
    add_audit_log(db, actor_id=user.id, action_type="PLACE", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary="采购订单正式下单", result_status="SUCCESS")
    db.commit()
    return _require_order(db, order.id)


def cancel_order(db: Session, user: User, order_id: int, data: PurchaseOrderCancelAction) -> PurchaseOrder:
    """取消尚未下单或执行中的采购订单。"""

    order = get_order(db, user, order_id, for_update=True)
    if order.status not in {"DRAFT", "APPROVING", "APPROVED"}:
        raise BusinessValidationError("当前订单状态不允许取消")
    previous = order.status
    order.status = "CANCELLED"
    order.cancelled_at = _now()
    order.cancel_reason = data.reason
    _add_event(db, order, user.id, "CANCELLED", previous, "CANCELLED", data.reason)
    add_audit_log(db, actor_id=user.id, action_type="CANCEL", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary="取消采购订单", result_status="SUCCESS")
    db.commit()
    return _require_order(db, order.id)
