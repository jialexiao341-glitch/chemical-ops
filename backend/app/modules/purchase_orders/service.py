"""采购订单生成、审批、下单和取消的业务逻辑。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.purchase_orders import crud
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderApproval, PurchaseOrderEvent, PurchaseOrderItem
from app.modules.purchase_orders.schema import (
    PurchaseOrderApprovalAction,
    PurchaseOrderCancelAction,
    PurchaseOrderCreate,
    PurchaseOrderUpdate,
)
from app.modules.purchase_requests.model import PurchaseRequest, PurchaseRequestItem
from app.modules.rfqs.model import RFQItem, SupplierQuoteItem
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


def _validate_source(db: Session, data: PurchaseOrderCreate):
    """校验比价结果、中选报价和产品明细可以生成采购订单。"""

    comparison = crud.get_comparison(db, data.comparison_id)
    if comparison is None:
        raise ResourceNotFoundError("报价比较结果不存在")
    if comparison.status != "CONFIRMED" or comparison.selected_quote_id != data.quote_id:
        raise BusinessValidationError("只能根据已确认且与中选报价一致的比价结果生成订单")
    quote = crud.get_quote(db, data.quote_id)
    if quote is None:
        raise ResourceNotFoundError("供应商报价不存在")
    if quote.status != "SELECTED" or quote.rfq is None:
        raise BusinessValidationError("报价尚未被确认中选")
    if quote.rfq.source_request_id is None:
        raise BusinessValidationError("只有关联采购申请的询价才能生成订单")
    source_request = db.get(PurchaseRequest, quote.rfq.source_request_id)
    if source_request is None or source_request.status != "APPROVED":
        raise BusinessValidationError("来源采购申请不存在或未审批通过")
    if not quote.items:
        raise BusinessValidationError("中选报价没有报价明细")
    rfq_items = {item.id: item for item in quote.rfq.items}
    quote_items = {item.rfq_item_id: item for item in quote.items}
    if set(rfq_items) != set(quote_items):
        raise BusinessValidationError("中选报价必须覆盖询价单全部明细")
    for rfq_item_id, quote_item in quote_items.items():
        rfq_item = rfq_items[rfq_item_id]
        if rfq_item.product_id is None:
            raise BusinessValidationError(f"询价明细 {rfq_item.line_no} 尚未关联产品主数据，不能生成采购订单")
        request_item = db.get(PurchaseRequestItem, rfq_item.source_request_item_id) if rfq_item.source_request_item_id else None
        if request_item is not None:
            remaining = request_item.quantity - request_item.fulfilled_quantity
            if quote_item.quoted_quantity > remaining:
                raise BusinessValidationError(f"采购申请明细 {request_item.id} 剩余可采购数量不足")
    return comparison, quote, source_request, rfq_items, quote_items


def create_order(db: Session, user: User, data: PurchaseOrderCreate) -> PurchaseOrder:
    """根据已确认的中选报价生成采购订单草稿。"""

    comparison, quote, source_request, rfq_items, quote_items = _validate_source(db, data)
    if not _can_manage_all(db, user) and user.department_id is not None and source_request.department_id != user.department_id:
        raise ResourceNotFoundError("报价来源采购申请不存在")
    existing_order = db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.source_quote_id == quote.id))
    if existing_order is not None:
        raise BusinessValidationError("该中选报价已经生成采购订单，不能重复下单")
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
                planned_arrival_date=data.expected_arrival_date or rfq_item.required_delivery_date,
            )
        )
    order.order_amount = total
    db.add(order)
    db.flush()
    order.po_no = f"PO{date.today():%Y%m%d}{order.id:06d}"
    _add_event(db, order, user.id, "CREATED", None, "DRAFT", "由中选报价生成采购订单草稿")
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary="根据中选报价生成采购订单", result_status="SUCCESS")
    db.commit()
    return _require_order(db, order.id)


def list_orders(db: Session, user: User, *, keyword: str | None, status: str | None, page: int, page_size: int):
    """按用户数据范围分页查询采购订单。"""

    can_manage_all = _can_manage_all(db, user)
    buyer_id = None if can_manage_all or user.department_id is not None else user.id
    department_id = user.department_id if not can_manage_all else None
    return crud.list_page(db, buyer_id=buyer_id, department_id=department_id, keyword=keyword, status=status, page=page, page_size=page_size)


def get_order(db: Session, user: User, order_id: int, *, for_update: bool = False) -> PurchaseOrder:
    """查询订单详情并执行数据范围校验。"""

    order = _require_order(db, order_id, for_update=for_update)
    if not _can_manage_all(db, user) and not ((user.department_id is not None and order.department_id == user.department_id) or (user.department_id is None and order.buyer_id == user.id)):
        raise ResourceNotFoundError(f"采购订单 {order_id} 不存在")
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


def submit_order(db: Session, user: User, order_id: int) -> PurchaseOrder:
    """提交采购订单并创建采购经理审批节点。"""

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
    db.commit()
    return _require_order(db, order.id)


def act_on_order(db: Session, user: User, order_id: int, data: PurchaseOrderApprovalAction, target_status: str) -> PurchaseOrder:
    """处理采购订单审批通过或驳回。"""

    order = get_order(db, user, order_id, for_update=True)
    if order.status != "APPROVING":
        raise BusinessValidationError("只有审批中的采购订单可以处理")
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
