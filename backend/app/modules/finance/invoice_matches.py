"""发票人工行匹配：保存证据版本、确定性差异和提交时重新校验。"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError
from app.modules.finance.model import FinanceInvoice, FinanceInvoiceMatch, FinanceReconciliationItem
from app.modules.finance.reconciliation_items import basis_hash, collect_basis
from app.modules.finance.schema import InvoiceMatchRead, InvoiceMatchSave
from app.modules.system.audit import add_audit_log

ACTIVE = {"DRAFT", "SUBMITTED", "VERIFIED"}


def latest(db, invoice_id, *, for_update=False):
    statement = select(FinanceInvoiceMatch).where(FinanceInvoiceMatch.invoice_id == invoice_id).order_by(FinanceInvoiceMatch.version_no.desc()).limit(1)
    return db.scalar(statement.with_for_update().execution_options(populate_existing=True) if for_update else statement)


def line_summary(db, rec, exclude_invoice_id=None, *, for_update=False):
    rows = db.scalars(select(FinanceReconciliationItem).where(FinanceReconciliationItem.reconciliation_id == rec.id, FinanceReconciliationItem.version_no == rec.items_version).order_by(FinanceReconciliationItem.line_no)).all()
    totals = {row.id: {"reserved": Decimal(0), "verified": Decimal(0)} for row in rows}
    unallocated = []
    statement = select(FinanceInvoice).where(FinanceInvoice.reconciliation_id == rec.id, FinanceInvoice.status.in_(ACTIVE), FinanceInvoice.id != (exclude_invoice_id or 0)).order_by(FinanceInvoice.id)
    invoices = db.scalars(statement.with_for_update().execution_options(populate_existing=True) if for_update else statement).all()
    for invoice in invoices:
        match = latest(db, invoice.id, for_update=for_update)
        if invoice.currency_code != rec.currency_code:
            unallocated.append(invoice.invoice_no + "（币种不一致）")
            continue
        if not match or match.reconciliation_version != rec.items_version:
            unallocated.append(invoice.invoice_no)
            continue
        for allocation in match.allocations:
            total = totals.get(allocation["reconciliation_item_id"])
            if total is not None:
                amount = Decimal(allocation["amount_excl_tax"]) + Decimal(allocation["tax_amount"])
                total["reserved"] += amount
                if invoice.status == "VERIFIED":
                    total["verified"] += amount
    return [{"reconciliation_item_id": row.id, "po_item_id": row.po_item_id, "line_no": row.line_no, "product_name": row.product_name, "amount_excl_tax": str(row.amount_excl_tax), "tax_amount": str(row.tax_amount), "amount_incl_tax": str(row.amount_incl_tax), "reserved_amount": str(totals[row.id]["reserved"]), "verified_amount": str(totals[row.id]["verified"]), "remaining_amount": str(row.amount_incl_tax - totals[row.id]["reserved"])} for row in rows], unallocated


def warnings(db, invoice, rec, match, *, for_update=True):
    problems = []
    if rec.status != "CONFIRMED":
        problems.append("请先确认对账单，再提交行级匹配发票")
    from app.modules.finance import service
    order = service._lock_order(db, rec.po_id) if for_update else db.get(service.PurchaseOrder, rec.po_id)
    if rec.source_hash != basis_hash(collect_basis(db, order, for_update=for_update)):
        problems.append("订单、到货或退货来源已变化，请先处理对账争议")
    if not match:
        return problems + ["请先保存发票行匹配"]
    if match.reconciliation_version != rec.items_version or match.source_hash != rec.source_hash:
        return problems + ["匹配依据已过期，请重新匹配当前对账版本"]
    items, unallocated = line_summary(db, rec, invoice.id, for_update=for_update)
    if unallocated:
        problems.append("其他有效发票尚未行级匹配：" + "、".join(unallocated))
    by_id = {row["reconciliation_item_id"]: row for row in items}
    excl = tax = Decimal(0)
    for allocation in match.allocations:
        row = by_id.get(allocation["reconciliation_item_id"])
        if row is None:
            problems.append("匹配项不属于当前对账版本")
            continue
        amount_excl = Decimal(allocation["amount_excl_tax"])
        amount_tax = Decimal(allocation["tax_amount"])
        amount = amount_excl + amount_tax
        excl += amount_excl
        tax += amount_tax
        if amount > Decimal(row["remaining_amount"]):
            problems.append(f"第 {row['line_no']} 行累计匹配金额超过应付额度")
        # 比较保存版的价税比例；允许人工说明税额和舍入差异，不自动吸收尾差。
        expected_total = Decimal(row["amount_incl_tax"])
        if expected_total and amount_tax * expected_total != amount * Decimal(row["tax_amount"]) and not (allocation.get("difference_note") or "").strip():
            problems.append(f"第 {row['line_no']} 行税额比例或尾差不一致，请填写差异处理说明")
    if excl != invoice.amount_excl_tax or tax != invoice.tax_amount:
        problems.append("匹配合计必须分别等于发票不含税金额和税额")
    statement = select(FinanceInvoice).where(FinanceInvoice.reconciliation_id == rec.id, FinanceInvoice.id != invoice.id, FinanceInvoice.status.in_(ACTIVE))
    other_total = sum((row.amount_incl_tax for row in db.scalars(statement.with_for_update().execution_options(populate_existing=True) if for_update else statement)), Decimal(0))
    if other_total + invoice.amount_incl_tax > rec.total_amount:
        problems.append("发票累计金额不能超过对账应付总额")
    return problems


def read_match(db: Session, user, invoice_id):
    from app.modules.finance import service
    invoice = service.get_invoice(db, user, invoice_id)
    rec = service.get_reconciliation(db, user, invoice.reconciliation_id)
    order = service.order_service.read_order(db, user, rec.po_id)
    changed = rec.source_hash != basis_hash(collect_basis(db, order)) if rec.items_version else False
    versions = list(db.scalars(select(FinanceInvoiceMatch).where(FinanceInvoiceMatch.invoice_id == invoice.id).order_by(FinanceInvoiceMatch.version_no.desc())))
    items, unallocated = line_summary(db, rec, invoice.id)
    # 读取不加锁；完整校验在提交/核验时重新执行。
    notes = ["历史对账单无行级依据，发票沿用单据级核验"] if not rec.items_version else []
    if changed:
        notes.append("来源已变化，提交或复核前需处理对账争议")
    if unallocated and rec.items_version:
        notes.append("其他有效发票尚未匹配：" + "、".join(unallocated))
    if rec.items_version and invoice.status in {"DRAFT", "REJECTED", "SUBMITTED"}:
        notes += warnings(db, invoice, rec, versions[0] if versions else None, for_update=False)
    return InvoiceMatchRead(invoice_id=invoice.id, reconciliation_version=rec.items_version, source_changed=changed, legacy=rec.items_version == 0, warnings=list(dict.fromkeys(notes)), items=items, versions=versions)


def save_match(db: Session, user, invoice_id, payload: InvoiceMatchSave):
    from app.modules.finance import service
    invoice = service.get_invoice(db, user, invoice_id)
    rec = service._require_reconciliation(db, invoice.reconciliation_id, for_update=True)
    invoice = service._require_invoice(db, invoice_id, for_update=True)
    if invoice.status not in {"DRAFT", "REJECTED"} or rec.status in {"CLOSED", "CANCELLED"}:
        raise BusinessValidationError("仅未关闭对账单的草稿或驳回发票可以修改匹配")
    if payload.reconciliation_version != rec.items_version:
        raise BusinessValidationError("请选择当前对账版本，不得匹配历史版本")
    items, _ = line_summary(db, rec, invoice.id)
    by_id = {row["reconciliation_item_id"]: row for row in items}
    ids = [row.reconciliation_item_id for row in payload.allocations]
    if len(ids) != len(set(ids)) or not set(ids) <= by_id.keys():
        raise BusinessValidationError("匹配项不能重复或引用其他对账单、历史版本的明细")
    allocations = []
    for row in payload.allocations:
        if row.amount_excl_tax + row.tax_amount <= 0:
            raise BusinessValidationError("匹配项价税合计必须大于零")
        allocations.append({**row.model_dump(mode="json"), "line_no": by_id[row.reconciliation_item_id]["line_no"], "product_name": by_id[row.reconciliation_item_id]["product_name"]})
    previous = latest(db, invoice.id, for_update=True)
    match = FinanceInvoiceMatch(invoice_id=invoice.id, version_no=previous.version_no + 1 if previous else 1, reconciliation_version=rec.items_version, source_hash=rec.source_hash or "", allocations=allocations, note=(payload.note or "").strip() or None, created_by=user.id)
    db.add(match)
    db.flush()
    from app.modules.insights.finance_checks import reopen_for_invoice_change
    reopen_for_invoice_change(db, user, invoice)
    problems = warnings(db, invoice, rec, match)
    add_audit_log(db, actor_id=user.id, action_type="MATCH", resource_type="FINANCE_INVOICE", resource_id=invoice.id, request_summary=f"保存发票行匹配第 {match.version_no} 版", result_status="SUCCESS")
    db.commit()
    result = read_match(db, user, invoice.id)
    result.warnings = list(dict.fromkeys(result.warnings + problems))
    return result


def validate_transition(db, user, invoice, rec, *, verifying=False):
    from app.modules.finance import service
    if rec.status in {"CLOSED", "CANCELLED"}:
        raise BusinessValidationError("已关闭或取消的对账单不能提交或核验发票")
    if not rec.items_version:
        if service._sum_invoices(db, rec.id) + (invoice.amount_incl_tax if invoice.status == "REJECTED" else 0) > rec.total_amount:
            raise BusinessValidationError("发票累计金额不能超过对账应付总额")
        return
    if invoice.currency_code != rec.currency_code or invoice.po_id != rec.po_id or invoice.supplier_id != rec.supplier_id:
        raise BusinessValidationError("发票币种、订单或供应商与对账单不一致")
    match = latest(db, invoice.id, for_update=True)
    problems = warnings(db, invoice, rec, match)
    if problems:
        raise BusinessValidationError("；".join(problems))
    if verifying and (invoice.submitted_by == user.id or match.created_by == user.id):
        raise BusinessValidationError("复核人须与提交人及匹配人不同")


def void_invoice(db, user, invoice_id, reason):
    from app.modules.finance import service
    invoice = service.get_invoice(db, user, invoice_id)
    rec = service._require_reconciliation(db, invoice.reconciliation_id, for_update=True)
    invoice = service._require_invoice(db, invoice_id, for_update=True)
    if invoice.status not in {"DRAFT", "REJECTED"} or rec.status in {"CLOSED", "CANCELLED"}:
        raise BusinessValidationError("仅未关闭对账单的草稿或驳回发票可以作废，已核验发票须走正式冲销流程")
    if not reason.strip():
        raise BusinessValidationError("作废必须填写原因")
    invoice.status = "VOIDED"
    invoice.reject_reason = reason.strip()
    from app.modules.insights.finance_checks import reopen_for_invoice_change
    reopen_for_invoice_change(db, user, invoice)
    add_audit_log(db, actor_id=user.id, action_type="VOID", resource_type="FINANCE_INVOICE", resource_id=invoice.id, request_summary=f"作废发票：{reason.strip()}", result_status="SUCCESS")
    db.commit()
    return invoice
