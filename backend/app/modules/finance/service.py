"""财务对账、发票、付款和结算的业务逻辑。"""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.deliveries.model import Delivery
from app.modules.finance import crud
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceSettlement
from app.modules.finance.schema import InvoiceCreate, PaymentCreate, SettlementCreate
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_orders import service as order_service
from app.modules.purchase_orders.scope import order_read_condition
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    """返回当前本地时间。"""

    return datetime.now()


def _require_reconciliation(db: Session, reconciliation_id: int, *, for_update: bool = False) -> FinanceReconciliation:
    """查询对账单，不存在时返回中文 404。"""

    reconciliation = crud.get_reconciliation(db, reconciliation_id, for_update=for_update)
    if reconciliation is None:
        raise ResourceNotFoundError(f"对账单 {reconciliation_id} 不存在")
    return reconciliation


def _require_invoice(db: Session, invoice_id: int, *, for_update: bool = False) -> FinanceInvoice:
    """查询发票，不存在时返回中文 404。"""

    invoice = crud.get_invoice(db, invoice_id, for_update=for_update)
    if invoice is None:
        raise ResourceNotFoundError(f"发票记录 {invoice_id} 不存在")
    return invoice


def _require_payment(db: Session, payment_id: int, *, for_update: bool = False) -> FinancePayment:
    """查询付款记录，不存在时返回中文 404。"""

    payment = crud.get_payment(db, payment_id, for_update=for_update)
    if payment is None:
        raise ResourceNotFoundError(f"付款记录 {payment_id} 不存在")
    return payment


def _require_settlement(db: Session, settlement_id: int, *, for_update: bool = False) -> FinanceSettlement:
    """查询结算单，不存在时返回中文 404。"""

    settlement = crud.get_settlement(db, settlement_id, for_update=for_update)
    if settlement is None:
        raise ResourceNotFoundError(f"结算单 {settlement_id} 不存在")
    return settlement


def _require_finance_scope(db: Session, user: User, po_id: int) -> None:
    order_service.read_order(db, user, po_id)


def _scope_condition(db: Session, user: User, model):
    visible_orders = select(PurchaseOrder.id).where(order_read_condition(user, get_user_role_codes(db, user.id)))
    return model.po_id.in_(visible_orders)


def _lock_order(db: Session, po_id: int) -> PurchaseOrder:
    """锁定采购订单，防止并发创建重复对账单。"""

    order = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update().execution_options(populate_existing=True))
    if order is None:
        raise ResourceNotFoundError(f"采购订单 {po_id} 不存在")
    return order


def _check_order_ready_for_reconciliation(db: Session, order: PurchaseOrder) -> None:
    """校验订单已完成收货且所有到货单已通过质量验收。"""

    if order.status != "COMPLETED":
        raise BusinessValidationError("只有已完成收货的采购订单可以创建对账单")
    deliveries = list(db.scalars(select(Delivery).where(Delivery.po_id == order.id).with_for_update().execution_options(populate_existing=True)).all())
    if not deliveries or any(delivery.status != "ACCEPTED" for delivery in deliveries):
        raise BusinessValidationError("采购订单必须全部完成质量验收后才能创建对账单")


def _sum_invoices(db: Session, reconciliation_id: int, *, verified_only: bool = False) -> Decimal:
    """统计对账单的有效发票金额。"""

    statuses = ["VERIFIED"] if verified_only else ["DRAFT", "SUBMITTED", "VERIFIED"]
    # 使用当前锁定读，避免等待主单锁后仍从旧事务快照统计占用额度。
    values = db.scalars(select(FinanceInvoice.amount_incl_tax).where(FinanceInvoice.reconciliation_id == reconciliation_id, FinanceInvoice.status.in_(statuses)).with_for_update()).all()
    return sum(values, Decimal(0))


def _sum_payments(db: Session, reconciliation_id: int, *, paid_only: bool = False) -> Decimal:
    """统计付款申请或实际付款金额。"""

    statuses = ["PAID"] if paid_only else ["REQUESTED", "APPROVED", "PAID"]
    value = db.scalar(select(func.coalesce(func.sum(FinancePayment.amount), 0)).where(FinancePayment.reconciliation_id == reconciliation_id, FinancePayment.status.in_(statuses)))
    return Decimal(value or 0)


def create_reconciliation(db: Session, user: User, po_id: int, note: str | None) -> FinanceReconciliation:
    """为已完成并验收通过的采购订单创建对账单。"""

    _require_finance_scope(db, user, po_id)
    order = _lock_order(db, po_id)
    _check_order_ready_for_reconciliation(db, order)
    if db.scalar(select(FinanceReconciliation).where(FinanceReconciliation.po_id == po_id)) is not None:
        raise DuplicateResourceError(f"采购订单 {po_id} 已经存在对账单")
    reconciliation = FinanceReconciliation(
        reconciliation_no=f"TEMP-FR-{uuid4().hex[:12]}",
        po_id=order.id,
        supplier_id=order.supplier_id,
        currency_code=order.currency_code,
        total_amount=order.order_amount,
        status="DRAFT",
        created_by=user.id,
        note=note,
    )
    db.add(reconciliation)
    db.flush()
    reconciliation.reconciliation_no = f"FR{date.today():%Y%m%d}{reconciliation.id:06d}"
    from app.modules.finance.reconciliation_items import append_basis
    from app.modules.finance.schema import ReconciliationItemsRefresh
    append_basis(db, user, reconciliation, order, ReconciliationItemsRefresh())
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="FINANCE_RECONCILIATION", resource_id=reconciliation.id, request_summary="创建财务对账单", result_status="SUCCESS")
    db.commit()
    return _require_reconciliation(db, reconciliation.id)


def list_reconciliations(db: Session, user: User, *, status: str | None, supplier_id: int | None, page: int, page_size: int):
    """按权限范围分页查询对账单。"""

    return crud.list_reconciliations(db, scope_condition=_scope_condition(db, user, FinanceReconciliation), status=status, supplier_id=supplier_id, page=page, page_size=page_size)


def get_reconciliation(db: Session, user: User, reconciliation_id: int) -> FinanceReconciliation:
    """查询对账单详情并执行数据范围校验。"""

    reconciliation = _require_reconciliation(db, reconciliation_id)
    _require_finance_scope(db, user, reconciliation.po_id)
    return reconciliation


def confirm_reconciliation(db: Session, user: User, reconciliation_id: int, reason: str | None) -> FinanceReconciliation:
    """确认对账单，允许后续发起付款申请。"""

    reconciliation = _require_reconciliation(db, reconciliation_id, for_update=True)
    _require_finance_scope(db, user, reconciliation.po_id)
    if reconciliation.status not in {"DRAFT", "DISPUTED"}:
        raise BusinessValidationError("只有草稿或争议中的对账单可以确认")
    order = _lock_order(db, reconciliation.po_id)
    _check_order_ready_for_reconciliation(db, order)
    from app.modules.finance.reconciliation_items import validate_for_confirmation
    validate_for_confirmation(db, reconciliation, order)
    reconciliation.status = "CONFIRMED"
    reconciliation.confirmed_by = user.id
    reconciliation.confirmed_at = _now()
    if reason:
        reconciliation.note = reason
    add_audit_log(db, actor_id=user.id, action_type="CONFIRM", resource_type="FINANCE_RECONCILIATION", resource_id=reconciliation.id, request_summary="确认财务对账单", result_status="SUCCESS")
    db.commit()
    return _require_reconciliation(db, reconciliation.id)


def dispute_reconciliation(db: Session, user: User, reconciliation_id: int, reason: str) -> FinanceReconciliation:
    """将对账单标记为争议状态并保留原因。"""

    reconciliation = _require_reconciliation(db, reconciliation_id, for_update=True)
    _require_finance_scope(db, user, reconciliation.po_id)
    if reconciliation.status not in {"DRAFT", "CONFIRMED"}:
        raise BusinessValidationError("当前状态不允许发起对账争议")
    reconciliation.status = "DISPUTED"
    reconciliation.note = reason
    add_audit_log(db, actor_id=user.id, action_type="DISPUTE", resource_type="FINANCE_RECONCILIATION", resource_id=reconciliation.id, request_summary="发起财务对账争议", result_status="SUCCESS")
    db.commit()
    return _require_reconciliation(db, reconciliation.id)


def create_invoice(db: Session, user: User, data: InvoiceCreate) -> FinanceInvoice:
    """为对账单录入发票，并校验发票金额不超过对账金额。"""

    reconciliation = _require_reconciliation(db, data.reconciliation_id, for_update=True)
    _require_finance_scope(db, user, reconciliation.po_id)
    if reconciliation.status in {"CLOSED", "CANCELLED"}:
        raise BusinessValidationError("已关闭或已取消的对账单不能录入发票")
    if data.amount_incl_tax != data.amount_excl_tax + data.tax_amount:
        raise BusinessValidationError("价税合计必须等于不含税金额加税额")
    if _sum_invoices(db, reconciliation.id) + data.amount_incl_tax > reconciliation.total_amount:
        raise BusinessValidationError("发票累计金额不能超过对账应付总额")
    invoice = FinanceInvoice(
        invoice_no=f"TEMP-FI-{uuid4().hex[:12]}",
        reconciliation_id=reconciliation.id,
        po_id=reconciliation.po_id,
        supplier_id=reconciliation.supplier_id,
        invoice_code=data.invoice_code,
        invoice_number=data.invoice_number,
        invoice_date=data.invoice_date,
        amount_excl_tax=data.amount_excl_tax,
        tax_amount=data.tax_amount,
        amount_incl_tax=data.amount_incl_tax,
        currency_code=reconciliation.currency_code,
        status="DRAFT",
        source_file_id=data.source_file_id,
        submitted_by=user.id,
        note=data.note,
    )
    db.add(invoice)
    db.flush()
    invoice.invoice_no = f"FI{date.today():%Y%m%d}{invoice.id:06d}"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="FINANCE_INVOICE", resource_id=invoice.id, request_summary="录入供应商发票", result_status="SUCCESS")
    db.commit()
    return _require_invoice(db, invoice.id)


def list_invoices(db: Session, user: User, *, reconciliation_id: int | None, status: str | None, page: int, page_size: int):
    """分页查询发票。"""

    return crud.list_invoices(db, scope_condition=_scope_condition(db, user, FinanceInvoice), reconciliation_id=reconciliation_id, status=status, page=page, page_size=page_size)


def submit_invoice(db: Session, user: User, invoice_id: int) -> FinanceInvoice:
    """提交发票进入财务核验。"""

    invoice = get_invoice(db, user, invoice_id)
    reconciliation = _require_reconciliation(db, invoice.reconciliation_id, for_update=True)
    invoice = _require_invoice(db, invoice_id, for_update=True)
    _require_finance_scope(db, user, invoice.po_id)
    if invoice.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的发票可以提交核验")
    from app.modules.finance.invoice_matches import validate_transition
    validate_transition(db, user, invoice, reconciliation)
    invoice.status = "SUBMITTED"
    invoice.submitted_by = user.id
    invoice.reject_reason = None
    from app.modules.insights.finance_checks import reopen_for_invoice_change
    reopen_for_invoice_change(db, user, invoice)
    add_audit_log(db, actor_id=user.id, action_type="SUBMIT", resource_type="FINANCE_INVOICE", resource_id=invoice.id, request_summary="提交发票核验", result_status="SUCCESS")
    db.commit()
    return _require_invoice(db, invoice.id)


def verify_invoice(db: Session, user: User, invoice_id: int) -> FinanceInvoice:
    """记录内部人工复核；当前不调用税务平台。"""

    invoice = get_invoice(db, user, invoice_id)
    reconciliation = _require_reconciliation(db, invoice.reconciliation_id, for_update=True)
    invoice = _require_invoice(db, invoice_id, for_update=True)
    _require_finance_scope(db, user, invoice.po_id)
    if invoice.status != "SUBMITTED":
        raise BusinessValidationError("只有已提交的发票可以核验")
    if invoice.submitted_by == user.id:
        raise BusinessValidationError("不能复核本人经办的发票")
    from app.modules.finance.invoice_matches import validate_transition
    validate_transition(db, user, invoice, reconciliation, verifying=True)
    invoice.status = "VERIFIED"
    invoice.verified_by = user.id
    invoice.verified_at = _now()
    from app.modules.insights.finance_checks import reopen_for_invoice_change
    reopen_for_invoice_change(db, user, invoice)
    add_audit_log(db, actor_id=user.id, action_type="VERIFY", resource_type="FINANCE_INVOICE", resource_id=invoice.id, request_summary="人工复核发票通过", result_status="SUCCESS")
    db.commit()
    return _require_invoice(db, invoice.id)


def reject_invoice(db: Session, user: User, invoice_id: int, reason: str) -> FinanceInvoice:
    """驳回发票并记录可供前端展示的原因。"""

    invoice = get_invoice(db, user, invoice_id)
    _require_reconciliation(db, invoice.reconciliation_id, for_update=True)
    invoice = _require_invoice(db, invoice_id, for_update=True)
    _require_finance_scope(db, user, invoice.po_id)
    if invoice.status != "SUBMITTED":
        raise BusinessValidationError("只有已提交的发票可以驳回")
    if invoice.submitted_by == user.id:
        raise BusinessValidationError("不能复核本人经办的发票")
    invoice.status = "REJECTED"
    invoice.reject_reason = reason
    from app.modules.insights.finance_checks import reopen_for_invoice_change
    reopen_for_invoice_change(db, user, invoice)
    add_audit_log(db, actor_id=user.id, action_type="REJECT", resource_type="FINANCE_INVOICE", resource_id=invoice.id, request_summary=f"驳回发票：{reason}", result_status="SUCCESS")
    db.commit()
    return _require_invoice(db, invoice.id)


def get_invoice(db: Session, user: User, invoice_id: int) -> FinanceInvoice:
    """查询发票详情。"""

    value = _require_invoice(db, invoice_id)
    _require_finance_scope(db, user, value.po_id)
    return value


def create_payment(db: Session, user: User, data: PaymentCreate) -> FinancePayment:
    """对已确认对账单发起付款申请。"""

    reconciliation = _require_reconciliation(db, data.reconciliation_id, for_update=True)
    _require_finance_scope(db, user, reconciliation.po_id)
    if reconciliation.status != "CONFIRMED":
        raise BusinessValidationError("只有已确认的对账单可以发起付款")
    if _sum_payments(db, reconciliation.id) + data.amount > reconciliation.total_amount:
        raise BusinessValidationError("付款累计金额不能超过对账应付总额")
    if _sum_invoices(db, reconciliation.id, verified_only=True) < data.amount:
        raise BusinessValidationError("人工复核通过的发票金额不足，不能发起本次付款")
    payment = FinancePayment(
        payment_no=f"TEMP-FP-{uuid4().hex[:12]}",
        reconciliation_id=reconciliation.id,
        po_id=reconciliation.po_id,
        supplier_id=reconciliation.supplier_id,
        amount=data.amount,
        currency_code=reconciliation.currency_code,
        payment_method=data.payment_method,
        status="REQUESTED",
        requested_by=user.id,
        note=data.note,
    )
    db.add(payment)
    db.flush()
    payment.payment_no = f"FP{date.today():%Y%m%d}{payment.id:06d}"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="FINANCE_PAYMENT", resource_id=payment.id, request_summary="发起付款申请", result_status="SUCCESS")
    db.commit()
    return _require_payment(db, payment.id)


def list_payments(db: Session, user: User, *, reconciliation_id: int | None, status: str | None, page: int, page_size: int):
    """分页查询付款记录。"""

    return crud.list_payments(db, scope_condition=_scope_condition(db, user, FinancePayment), reconciliation_id=reconciliation_id, status=status, page=page, page_size=page_size)


def approve_payment(db: Session, user: User, payment_id: int) -> FinancePayment:
    """审批付款申请，并再次校验已核验发票和金额上限。"""

    payment = _require_payment(db, payment_id)
    _require_finance_scope(db, user, payment.po_id)
    reconciliation = _require_reconciliation(db, payment.reconciliation_id, for_update=True)
    _require_finance_scope(db, user, reconciliation.po_id)
    payment = _require_payment(db, payment_id, for_update=True)
    _require_finance_scope(db, user, payment.po_id)
    if payment.status != "REQUESTED":
        raise BusinessValidationError("只有待审批付款可以审批")
    if payment.requested_by == user.id:
        raise BusinessValidationError("不能审批本人经办的付款申请")
    if reconciliation.status != "CONFIRMED":
        raise BusinessValidationError("对账单未确认，不能审批付款")
    if _sum_invoices(db, reconciliation.id, verified_only=True) < payment.amount:
        raise BusinessValidationError("人工复核通过的发票金额不足，不能审批付款")
    payment.status = "APPROVED"
    payment.approved_by = user.id
    payment.approved_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="APPROVE", resource_type="FINANCE_PAYMENT", resource_id=payment.id, request_summary="审批付款申请", result_status="SUCCESS")
    db.commit()
    return _require_payment(db, payment.id)


def reject_payment(db: Session, user: User, payment_id: int, reason: str) -> FinancePayment:
    """驳回付款申请。"""

    payment = _require_payment(db, payment_id, for_update=True)
    _require_finance_scope(db, user, payment.po_id)
    if payment.status != "REQUESTED":
        raise BusinessValidationError("只有待审批付款可以驳回")
    if payment.requested_by == user.id:
        raise BusinessValidationError("不能审批本人经办的付款申请")
    payment.status = "REJECTED"
    payment.reject_reason = reason
    add_audit_log(db, actor_id=user.id, action_type="REJECT", resource_type="FINANCE_PAYMENT", resource_id=payment.id, request_summary=f"驳回付款申请：{reason}", result_status="SUCCESS")
    db.commit()
    return _require_payment(db, payment.id)


def mark_payment_paid(db: Session, user: User, payment_id: int, transaction_ref: str, note: str | None) -> FinancePayment:
    """登记人工核对的付款结果；不表示银行已与系统直连。"""

    payment = _require_payment(db, payment_id, for_update=True)
    _require_finance_scope(db, user, payment.po_id)
    if payment.status != "APPROVED":
        raise BusinessValidationError("只有已审批付款可以登记付款结果")
    duplicate = db.scalar(select(FinancePayment).where(FinancePayment.transaction_ref == transaction_ref, FinancePayment.id != payment.id))
    if duplicate is not None:
        raise DuplicateResourceError("银行流水号已经登记过")
    payment.status = "PAID"
    payment.paid_by = user.id
    payment.paid_at = _now()
    payment.transaction_ref = transaction_ref
    if note:
        payment.note = note
    add_audit_log(db, actor_id=user.id, action_type="PAY", resource_type="FINANCE_PAYMENT", resource_id=payment.id, request_summary="人工登记付款结果", result_status="SUCCESS")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateResourceError("银行流水号已经登记过") from exc
    return _require_payment(db, payment.id)


def get_payment(db: Session, user: User, payment_id: int) -> FinancePayment:
    """查询付款详情。"""

    value = _require_payment(db, payment_id)
    _require_finance_scope(db, user, value.po_id)
    return value


def create_settlement(db: Session, user: User, data: SettlementCreate) -> FinanceSettlement:
    """为已足额付款的对账单创建结算单。"""

    reconciliation = _require_reconciliation(db, data.reconciliation_id, for_update=True)
    _require_finance_scope(db, user, reconciliation.po_id)
    if reconciliation.status != "CONFIRMED":
        raise BusinessValidationError("只有已确认且未关闭的对账单可以创建结算单")
    if _sum_payments(db, reconciliation.id, paid_only=True) < reconciliation.total_amount:
        raise BusinessValidationError("实际付款未达到对账应付总额，不能结算")
    if crud.get_settlement(db, reconciliation.id) is not None:
        raise DuplicateResourceError("该对账单已经存在结算单")
    settlement = FinanceSettlement(
        settlement_no=f"TEMP-FS-{uuid4().hex[:12]}",
        reconciliation_id=reconciliation.id,
        po_id=reconciliation.po_id,
        supplier_id=reconciliation.supplier_id,
        settlement_amount=reconciliation.total_amount,
        currency_code=reconciliation.currency_code,
        status="DRAFT",
        created_by=user.id,
        note=data.note,
    )
    db.add(settlement)
    db.flush()
    settlement.settlement_no = f"FS{date.today():%Y%m%d}{settlement.id:06d}"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="FINANCE_SETTLEMENT", resource_id=settlement.id, request_summary="创建采购结算单", result_status="SUCCESS")
    db.commit()
    return _require_settlement(db, settlement.id)


def list_settlements(db: Session, user: User, *, status: str | None, supplier_id: int | None, page: int, page_size: int):
    """分页查询结算单。"""

    return crud.list_settlements(db, scope_condition=_scope_condition(db, user, FinanceSettlement), status=status, supplier_id=supplier_id, page=page, page_size=page_size)


def confirm_settlement(db: Session, user: User, settlement_id: int) -> FinanceSettlement:
    """确认结算单并原子关闭对账单。"""

    settlement = _require_settlement(db, settlement_id)
    _require_finance_scope(db, user, settlement.po_id)
    reconciliation = _require_reconciliation(db, settlement.reconciliation_id, for_update=True)
    _require_finance_scope(db, user, reconciliation.po_id)
    settlement = _require_settlement(db, settlement_id, for_update=True)
    _require_finance_scope(db, user, settlement.po_id)
    if settlement.status != "DRAFT":
        raise BusinessValidationError("只有草稿结算单可以确认")
    if settlement.created_by == user.id:
        raise BusinessValidationError("不能确认本人经办的结算单")
    if reconciliation.status != "CONFIRMED" or _sum_payments(db, reconciliation.id, paid_only=True) < reconciliation.total_amount:
        raise BusinessValidationError("对账单未完成足额付款，不能确认结算")
    settlement.status = "CONFIRMED"
    settlement.confirmed_by = user.id
    settlement.confirmed_at = _now()
    reconciliation.status = "CLOSED"
    reconciliation.closed_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="CONFIRM", resource_type="FINANCE_SETTLEMENT", resource_id=settlement.id, request_summary="确认采购结算并关闭对账", result_status="SUCCESS")
    db.commit()
    return _require_settlement(db, settlement.id)


def cancel_settlement(db: Session, user: User, settlement_id: int, reason: str) -> FinanceSettlement:
    """取消尚未确认的结算单。"""

    settlement = _require_settlement(db, settlement_id, for_update=True)
    _require_finance_scope(db, user, settlement.po_id)
    if settlement.status != "DRAFT":
        raise BusinessValidationError("只有草稿结算单可以取消")
    settlement.status = "CANCELLED"
    settlement.cancelled_at = _now()
    settlement.cancel_reason = reason
    add_audit_log(db, actor_id=user.id, action_type="CANCEL", resource_type="FINANCE_SETTLEMENT", resource_id=settlement.id, request_summary=f"取消采购结算：{reason}", result_status="SUCCESS")
    db.commit()
    return _require_settlement(db, settlement.id)


def get_settlement(db: Session, user: User, settlement_id: int) -> FinanceSettlement:
    """查询结算单详情。"""

    value = _require_settlement(db, settlement_id)
    _require_finance_scope(db, user, value.po_id)
    return value
