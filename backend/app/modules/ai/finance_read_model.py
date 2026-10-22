"""只读财务对账视图，供 Agent 工具和页面上下文共用。"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError
from app.modules.finance import invoice_matches, reconciliation_items
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation
from app.modules.finance.service import get_reconciliation
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


def read_reconciliation(db: Session, user: User, reconciliation: FinanceReconciliation) -> dict:
    """按财务详情权限复用行级对账与发票匹配口径，生成只读汇总。"""
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    required = {"finance.reconciliations.read", "finance.invoices.read", "finance.payments.read"}
    if "SYS_ADMIN" not in roles and not required.issubset(permissions):
        raise AuthorizationError("当前账号没有完整的财务对账读取权限")

    reconciliation = get_reconciliation(db, user, reconciliation.id)
    saved = reconciliation_items.read_items(db, user, reconciliation.id)
    invoice_lines, unallocated_invoices = invoice_matches.line_summary(db, reconciliation)
    invoice_rows = db.execute(select(
        FinanceInvoice.status.label("status"), func.count(FinanceInvoice.id).label("count"),
        func.coalesce(func.sum(FinanceInvoice.amount_incl_tax), 0).label("amount"),
    ).where(FinanceInvoice.reconciliation_id == reconciliation.id).group_by(FinanceInvoice.status)).mappings().all()
    payment_rows = db.execute(select(
        FinancePayment.status.label("status"), func.count(FinancePayment.id).label("count"),
        func.coalesce(func.sum(FinancePayment.amount), 0).label("amount"),
    ).where(FinancePayment.reconciliation_id == reconciliation.id).group_by(FinancePayment.status)).mappings().all()
    invoices = [dict(row) for row in invoice_rows]
    payments = [dict(row) for row in payment_rows]
    verified_invoice_amount = sum(
        (Decimal(str(row["amount"])) for row in invoices if row["status"] == "VERIFIED"), Decimal(0)
    )
    active_payment_amount = sum(
        (Decimal(str(row["amount"])) for row in payments if row["status"] in {"REQUESTED", "APPROVED", "PAID"}),
        Decimal(0),
    )
    remaining_reconciliation_amount = max(Decimal(0), reconciliation.total_amount - active_payment_amount)
    blockers = []
    if reconciliation.status != "CONFIRMED":
        blockers.append("对账单尚未确认")
    if verified_invoice_amount <= 0:
        blockers.append("当前没有已核验发票")
    if remaining_reconciliation_amount <= 0:
        blockers.append("对账金额已被现有付款申请或付款占满")
    max_new_payment_amount = (
        min(verified_invoice_amount, remaining_reconciliation_amount)
        if not blockers else Decimal(0)
    )

    line_rows = []
    match_by_id = {row["reconciliation_item_id"]: row for row in invoice_lines}
    for item in saved.items:
        match = match_by_id.get(item.id, {})
        line_rows.append({
            "reconciliation_item_id": item.id,
            "line_no": item.line_no,
            "product_name": item.product_name,
            "unit_name": item.unit_name,
            "ordered_quantity": item.ordered_quantity,
            "received_quantity": item.received_quantity,
            "accepted_quantity": item.accepted_quantity,
            "returned_quantity": item.returned_quantity,
            "reconciliation_quantity": item.reconciliation_quantity,
            "amount_incl_tax": item.amount_incl_tax,
            "invoiced_reserved_amount": Decimal(str(match.get("reserved_amount", "0"))),
            "verified_invoice_amount": Decimal(str(match.get("verified_amount", "0"))),
            "unmatched_invoice_capacity": Decimal(str(match.get("remaining_amount", item.amount_incl_tax))),
            "warnings": list(item.warnings or []),
        })

    return {
        "reconciliation": reconciliation,
        "version_no": saved.version_no,
        "source_changed": saved.source_changed,
        "line_warnings": list(saved.warnings),
        "lines": line_rows,
        "unallocated_invoices": list(unallocated_invoices),
        "invoices": invoices,
        "payments": payments,
        "payment_precheck": {
            "reconciliation_confirmed": reconciliation.status == "CONFIRMED",
            "verified_invoice_amount": verified_invoice_amount,
            "active_payment_amount": active_payment_amount,
            "remaining_reconciliation_amount": remaining_reconciliation_amount,
            "max_new_payment_amount": max_new_payment_amount,
            "currency_code": reconciliation.currency_code,
            "blockers": blockers,
            "limitation": "未提供拟付款金额；此处仅按发起付款服务现有金额上限规则计算当前理论上限，提交与审批时仍由领域服务重新校验。",
        },
    }
