"""订单跨模块只读追溯。每个环节先独立核验权限，再读取其业务来源。"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceSettlement
from app.modules.inventory.model import InventoryBalance, InventoryBatch, InventoryTransaction
from app.modules.inventory_returns.model import InventoryReturnRequest
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderItem
from app.modules.purchase_requests.model import PurchaseRequest
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.rfqs.model import QuoteComparison, RFQ, SupplierQuote
from app.modules.suppliers.model import Supplier
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


ORDER_NO_PATTERN = re.compile(r"\b(PO[-_][A-Z0-9][A-Z0-9-]*)\b", re.IGNORECASE)
TRACE_MARKERS = ("为什么", "原因", "结算", "全流程", "到哪一步", "进度", "追溯", "未完成", "卡在哪", "异常订单")

PERMISSION_BY_STAGE = {
    "采购申请": "procurement.requests.read",
    "询价与报价": "procurement.rfqs.read",
    "到货": "warehouse.deliveries.read",
    "质量验收": "quality.acceptances.read",
    "库存": "warehouse.inventory.read",
    "退货": "warehouse.inventory.return.read",
    "财务对账": "finance.reconciliations.read",
    "发票": "finance.invoices.read",
    "付款": "finance.payments.read",
    "结算": "finance.settlements.read",
}


def extract_order_trace_no(question: str) -> str | None:
    """只将明确包含订单号且询问流程/原因的问题路由到跨模块追溯。"""

    if not any(marker in question for marker in TRACE_MARKERS):
        return None
    match = ORDER_NO_PATTERN.search(question.upper())
    return match.group(1).replace("_", "-") if match else None


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, (date, datetime)) else None


def _amount(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _can_read(stage: str, permissions: set[str], roles: set[str]) -> bool:
    return "SYS_ADMIN" in roles or PERMISSION_BY_STAGE[stage] in permissions


def _stage(stage: str, allowed: bool, records: list[dict[str, Any]] | None = None, *, summary: str | None = None, truncated: bool = False) -> dict[str, Any]:
    if not allowed:
        return {"stage": stage, "status": "NO_PERMISSION", "summary": "当前账号没有该环节的读取权限", "records": []}
    values = records or []
    return {
        "stage": stage,
        "status": "AVAILABLE" if values else "NO_DATA",
        "summary": (summary or (f"找到 {len(values)} 条记录" if values else "没有查到关联记录")) + ("；仅显示前 50 条" if truncated else ""),
        "records": values,
        "truncated": truncated,
    }


def _record(no: str | None, status: str | None, updated_at: datetime | None, **values: Any) -> dict[str, Any]:
    return {
        "number": no,
        "status": status,
        "updated_at": _iso(updated_at),
        **{key: value for key, value in values.items() if value is not None},
    }


def _require_order_scope(db: Session, user: User, order: PurchaseOrder, roles: set[str]) -> None:
    if "SYS_ADMIN" in roles or "PROCUREMENT_MANAGER" in roles:
        return
    if user.department_id is not None:
        if order.department_id != user.department_id:
            raise ResourceNotFoundError(f"订单 {order.po_no} 不存在或无权查看")
    elif order.buyer_id != user.id:
        raise ResourceNotFoundError(f"订单 {order.po_no} 不存在或无权查看")


def trace_purchase_order(db: Session, user: User, po_no: str) -> dict[str, Any]:
    """按订单号逐模块取证；每一环节只有权限通过后才查询该模块数据。"""

    permissions = set(get_user_permission_codes(db, user.id))
    roles = set(get_user_role_codes(db, user.id))
    if "SYS_ADMIN" not in roles and "procurement.orders.read" not in permissions:
        raise BusinessValidationError("跨模块追溯需要采购订单读取权限")

    order = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == po_no))
    if order is None:
        raise ResourceNotFoundError(f"订单 {po_no} 不存在或无权查看")
    _require_order_scope(db, user, order, roles)

    supplier_name = db.scalar(select(Supplier.supplier_name).where(Supplier.id == order.supplier_id))
    order_items = list(db.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == order.id).order_by(PurchaseOrderItem.line_no)).all())
    stages: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = [
        {"dataset": "purchase_orders", "label": f"采购订单 {order.po_no}", "record_id": order.id, "filters": {"keywords": order.po_no}}
    ]

    # 采购申请
    allowed = _can_read("采购申请", permissions, roles)
    if allowed and order.source_request_id:
        request = db.get(PurchaseRequest, order.source_request_id)
        records = [_record(request.request_no, request.status, request.updated_at)] if request else []
        if request:
            source_records.append({"dataset": "purchase_requests", "label": f"采购申请 {request.request_no}", "record_id": request.id, "filters": {"keywords": request.request_no}})
        stages.append(_stage("采购申请", True, records))
    else:
        stages.append(_stage("采购申请", allowed, []))

    # 询价、选中报价和比价记录
    allowed = _can_read("询价与报价", permissions, roles)
    if allowed:
        quote_id = order.source_quote_id
        if quote_id is None and order.source_comparison_id:
            comparison = db.get(QuoteComparison, order.source_comparison_id)
            quote_id = comparison.selected_quote_id if comparison else None
        quote = db.get(SupplierQuote, quote_id) if quote_id else None
        rfq = db.get(RFQ, quote.rfq_id) if quote else None
        quote_records = [_record(quote.quote_no, quote.status, quote.updated_at, rfq_no=rfq.rfq_no if rfq else None)] if quote else []
        stages.append(_stage("询价与报价", True, quote_records, summary=(f"关联询价单 {rfq.rfq_no}，报价 {quote.quote_no}（{quote.status}）" if quote and rfq else None)))
    else:
        stages.append(_stage("询价与报价", False))

    stages.append(_stage("采购订单", True, [_record(order.po_no, order.status, order.updated_at, supplier=supplier_name, order_amount=_amount(order.order_amount), currency=order.currency_code, order_date=_iso(order.order_date), item_count=len(order_items))]))

    # 到货记录
    delivery_allowed = _can_read("到货", permissions, roles)
    delivery_rows = list(db.scalars(select(Delivery).where(Delivery.po_id == order.id).order_by(Delivery.id).limit(51)).all()) if delivery_allowed else []
    deliveries_truncated = len(delivery_rows) > 50
    deliveries = delivery_rows[:50]
    delivery_records = [
        _record(item.delivery_no, item.status, item.updated_at, expected_arrival_date=_iso(item.expected_arrival_date), actual_arrival_date=_iso(item.actual_arrival_date))
        for item in deliveries
    ]
    stages.append(_stage("到货", delivery_allowed, delivery_records, truncated=deliveries_truncated))
    delivery_ids = [item.id for item in deliveries]
    for item in deliveries:
        source_records.append({"dataset": "deliveries", "label": f"到货单 {item.delivery_no}", "record_id": item.id, "filters": {"keywords": item.delivery_no}})

    # 质量验收
    quality_allowed = _can_read("质量验收", permissions, roles)
    acceptance_rows = list(db.scalars(select(QualityAcceptance).join(Delivery, Delivery.id == QualityAcceptance.delivery_id).where(Delivery.po_id == order.id).order_by(QualityAcceptance.id).limit(51)).all()) if quality_allowed else []
    acceptances_truncated = len(acceptance_rows) > 50
    acceptances = acceptance_rows[:50]
    stages.append(_stage("质量验收", quality_allowed, [_record(item.acceptance_no, item.result, item.updated_at, conclusion=item.conclusion) for item in acceptances], truncated=acceptances_truncated))
    for item in acceptances:
        source_records.append({"dataset": "quality_acceptances", "label": f"质量验收 {item.acceptance_no}", "record_id": item.id, "filters": {"result": item.result}})

    # 入库批次及库存记录
    inventory_allowed = _can_read("库存", permissions, roles)
    batch_rows: list[InventoryBatch] = []
    balances: list[InventoryBalance] = []
    batches_truncated = False
    balances_truncated = False
    if inventory_allowed and delivery_ids:
        from app.modules.inventory.service import accessible_warehouse_ids

        warehouse_ids = accessible_warehouse_ids(db, user)
        all_batches = list(db.scalars(select(InventoryBatch).where(InventoryBatch.source_delivery_id.in_(delivery_ids)).order_by(InventoryBatch.id).limit(51)).all())
        batches_truncated = len(all_batches) > 50
        batch_rows = all_batches[:50]
        if batch_rows:
            balance_query = select(InventoryBalance).where(InventoryBalance.batch_id.in_([item.id for item in batch_rows]))
            if warehouse_ids is not None:
                balance_query = balance_query.where(InventoryBalance.warehouse_id.in_(warehouse_ids))
            all_balances = list(db.scalars(balance_query.order_by(InventoryBalance.id).limit(51)).all())
            balances_truncated = len(all_balances) > 50
            balances = all_balances[:50]
    batches = batch_rows
    inventory_records = [
        _record(None, item.status, item.updated_at, batch_id=item.batch_id, product_id=item.product_id, warehouse_id=item.warehouse_id, quantity=_amount(item.quantity), locked_quantity=_amount(item.locked_quantity), unit_id=item.unit_id)
        for item in balances
    ]
    stages.append(_stage("库存", inventory_allowed, inventory_records, summary=f"关联 {len(batches)} 个批次，当前权限范围内找到 {len(balances)} 条库存余额" if inventory_allowed and batches else None, truncated=batches_truncated or balances_truncated))
    for item in balances[:20]:
        source_records.append({"dataset": "inventory", "label": f"库存批次 #{item.batch_id}", "record_id": item.id, "filters": {"product_id": item.product_id, "warehouse_id": item.warehouse_id, "batch_id": item.batch_id}})

    # 退货
    return_allowed = _can_read("退货", permissions, roles)
    return_rows = list(db.scalars(select(InventoryReturnRequest).where((InventoryReturnRequest.po_id == order.id) | (InventoryReturnRequest.delivery_id.in_(delivery_ids) if delivery_ids else False)).order_by(InventoryReturnRequest.id).limit(51)).all()) if return_allowed else []
    returns_truncated = len(return_rows) > 50
    returns = return_rows[:50]
    stages.append(_stage("退货", return_allowed, [_record(item.return_no, item.status, item.updated_at, reason=item.reason) for item in returns], truncated=returns_truncated))

    # 财务各节点独立鉴权，未授权节点不发起 SQL 查询。
    reconciliation_allowed = _can_read("财务对账", permissions, roles)
    reconciliation = db.scalar(select(FinanceReconciliation).where(FinanceReconciliation.po_id == order.id)) if reconciliation_allowed else None
    stages.append(_stage("财务对账", reconciliation_allowed, [_record(reconciliation.reconciliation_no, reconciliation.status, reconciliation.updated_at, amount=_amount(reconciliation.total_amount), currency=reconciliation.currency_code)] if reconciliation else []))
    if reconciliation is not None:
        source_records.append({"dataset": "finance_reconciliations", "label": f"财务对账 {reconciliation.reconciliation_no}", "record_id": reconciliation.id, "filters": {"status": reconciliation.status}})

    invoice_allowed = _can_read("发票", permissions, roles)
    invoice_rows = list(db.scalars(select(FinanceInvoice).where(FinanceInvoice.po_id == order.id).order_by(FinanceInvoice.id).limit(51)).all()) if invoice_allowed else []
    invoices_truncated = len(invoice_rows) > 50
    invoices = invoice_rows[:50]
    stages.append(_stage("发票", invoice_allowed, [_record(item.invoice_no, item.status, item.updated_at, amount=_amount(item.amount_incl_tax), currency=item.currency_code) for item in invoices], truncated=invoices_truncated))

    payment_allowed = _can_read("付款", permissions, roles)
    payment_rows = list(db.scalars(select(FinancePayment).where(FinancePayment.po_id == order.id).order_by(FinancePayment.id).limit(51)).all()) if payment_allowed else []
    payments_truncated = len(payment_rows) > 50
    payments = payment_rows[:50]
    stages.append(_stage("付款", payment_allowed, [_record(item.payment_no, item.status, item.updated_at, amount=_amount(item.amount), currency=item.currency_code) for item in payments], truncated=payments_truncated))

    settlement_allowed = _can_read("结算", permissions, roles)
    settlement_rows = list(db.scalars(select(FinanceSettlement).where(FinanceSettlement.po_id == order.id).order_by(FinanceSettlement.id).limit(51)).all()) if settlement_allowed else []
    settlements_truncated = len(settlement_rows) > 50
    settlements = settlement_rows[:50]
    stages.append(_stage("结算", settlement_allowed, [_record(item.settlement_no, item.status, item.updated_at, amount=_amount(item.settlement_amount), currency=item.currency_code) for item in settlements], truncated=settlements_truncated))

    conclusion: list[str] = []
    expected = reconciliation.total_amount if reconciliation and reconciliation.status in {"CONFIRMED", "CLOSED"} else None
    currency = reconciliation.currency_code if reconciliation else order.currency_code
    if reconciliation_allowed:
        if reconciliation is None:
            conclusion.append("尚未建立财务对账记录")
        elif reconciliation.status not in {"CONFIRMED", "CLOSED"}:
            conclusion.append(f"财务对账仍为 {reconciliation.status}")
    if invoice_allowed and expected is not None:
        verified = db.scalar(
            select(func.coalesce(func.sum(FinanceInvoice.amount_incl_tax), 0)).where(
                FinanceInvoice.po_id == order.id,
                FinanceInvoice.status == "VERIFIED",
                FinanceInvoice.currency_code == currency,
            )
        ) or Decimal(0)
        if verified < expected:
            conclusion.append(f"已核验发票 {verified} {currency}，低于应付口径 {expected} {currency}")
    if payment_allowed and expected is not None:
        paid = db.scalar(
            select(func.coalesce(func.sum(FinancePayment.amount), 0)).where(
                FinancePayment.po_id == order.id,
                FinancePayment.status == "PAID",
                FinancePayment.currency_code == currency,
            )
        ) or Decimal(0)
        if paid < expected:
            conclusion.append(f"已付款 {paid} {currency}，低于应付口径 {expected} {currency}")
    if settlement_allowed:
        if not settlements:
            conclusion.append("尚未生成结算单")
        elif not db.scalar(
            select(
                exists().where(
                    FinanceSettlement.po_id == order.id,
                    FinanceSettlement.status == "CONFIRMED",
                    FinanceSettlement.currency_code == currency,
                )
            )
        ):
            conclusion.append("结算单尚未确认")

    unavailable = [item["stage"] for item in stages if item["status"] == "NO_PERMISSION"]
    lines = [f"订单 {order.po_no} 跨模块追溯", f"供应商：{supplier_name or '未登记'}；订单状态：{order.status}。"]
    for item in stages:
        if item["status"] == "NO_PERMISSION":
            lines.append(f"- {item['stage']}：当前账号无读取权限，无法核验。")
        elif item["records"]:
            descriptions = []
            for record in item["records"][:8]:
                text = str(record.get("number") or record.get("batch_id") or "关联记录")
                if record.get("status"):
                    text += f"（{record['status']}）"
                descriptions.append(text)
            suffix = f"；{item['summary']}" if len(item["records"]) > 8 or item.get("truncated") else ""
            lines.append(f"- {item['stage']}：" + "、".join(descriptions) + suffix)
        else:
            lines.append(f"- {item['stage']}：{item['summary']}。")
    if conclusion:
        lines.append("可见数据中的未完成原因：" + "；".join(conclusion) + "。")
    elif unavailable:
        lines.append("当前可查看的数据不足以确定未结算原因；需有权限后再核验：" + "、".join(unavailable) + "。")
    else:
        lines.append("已查看的环节未发现未完成项；请以业务模块当前状态复核结算结果。")

    return {
        "po_no": order.po_no,
        "supplier": supplier_name,
        "order_status": order.status,
        "order_updated_at": _iso(order.updated_at),
        "stages": stages,
        "conclusion": conclusion,
        "unavailable_stages": unavailable,
        "source_records": source_records,
        "answer": "\n".join(lines),
    }
