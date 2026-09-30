"""订单行对账：确定性计算、来源快照、人工退货口径与确认前校验。"""

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceReconciliationItem, FinanceSettlement
from app.modules.finance.schema import ReconciliationItemsRead, ReconciliationItemsRefresh
from app.modules.inventory.model import InventoryBatch
from app.modules.inventory_returns.model import InventoryReturnItem, InventoryReturnRequest
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderItem
from app.modules.purchase_orders.service import read_order
from app.modules.purchase_requests.model import Unit
from app.modules.system.audit import add_audit_log
from app.modules.system.model import User


def collect_basis(db: Session, order: PurchaseOrder, *, for_update: bool = False) -> dict:
    """读取所有相关行和退货，未绑定来源的记录保留为待核查。"""
    def current(statement):
        return statement.with_for_update().execution_options(populate_existing=True) if for_update else statement
    lines = db.scalars(current(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == order.id).order_by(PurchaseOrderItem.line_no))).all()
    deliveries = db.scalars(current(select(Delivery).where(Delivery.po_id == order.id).order_by(Delivery.id))).all()
    delivery_ids = [row.id for row in deliveries]
    delivery_by_id = {row.id: row for row in deliveries}
    items = db.scalars(current(select(DeliveryItem).where(DeliveryItem.delivery_id.in_(delivery_ids)).order_by(DeliveryItem.id))).all() if delivery_ids else []
    returns = db.execute(current(select(InventoryReturnItem, InventoryReturnRequest).join(InventoryReturnRequest).outerjoin(InventoryBatch, InventoryBatch.id == InventoryReturnItem.batch_id).where(
        InventoryReturnRequest.status.in_({"SUBMITTED", "APPROVED", "COMPLETED"}),
        or_(InventoryReturnRequest.po_id == order.id, InventoryReturnRequest.delivery_id.in_(delivery_ids), InventoryReturnItem.source_po_item_id.in_([line.id for line in lines]), InventoryBatch.source_delivery_id.in_(delivery_ids)),
    ).order_by(InventoryReturnItem.id))).all()
    return {
        "order": {"id":order.id, "po_no":order.po_no, "supplier_id":order.supplier_id, "status":order.status, "currency_code":order.currency_code, "order_amount":str(order.order_amount)},
        "lines": [{"id":line.id, "line_no":line.line_no, "product_id":line.product_id, "product_name":line.product_name_snapshot, "unit_id":line.unit_id, "unit_name":(db.get(Unit, line.unit_id).unit_name if db.get(Unit, line.unit_id) else "未记录"), "ordered_quantity":str(line.order_quantity), "recorded_received_quantity":str(line.received_quantity), "unit_price":str(line.unit_price), "tax_rate":str(line.tax_rate or 0)} for line in lines],
        "deliveries": [{"id":row.id,"delivery_no":row.delivery_no,"status":row.status} for row in deliveries],
        "receipts": [{"id":row.id,"delivery_id":row.delivery_id,"delivery_no":delivery_by_id[row.delivery_id].delivery_no,"status":delivery_by_id[row.delivery_id].status,"line_no":row.line_no,"po_item_id":row.po_item_id,"product_id":row.product_id,"unit_id":row.unit_id,"batch_no":row.batch_no,"quantity":str(row.actual_quantity),"short_quantity":str(row.short_quantity)} for row in items],
        "returns": [{"id":row.id,"return_no":request.return_no,"status":request.status,"source_delivery_item_id":row.source_delivery_item_id,"source_po_item_id":row.source_po_item_id,"product_id":row.product_id,"unit_id":row.unit_id,"requested_quantity":str(row.requested_quantity),"returned_quantity":str(row.returned_quantity)} for row,request in returns],
    }


def basis_hash(basis: dict) -> str:
    return hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _global_warnings(basis: dict) -> list[str]:
    warnings = []
    ids = {line["id"] for line in basis["lines"]}
    if not ids:
        warnings.append("订单没有明细，不能建立行级对账依据")
    for row in basis["returns"]:
        if row["status"] != "COMPLETED":
            warnings.append(f"退货 {row['return_no']} 尚未完成，请先核实实际退货结果")
        if row["source_po_item_id"] not in ids:
            warnings.append(f"退货 {row['return_no']} 第 {row['id']} 项尚未关联当前订单行，不能自动分摊")
    return warnings


def append_basis(db: Session, user: User, reconciliation: FinanceReconciliation, order: PurchaseOrder, payload: ReconciliationItemsRefresh) -> None:
    basis = collect_basis(db, order, for_update=True)
    if not basis["lines"]:
        raise BusinessValidationError("采购订单没有明细，无法建立行级对账单")
    decision_ids = [item.po_item_id for item in payload.decisions]
    line_ids = {line["id"] for line in basis["lines"]}
    if len(decision_ids) != len(set(decision_ids)) or not set(decision_ids) <= line_ids:
        raise BusinessValidationError("退货口径不能重复填写或引用其他订单行")
    decisions = {item.po_item_id:item for item in payload.decisions}
    fingerprint = basis_hash(basis)
    version = reconciliation.items_version + 1
    quantum = Decimal(1).scaleb(-payload.amount_precision)
    total = Decimal(0)
    for line in basis["lines"]:
        receipts = [row for row in basis["receipts"] if row["po_item_id"] == line["id"]]
        returns = [row for row in basis["returns"] if row["source_po_item_id"] == line["id"]]
        warnings = []
        valid_receipts = [row for row in receipts if row["product_id"] == line["product_id"] and row["unit_id"] == line["unit_id"]]
        if len(valid_receipts) != len(receipts):
            warnings.append("到货明细的产品或单位与订单行不一致")
        received = sum((Decimal(row["quantity"]) for row in valid_receipts if row["status"] != "IN_TRANSIT"), Decimal(0))
        accepted = sum((Decimal(row["quantity"]) for row in valid_receipts if row["status"] == "ACCEPTED"), Decimal(0))
        if received != Decimal(line["recorded_received_quantity"]):
            warnings.append("关联到货数量与订单累计已收数量不一致")
        if received > Decimal(line["ordered_quantity"]):
            warnings.append("关联到货数量超过订购数量")
        valid_returns = [row for row in returns if row["product_id"] == line["product_id"] and row["unit_id"] == line["unit_id"]]
        if len(valid_returns) != len(returns):
            warnings.append("退货明细的产品或单位与订单行不一致")
        receipt_ids = {row["id"] for row in valid_receipts}
        if any(row["source_delivery_item_id"] is not None and row["source_delivery_item_id"] not in receipt_ids for row in returns):
            warnings.append("退货的到货来源与当前订单行不一致")
        returned = sum((Decimal(row["returned_quantity"]) for row in valid_returns if row["status"] == "COMPLETED"), Decimal(0))
        if returned > accepted:
            warnings.append("退货数量超过已验收通过数量")
        decision = decisions.get(line["id"])
        treatment = decision.return_treatment if decision else ("PENDING" if returned else "NONE")
        note = decision.treatment_note.strip() if decision and decision.treatment_note else None
        if returned and treatment == "NONE":
            raise BusinessValidationError("存在已完成退货的订单行必须选择扣款、待补交或待确认")
        if not returned and treatment not in {"NONE", "PENDING"}:
            raise BusinessValidationError("没有已完成退货的订单行不能选择退货金额处理口径")
        if not returned:
            treatment = "NONE"
        if treatment in {"DEDUCT", "REPLACEMENT"} and not note:
            raise BusinessValidationError("选择退货扣款或待补交时必须填写依据")
        if treatment == "PENDING":
            warnings.append("退货金额处理口径待财务确认，当前金额仅为草稿核查值")
        quantity = max(Decimal(0), accepted - returned) if treatment == "DEDUCT" else accepted
        raw_excl = quantity * Decimal(line["unit_price"])
        amount_excl = raw_excl.quantize(quantum, rounding=ROUND_HALF_UP)
        tax = (raw_excl * Decimal(line["tax_rate"]) / 100).quantize(quantum, rounding=ROUND_HALF_UP)
        amount = amount_excl + tax
        total += amount
        db.add(FinanceReconciliationItem(
            reconciliation_id=reconciliation.id,
            version_no=version,
            po_item_id=line["id"],
            line_no=line["line_no"],
            product_name=line["product_name"],
            unit_name=line["unit_name"],
            ordered_quantity=Decimal(line["ordered_quantity"]),
            received_quantity=received,
            accepted_quantity=accepted,
            returned_quantity=returned,
            reconciliation_quantity=quantity,
            unit_price=Decimal(line["unit_price"]),
            tax_rate=Decimal(line["tax_rate"]),
            amount_excl_tax=amount_excl,
            tax_amount=tax,
            amount_incl_tax=amount,
            return_treatment=treatment,
            treatment_note=note,
            warnings=warnings,
            created_by=user.id,
            basis_json={
                "source_hash": fingerprint,
                "order": basis["order"],
                "order_line": line,
                "receipts": receipts,
                "returns": returns,
                "global_warnings": _global_warnings(basis),
                "amount_precision": payload.amount_precision,
                "rounding": "逐行不含税金额和税额分别按原始数量乘单价计算，以 ROUND_HALF_UP 舍入后相加",
            },
        ))
    reconciliation.items_version = version
    reconciliation.source_hash = fingerprint
    reconciliation.amount_precision = payload.amount_precision
    reconciliation.total_amount = total
    db.flush()


def validate_for_confirmation(db: Session, reconciliation: FinanceReconciliation, order: PurchaseOrder) -> None:
    if reconciliation.items_version == 0:
        raise BusinessValidationError("旧对账单尚无行级依据，请先生成对账明细")
    if reconciliation.source_hash != basis_hash(collect_basis(db, order, for_update=True)):
        raise BusinessValidationError("订单、到货或退货来源已变化，请重新生成对账明细后确认")
    rows = db.scalars(select(FinanceReconciliationItem).where(FinanceReconciliationItem.reconciliation_id == reconciliation.id, FinanceReconciliationItem.version_no == reconciliation.items_version)).all()
    if not rows or any(row.warnings or row.basis_json["global_warnings"] for row in rows):
        raise BusinessValidationError("对账明细存在未处理的来源、数量或退货口径问题，不能确认")
    if sum((row.amount_incl_tax for row in rows), Decimal(0)) != reconciliation.total_amount:
        raise BusinessValidationError("对账主单金额与明细合计不一致，不能确认")


def read_items(db: Session, user: User, reconciliation_id: int, version: int | None = None) -> ReconciliationItemsRead:
    rec = db.get(FinanceReconciliation, reconciliation_id)
    if rec is None:
        raise ResourceNotFoundError("对账单不存在")
    order = read_order(db, user, rec.po_id)
    versions = list(db.scalars(select(FinanceReconciliationItem.version_no).where(FinanceReconciliationItem.reconciliation_id == rec.id).distinct().order_by(FinanceReconciliationItem.version_no.desc())).all())
    selected = rec.items_version if version is None else version
    if version is not None and version not in versions:
        raise ResourceNotFoundError("对账明细版本不存在")
    items = list(db.scalars(select(FinanceReconciliationItem).where(FinanceReconciliationItem.reconciliation_id == rec.id, FinanceReconciliationItem.version_no == selected).order_by(FinanceReconciliationItem.line_no)).all())
    current = collect_basis(db, order)
    saved_hash = items[0].basis_json["source_hash"] if items else None
    warnings = list(items[0].basis_json["global_warnings"]) if items else [
        "历史对账单尚未建立明细，原金额保持不变" if selected == 0 else "当前对账版本的明细未找到，请联系管理员核查"
    ]
    # 没有保存过快照时不存在可比较的历史来源，不能据此判定来源已变化。
    changed = selected > 0 and saved_hash != basis_hash(current)
    return ReconciliationItemsRead(reconciliation_id=rec.id, version_no=selected, available_versions=versions, amount_precision=items[0].basis_json["amount_precision"] if items else rec.amount_precision, currency_code=rec.currency_code, total_amount=sum((row.amount_incl_tax for row in items), Decimal(0)) if items else rec.total_amount, source_changed=changed, warnings=warnings, items=items)


def refresh_items(db: Session, user: User, reconciliation_id: int, payload: ReconciliationItemsRefresh) -> ReconciliationItemsRead:
    from app.modules.finance import service
    rec = service._require_reconciliation(db, reconciliation_id, for_update=True)
    order = read_order(db, user, rec.po_id)
    order = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == order.id).with_for_update().execution_options(populate_existing=True))
    if rec.status not in {"DRAFT", "DISPUTED"}:
        raise BusinessValidationError("仅草稿或争议中的对账单可以重新生成明细")
    service._check_order_ready_for_reconciliation(db, order)
    committed = (
        db.scalar(select(FinanceInvoice.id).where(FinanceInvoice.reconciliation_id == rec.id, FinanceInvoice.status.in_({"DRAFT", "SUBMITTED", "VERIFIED"})).limit(1).with_for_update())
        or db.scalar(select(FinancePayment.id).where(FinancePayment.reconciliation_id == rec.id, FinancePayment.status.in_({"REQUESTED", "APPROVED", "PAID"})).limit(1).with_for_update())
        or db.scalar(select(FinanceSettlement.id).where(FinanceSettlement.reconciliation_id == rec.id, FinanceSettlement.status != "CANCELLED").limit(1).with_for_update())
    )
    if committed:
        raise BusinessValidationError("已有有效发票、付款或结算记录，不能重新计算应付金额，请先处理关联财务单据")
    append_basis(db, user, rec, order, payload)
    add_audit_log(db, actor_id=user.id, action_type="REFRESH_ITEMS", resource_type="FINANCE_RECONCILIATION", resource_id=rec.id, request_summary=f"保存第 {rec.items_version} 版行级对账依据", result_status="SUCCESS")
    db.commit()
    return read_items(db, user, rec.id)
