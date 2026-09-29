"""用开发库单据与业务角色验证订单追溯及来源，仅读取数据。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from decimal import Decimal

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.ai.order_trace import PERMISSION_BY_STAGE, extract_order_trace_no, trace_purchase_order
from app.modules.ai.service import _run_text2sql_for_chat
from app.modules.deliveries.model import Delivery
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceSettlement
from app.modules.inventory.model import InventoryBalance, InventoryBatch
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_requests.model import PurchaseRequest
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.rfqs.model import RFQ, SupplierQuote
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


ORDER_NUMBERS = ("PO-2026-0302", "PO-2026-0321", "PO-2026-0327", "PO-2026-0436")
ROLE_USERS = ("procurement_manager", "buyer", "warehouse_receiver", "quality_inspector", "finance_viewer", "finance_manager")
SOURCE_MODELS = {
    "purchase_orders": PurchaseOrder,
    "purchase_requests": PurchaseRequest,
    "rfqs": RFQ,
    "deliveries": Delivery,
    "quality_acceptances": QualityAcceptance,
    "inventory": InventoryBalance,
    "finance_reconciliations": FinanceReconciliation,
    "finance_invoices": FinanceInvoice,
    "finance_payments": FinancePayment,
    "finance_settlements": FinanceSettlement,
}
STAGE_SOURCES = {
    "采购申请": "purchase_requests", "询价与报价": "rfqs", "到货": "deliveries",
    "质量验收": "quality_acceptances", "库存": "inventory", "财务对账": "finance_reconciliations",
    "发票": "finance_invoices", "付款": "finance_payments", "结算": "finance_settlements",
}
SOURCE_NUMBERS = {
    "purchase_orders": "po_no", "purchase_requests": "request_no", "rfqs": "rfq_no",
    "deliveries": "delivery_no", "quality_acceptances": "acceptance_no",
    "finance_reconciliations": "reconciliation_no", "finance_invoices": "invoice_no",
    "finance_payments": "payment_no", "finance_settlements": "settlement_no",
}


def verify_order(db, user: User, number: str) -> dict:
    order = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == number))
    result = trace_purchase_order(db, user, number)
    delivery_ids = set(db.scalars(select(Delivery.id).where(Delivery.po_id == order.id)).all())
    batch_ids = set(db.scalars(select(InventoryBatch.id).where(InventoryBatch.source_delivery_id.in_(delivery_ids))).all()) if delivery_ids else set()
    expected = {
        "purchase_orders": {order.id},
        "purchase_requests": {order.source_request_id} if order.source_request_id else set(),
        "rfqs": {db.get(SupplierQuote, order.source_quote_id).rfq_id} if order.source_quote_id else set(),
        "deliveries": delivery_ids,
        "quality_acceptances": set(db.scalars(select(QualityAcceptance.id).where(QualityAcceptance.delivery_id.in_(delivery_ids))).all()) if delivery_ids else set(),
        "inventory": set(db.scalars(select(InventoryBalance.id).where(InventoryBalance.batch_id.in_(batch_ids))).all()) if batch_ids else set(),
        "finance_reconciliations": set(db.scalars(select(FinanceReconciliation.id).where(FinanceReconciliation.po_id == order.id)).all()),
        "finance_invoices": set(db.scalars(select(FinanceInvoice.id).where(FinanceInvoice.po_id == order.id)).all()),
        "finance_payments": set(db.scalars(select(FinancePayment.id).where(FinancePayment.po_id == order.id)).all()),
        "finance_settlements": set(db.scalars(select(FinanceSettlement.id).where(FinanceSettlement.po_id == order.id)).all()),
    }
    invalid_sources = []
    for source in result["source_records"]:
        dataset = source["dataset"]
        record_id = source["record_id"]
        record = db.get(SOURCE_MODELS[dataset], record_id)
        number_field = SOURCE_NUMBERS.get(dataset)
        wrong_label = record is not None and number_field is not None and str(getattr(record, number_field)) not in source["label"]
        if record is None or record_id not in expected[dataset] or wrong_label:
            invalid_sources.append(f"{dataset}:{record_id}")
    returned = {(source["dataset"], source["record_id"]) for source in result["source_records"]}
    missing_sources = [f"{dataset}:{record_id}" for dataset, ids in expected.items() for record_id in ids
                       if (dataset, record_id) not in returned]
    stage_by_name = {item["stage"]: item for item in result["stages"]}
    reconciliation = db.scalar(select(FinanceReconciliation).where(FinanceReconciliation.po_id == order.id))
    settlement = db.scalar(select(FinanceSettlement).where(FinanceSettlement.po_id == order.id))
    conclusion_ok = (
        (reconciliation is not None or "尚未建立财务对账记录" in result["conclusion"])
        and (settlement is not None or "尚未生成结算单" in result["conclusion"])
    )
    if reconciliation is not None and reconciliation.status in {"CONFIRMED", "CLOSED"}:
        verified = db.scalar(select(func.coalesce(func.sum(FinanceInvoice.amount_incl_tax), 0)).where(
            FinanceInvoice.po_id == order.id, FinanceInvoice.status == "VERIFIED",
            FinanceInvoice.currency_code == reconciliation.currency_code,
        )) or Decimal(0)
        paid = db.scalar(select(func.coalesce(func.sum(FinancePayment.amount), 0)).where(
            FinancePayment.po_id == order.id, FinancePayment.status == "PAID",
            FinancePayment.currency_code == reconciliation.currency_code,
        )) or Decimal(0)
        conclusion_ok = conclusion_ok and (
            any(f"已核验发票 {verified} {reconciliation.currency_code}" in text for text in result["conclusion"])
            == (verified < reconciliation.total_amount)
        ) and (
            any(f"已付款 {paid} {reconciliation.currency_code}" in text for text in result["conclusion"])
            == (paid < reconciliation.total_amount)
        )
    return {"order": number, "passed": not invalid_sources and not missing_sources and conclusion_ok and stage_by_name["采购订单"]["records"][0]["number"] == number,
            "sources": len(result["source_records"]), "invalid_sources": invalid_sources, "missing_sources": missing_sources,
            "conclusion": result["conclusion"]}


def verify_roles(db, number: str) -> list[dict]:
    results = []
    order = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == number))
    for username in ROLE_USERS:
        user = db.scalar(select(User).where(User.username == username))
        roles = set(get_user_role_codes(db, user.id))
        permissions = set(get_user_permission_codes(db, user.id))
        try:
            result = trace_purchase_order(db, user, number)
            stages_ok = all((stage["status"] == "NO_PERMISSION") == ("SYS_ADMIN" not in roles and PERMISSION_BY_STAGE[stage["stage"]] not in permissions)
                            for stage in result["stages"] if stage["stage"] in PERMISSION_BY_STAGE)
            hidden = {stage for stage, permission in PERMISSION_BY_STAGE.items() if "SYS_ADMIN" not in roles and permission not in permissions}
            exposed = any(source["dataset"] in {STAGE_SOURCES[stage] for stage in hidden if stage in STAGE_SOURCES}
                          for source in result["source_records"])
            results.append({"role": username, "passed": stages_ok and not exposed, "access": "trace", "hidden_stages": len(hidden)})
        except BusinessValidationError:
            expected_denial = "procurement.orders.read" not in permissions and "SYS_ADMIN" not in roles
            results.append({"role": username, "passed": expected_denial, "access": "missing_order_permission"})
        except ResourceNotFoundError:
            expected_denial = not ({"SYS_ADMIN", "PROCUREMENT_MANAGER"} & roles) and (
                (user.department_id is not None and order.department_id != user.department_id)
                or (user.department_id is None and order.buyer_id != user.id)
            )
            results.append({"role": username, "passed": expected_denial, "access": "order_scope_denied"})
    return results


async def verify_chat_routes(db, user: User) -> list[dict]:
    results = []
    for number in ORDER_NUMBERS:
        question = f"订单 {number} 为什么还没有结算？"
        expected = trace_purchase_order(db, user, number)
        answer, citation, trace = await _run_text2sql_for_chat(db, user, question, get_settings())
        passed = (extract_order_trace_no(question) == number and answer == expected["answer"]
                  and citation["source_records"] == expected["source_records"]
                  and trace.dataset == "purchase_order_trace")
        results.append({"order": number, "passed": passed})
    return results


def main() -> int:
    if get_settings().app_env != "development":
        raise SystemExit("只在开发环境运行")
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.username == "system_admin"))
        cases = [verify_order(db, admin, number) for number in ORDER_NUMBERS]
        roles = verify_roles(db, "PO-2026-0321")
        chat_routes = asyncio.run(verify_chat_routes(db, admin))
        all_cases = cases + roles + chat_routes
        print(json.dumps({"order_cases": cases, "role_cases": roles, "chat_routes": chat_routes,
                          "passed_count": sum(item["passed"] for item in all_cases),
                          "case_count": len(all_cases)}, ensure_ascii=False, indent=2))
        return 0 if all(item["passed"] for item in all_cases) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
