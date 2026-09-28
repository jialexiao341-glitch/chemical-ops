"""Replace the old generated business corpus with a compact linked sample.

Only for the local ChemicalOps development database. Run a complete snapshot
with backup_development_database.py first; pass its path to --backup.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect, select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.modules.chemicals.model import Chemical  # noqa: E402
from app.modules.deliveries.model import Delivery  # noqa: E402
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceSettlement  # noqa: E402
from app.modules.inventory.model import (  # noqa: E402
    InventoryBalance, InventoryIssueItem, InventoryIssueRequest,
    InventoryStocktakeItem, InventoryStocktakeRequest, InventoryTransaction,
    InventoryTransferItem, InventoryTransferRequest, Warehouse, WarehouseLocation,
)
from app.modules.inventory_cost.model import InventoryCostAllocation, InventoryCostLayer  # noqa: E402
from app.modules.inventory_returns.model import InventoryReturnItem, InventoryReturnRequest  # noqa: E402
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderItem  # noqa: E402
from app.modules.purchase_requests.model import PurchaseRequest, PurchaseRequestApproval, Unit  # noqa: E402
from app.modules.replenishments.model import ReplenishmentItem, ReplenishmentRequest  # noqa: E402
from app.modules.system.model import Department, User  # noqa: E402
from load_development_dataset import load_master_data, load_procurement_chain, load_units  # noqa: E402


PRESERVE = {
    "schema_migrations", "schema_migration_attempts",
    "sys_users", "sys_roles", "sys_permissions", "sys_user_roles",
    "sys_role_permissions", "sys_departments", "sys_files",
    "sys_audit_logs", "sys_login_attempts",
    "md_chemicals", "md_units", "md_product_categories",
    "ai_documents", "ai_document_sections",
    "ai_conversations", "ai_messages", "ai_conversation_state", "ai_query_log",
}
TODAY = date.today()
NOW = datetime.now(timezone.utc)


def q(value: str | int | Decimal) -> Decimal:
    return Decimal(str(value))


def add(db, model, **values):
    row = model(**values)
    db.add(row)
    db.flush()
    return row


def preflight(backup: Path) -> list[str]:
    settings = get_settings()
    if settings.app_env != "development" or settings.mysql_host not in {"127.0.0.1", "localhost"} or settings.mysql_database != "chemicalops":
        raise SystemExit("Refusing to rebuild anything other than the local ChemicalOps development database")
    if not backup.is_file() or backup.stat().st_size < 1024:
        raise SystemExit("A nonempty database backup is required")
    with gzip.open(backup, "rt", encoding="utf-8") as source:
        header = json.loads(next(source))
        if header.get("database") != settings.mysql_database or len(header.get("tables", [])) < 80:
            raise SystemExit("Backup does not match this database schema")
    with engine.connect() as connection:
        if connection.scalar(text("SELECT COUNT(*) FROM md_chemicals WHERE source_text LIKE 'PubChem PUG REST%'")) < 8:
            raise SystemExit("Expected verified PubChem chemical identities are missing")
        for username in ("system_admin", "buyer", "warehouse_receiver", "quality_inspector", "finance_clerk"):
            if connection.scalar(text("SELECT COUNT(*) FROM sys_users WHERE username=:username"), {"username": username}) != 1:
                raise SystemExit(f"Core development account missing: {username}")
    return inspect(engine).get_table_names()


def clear_generated_data(db, tables: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    db.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    try:
        for table in tables:
            if table not in PRESERVE:
                counts[table] = db.execute(text(f"DELETE FROM `{table}`")).rowcount

        counts["ai_messages_generated"] = db.execute(text("DELETE m FROM ai_messages m JOIN ai_conversations c ON c.id=m.conversation_id WHERE c.title LIKE '业务分析会话%' ")).rowcount
        counts["ai_states_generated"] = db.execute(text("DELETE s FROM ai_conversation_state s JOIN ai_conversations c ON c.id=s.conversation_id WHERE c.title LIKE '业务分析会话%' ")).rowcount
        counts["ai_conversations_generated"] = db.execute(text("DELETE FROM ai_conversations WHERE title LIKE '业务分析会话%' ")).rowcount
        counts["sys_audit_logs_generated"] = db.execute(text("DELETE FROM sys_audit_logs WHERE request_summary LIKE '访问业务记录%' ")).rowcount

        # Genuine downloaded documents and chemical identities remain. Old fake
        # files, auto-test accounts, and their security mappings are removed.
        counts["sys_files_demo"] = db.execute(text("DELETE FROM sys_files WHERE object_key LIKE 'development/doc-270%' ")).rowcount
        counts["md_chemicals_demo"] = db.execute(text("DELETE FROM md_chemicals WHERE source_text IS NULL OR source_text NOT LIKE 'PubChem PUG REST%' ")).rowcount
        counts["sys_user_roles_test"] = db.execute(text("DELETE ur FROM sys_user_roles ur JOIN sys_users u ON u.id=ur.user_id WHERE u.username LIKE 'autotest\\_%' OR u.username IN ('supplier_portal_demo','quality','warehouse')")).rowcount
        counts["sys_user_roles_test_roles"] = db.execute(text("DELETE ur FROM sys_user_roles ur JOIN sys_roles r ON r.id=ur.role_id WHERE r.role_code LIKE 'ROLE_TEST\\_%' ")).rowcount
        counts["sys_users_test"] = db.execute(text("DELETE FROM sys_users WHERE username LIKE 'autotest\\_%' OR username IN ('supplier_portal_demo','quality','warehouse')")).rowcount
        counts["sys_role_permissions_test"] = db.execute(text("DELETE rp FROM sys_role_permissions rp JOIN sys_roles r ON r.id=rp.role_id WHERE r.role_code LIKE 'ROLE_TEST\\_%' ")).rowcount
        counts["sys_roles_test"] = db.execute(text("DELETE FROM sys_roles WHERE role_code LIKE 'ROLE_TEST\\_%' ")).rowcount
        counts["sys_departments_test"] = db.execute(text("DELETE FROM sys_departments WHERE department_code LIKE 'DEPT_TEST\\_%' ")).rowcount
    finally:
        db.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    return counts


def seed_core(db) -> Counter[str]:
    counts: Counter[str] = Counter()
    chemical_map = {item.cas_no: item for item in db.scalars(select(Chemical).where(Chemical.status == "ACTIVE")).all() if item.cas_no}
    departments = {item.department_code: item for item in db.scalars(select(Department)).all()}
    accounts = {item.username: item for item in db.scalars(select(User)).all()}
    users = {"buyer": accounts["buyer"], "quality": accounts["quality_inspector"], "warehouse": accounts["warehouse_receiver"]}
    units = load_units(db, counts)
    products, suppliers, supplier_products, warehouse, location = load_master_data(db, chemical_map, units, counts)
    # The stock actually received in the linked chain is solvent stock. Give it
    # an appropriate dedicated storage area instead of the former demo general warehouse.
    warehouse.warehouse_name = "甲类易燃液体仓"
    warehouse.region = "华东园区"
    warehouse.manager_id = users["warehouse"].id
    warehouse.note = "有机溶剂专用区域；按库内作业规程管理"
    location.location_name = "易燃液体区 A 排 01 位"
    load_procurement_chain(db, products, suppliers, supplier_products, units, departments, users, warehouse, location, counts)
    # The legacy SUBMITTED sample must have the pending approval node used by
    # the application workflow; completed receipt has passed quality review.
    submitted = db.scalar(select(PurchaseRequest).where(PurchaseRequest.request_no == "PR-26003"))
    add(db, PurchaseRequestApproval, request_id=submitted.id, sequence_no=1, node_code="PROCUREMENT_MANAGER", node_name="采购负责人审批", action="PENDING")
    accepted = db.scalar(select(Delivery).where(Delivery.delivery_no == "DLV-26001"))
    accepted.status = "ACCEPTED"
    counts["purchase_request_approvals"] += 1
    return counts


def seed_linked_workflows(db) -> Counter[str]:
    counts: Counter[str] = Counter()
    users = {u.username: u for u in db.scalars(select(User)).all()}
    buyer, warehouse_user, finance_user = users["buyer"], users["warehouse_receiver"], users["finance_clerk"]
    rd = db.scalar(select(Department).where(Department.department_code == "R_AND_D"))
    warehouse = db.scalar(select(Warehouse).where(Warehouse.warehouse_code == "WH-26001"))
    location = db.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == warehouse.id))
    reserve = add(db, Warehouse, warehouse_code="WH-SOLVENT-RESERVE", warehouse_name="易燃液体周转仓", region="华东园区", manager_id=warehouse_user.id, status="ACTIVE", note="与主仓同类物料分区周转")
    reserve_location = add(db, WarehouseLocation, warehouse_id=reserve.id, location_code="R-01-01", location_name="周转区 R 排 01 位", status="ACTIVE")
    add(db, Warehouse, warehouse_code="WH-CORROSIVE", warehouse_name="腐蚀品仓", region="华东园区", manager_id=warehouse_user.id, status="ACTIVE")
    add(db, Warehouse, warehouse_code="WH-OXIDIZER", warehouse_name="氧化剂仓", region="华东园区", manager_id=warehouse_user.id, status="ACTIVE")
    counts["warehouses"] += 3
    counts["warehouse_locations"] += 1

    inbound = db.scalars(select(InventoryTransaction).where(InventoryTransaction.transaction_type == "INBOUND").order_by(InventoryTransaction.id)).all()
    for transaction in inbound:
        order_item = db.scalar(select(PurchaseOrderItem).join(PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id).where(PurchaseOrderItem.product_id == transaction.product_id).order_by(PurchaseOrderItem.id))
        if order_item is None:
            continue
        add(db, InventoryCostLayer, source_transaction_id=transaction.id, warehouse_id=transaction.warehouse_id, location_id=transaction.location_id, product_id=transaction.product_id, batch_id=transaction.batch_id, unit_id=transaction.unit_id, unit_cost=order_item.unit_price, currency_code="CNY", original_quantity=transaction.quantity, remaining_quantity=transaction.quantity)
        counts["inventory_cost_layers"] += 1

    balance = db.scalar(select(InventoryBalance).join(InventoryTransaction, (InventoryTransaction.product_id == InventoryBalance.product_id) & (InventoryTransaction.batch_id == InventoryBalance.batch_id)).where(InventoryTransaction.transaction_type == "INBOUND").order_by(InventoryBalance.id))
    if balance is None or balance.quantity < q(20):
        raise RuntimeError("The linked solvent stock is missing")
    issue = add(db, InventoryIssueRequest, issue_no="ISS-LAB-26001", applicant_id=buyer.id, department_id=rd.id, purpose="研发实验室溶剂领用：样品前处理", status="COMPLETED", approved_by=warehouse_user.id, approved_at=NOW - timedelta(days=1), completed_at=NOW)
    add(db, InventoryIssueItem, issue_request_id=issue.id, line_no=1, product_id=balance.product_id, warehouse_id=balance.warehouse_id, location_id=balance.location_id, batch_id=balance.batch_id, unit_id=balance.unit_id, requested_quantity=q(5), issued_quantity=q(5), status="COMPLETED")
    out = add(db, InventoryTransaction, transaction_no="OUT-LAB-26001", transaction_type="OUTBOUND", warehouse_id=balance.warehouse_id, location_id=balance.location_id, product_id=balance.product_id, batch_id=balance.batch_id, unit_id=balance.unit_id, quantity=q(5), source_type="ISSUE_REQUEST", source_id=issue.id, operator_id=warehouse_user.id, note="研发样品前处理领用")
    layer = db.scalar(select(InventoryCostLayer).where(InventoryCostLayer.batch_id == balance.batch_id))
    layer.remaining_quantity -= q(5)
    add(db, InventoryCostAllocation, transaction_id=out.id, cost_layer_id=layer.id, quantity=q(5), unit_cost=layer.unit_cost, total_cost=q(5) * layer.unit_cost)
    balance.quantity -= q(5)
    counts.update({"inventory_issue_requests": 1, "inventory_issue_items": 1, "inventory_transactions": 1, "inventory_cost_allocations": 1})

    transfer = add(db, InventoryTransferRequest, transfer_no="TRF-SOLVENT-26001", applicant_id=warehouse_user.id, purpose="实验室周转需求，调拨同类易燃液体仓", status="COMPLETED", approved_by=warehouse_user.id, approved_at=NOW - timedelta(hours=2), completed_at=NOW)
    add(db, InventoryTransferItem, transfer_request_id=transfer.id, line_no=1, product_id=balance.product_id, source_warehouse_id=warehouse.id, source_location_id=location.id, target_warehouse_id=reserve.id, target_location_id=reserve_location.id, batch_id=balance.batch_id, unit_id=balance.unit_id, requested_quantity=q(10), transferred_quantity=q(10), status="COMPLETED")
    out_transfer = add(db, InventoryTransaction, transaction_no="TRF-OUT-26001", transaction_type="TRANSFER_OUT", warehouse_id=warehouse.id, location_id=location.id, product_id=balance.product_id, batch_id=balance.batch_id, unit_id=balance.unit_id, quantity=q(10), source_type="TRANSFER_REQUEST", source_id=transfer.id, operator_id=warehouse_user.id)
    in_transfer = add(db, InventoryTransaction, transaction_no="TRF-IN-26001", transaction_type="TRANSFER_IN", warehouse_id=reserve.id, location_id=reserve_location.id, product_id=balance.product_id, batch_id=balance.batch_id, unit_id=balance.unit_id, quantity=q(10), source_type="TRANSFER_REQUEST", source_id=transfer.id, operator_id=warehouse_user.id)
    add(db, InventoryCostAllocation, transaction_id=out_transfer.id, cost_layer_id=layer.id, quantity=q(10), unit_cost=layer.unit_cost, total_cost=q(10) * layer.unit_cost)
    layer.remaining_quantity -= q(10)
    balance.quantity -= q(10)
    add(db, InventoryBalance, warehouse_id=reserve.id, location_id=reserve_location.id, product_id=balance.product_id, batch_id=balance.batch_id, unit_id=balance.unit_id, quantity=q(10), locked_quantity=q(0), status="AVAILABLE")
    add(db, InventoryCostLayer, source_transaction_id=in_transfer.id, warehouse_id=reserve.id, location_id=reserve_location.id, product_id=balance.product_id, batch_id=balance.batch_id, unit_id=balance.unit_id, unit_cost=layer.unit_cost, currency_code="CNY", original_quantity=q(10), remaining_quantity=q(10))
    counts.update({"inventory_transfer_requests": 1, "inventory_transfer_items": 1, "inventory_transactions": 2, "inventory_cost_allocations": 1, "inventory_balances": 1, "inventory_cost_layers": 1})

    stocktake = add(db, InventoryStocktakeRequest, stocktake_no="STK-SOLVENT-26001", applicant_id=warehouse_user.id, warehouse_id=warehouse.id, location_id=location.id, purpose="月度批次账实核对", status="COMPLETED", approved_by=warehouse_user.id, approved_at=NOW, completed_at=NOW)
    add(db, InventoryStocktakeItem, stocktake_request_id=stocktake.id, line_no=1, product_id=balance.product_id, location_id=balance.location_id, batch_id=balance.batch_id, unit_id=balance.unit_id, book_quantity=balance.quantity, counted_quantity=balance.quantity, difference_quantity=q(0), status="COMPLETED", note="账实一致")
    counts.update({"inventory_stocktake_requests": 1, "inventory_stocktake_items": 1})

    partial = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == "PO-26002"))
    delivery = db.scalar(select(Delivery).where(Delivery.po_id == partial.id))
    short_item = db.scalar(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == partial.id))
    replenish = add(db, ReplenishmentRequest, replenishment_no="REP-SHORT-26001", supplier_id=partial.supplier_id, source_po_id=partial.id, source_delivery_id=delivery.id, applicant_id=buyer.id, reason="到货短交 8 L，要求供应商按原单补足", status="APPROVED", approved_by=users["procurement_manager"].id, approved_at=NOW)
    add(db, ReplenishmentItem, replenishment_request_id=replenish.id, line_no=1, product_id=short_item.product_id, unit_id=short_item.unit_id, requested_quantity=q(8), expected_date=TODAY + timedelta(days=5), status="OPEN")
    counts.update({"replenishment_requests": 1, "replenishment_items": 1})
    return_request = add(db, InventoryReturnRequest, return_no="RET-QUALITY-26001", supplier_id=partial.supplier_id, po_id=partial.id, delivery_id=delivery.id, applicant_id=warehouse_user.id, reason="待质量复核批次暂缓使用，申请退货评估", status="DRAFT")
    short_balance = db.scalar(select(InventoryBalance).where(InventoryBalance.product_id == short_item.product_id))
    add(db, InventoryReturnItem, return_request_id=return_request.id, line_no=1, product_id=short_item.product_id, warehouse_id=short_balance.warehouse_id, location_id=short_balance.location_id, batch_id=short_balance.batch_id, unit_id=short_balance.unit_id, requested_quantity=q(2), returned_quantity=q(0), status="OPEN")
    counts.update({"inventory_return_requests": 1, "inventory_return_items": 1})

    complete = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == "PO-26001"))
    amount = complete.order_amount
    reconciliation = add(db, FinanceReconciliation, reconciliation_no="REC-26001", po_id=complete.id, supplier_id=complete.supplier_id, currency_code="CNY", total_amount=amount, status="CLOSED", created_by=finance_user.id, confirmed_by=users["finance_manager"].id, confirmed_at=NOW - timedelta(days=2), closed_at=NOW, note="与已收货订单及发票金额核对一致")
    net = (amount / q("1.13")).quantize(q("0.01"))
    tax = amount - net
    add(db, FinanceInvoice, invoice_no="INV-26001", reconciliation_id=reconciliation.id, po_id=complete.id, supplier_id=complete.supplier_id, invoice_number="FP202609900001", invoice_date=TODAY - timedelta(days=2), amount_excl_tax=net, tax_amount=tax, amount_incl_tax=amount, currency_code="CNY", status="VERIFIED", submitted_by=finance_user.id, verified_by=users["finance_manager"].id, verified_at=NOW - timedelta(days=1), note="票面金额与订单及对账金额核对一致，附件待归档")
    add(db, FinancePayment, payment_no="PAY-26001", reconciliation_id=reconciliation.id, po_id=complete.id, supplier_id=complete.supplier_id, amount=amount, currency_code="CNY", payment_method="BANK_TRANSFER", status="PAID", requested_by=finance_user.id, approved_by=users["finance_manager"].id, paid_by=finance_user.id, approved_at=NOW - timedelta(days=1), paid_at=NOW, transaction_ref="FIN202609900001", note="付款登记金额与对账金额一致，银行回单待归档")
    add(db, FinanceSettlement, settlement_no="SET-26001", reconciliation_id=reconciliation.id, po_id=complete.id, supplier_id=complete.supplier_id, settlement_amount=amount, currency_code="CNY", status="CONFIRMED", created_by=finance_user.id, confirmed_by=users["finance_manager"].id, confirmed_at=NOW, note="结算金额已与订单、发票及付款登记核对一致")
    counts.update({"finance_reconciliations": 1, "finance_invoices": 1, "finance_payments": 1, "finance_settlements": 1})
    return counts


def verify(db) -> dict[str, int]:
    names = ("md_chemicals", "md_products", "suppliers", "warehouses", "purchase_requests", "rfqs", "purchase_orders", "deliveries", "quality_acceptances", "inventory_balances", "inventory_transactions", "inventory_issue_requests", "inventory_transfer_requests", "inventory_stocktake_requests", "finance_reconciliations", "finance_invoices", "finance_payments", "finance_settlements", "operation_exceptions", "ai_conversations")
    result = {name: db.scalar(text(f"SELECT COUNT(*) FROM `{name}`")) for name in names}
    if any(result[name] == 0 for name in names if name != "ai_conversations"):
        raise RuntimeError(f"A business area was left empty: {result}")
    if db.scalar(text("SELECT COUNT(*) FROM ai_conversations WHERE title LIKE '业务分析会话%'")):
        raise RuntimeError("Generated AI conversations were not cleared")
    if db.scalar(text("SELECT COUNT(*) FROM md_products p JOIN md_chemicals c ON c.id=p.chemical_id WHERE c.cas_no LIKE '%-DEMO'")):
        raise RuntimeError("A product still references a demo chemical")
    if db.scalar(text("SELECT COUNT(*) FROM warehouses WHERE warehouse_name LIKE '%演示%'")):
        raise RuntimeError("A demo warehouse is still visible")
    ledger_mismatches = db.execute(text("""
        SELECT b.id, b.quantity, COALESCE(SUM(CASE
            WHEN t.transaction_type IN ('INBOUND','TRANSFER_IN') THEN t.quantity
            WHEN t.transaction_type IN ('OUTBOUND','TRANSFER_OUT') THEN -t.quantity
            ELSE 0 END),0) AS ledger_quantity
        FROM inventory_balances b LEFT JOIN inventory_transactions t
          ON t.warehouse_id=b.warehouse_id AND t.location_id=b.location_id
         AND t.product_id=b.product_id AND t.batch_id=b.batch_id AND t.unit_id=b.unit_id
        GROUP BY b.id, b.quantity
        HAVING ABS(b.quantity-ledger_quantity)>0.000001
    """)).all()
    if ledger_mismatches:
        raise RuntimeError(f"Inventory balance does not match transactions: {ledger_mismatches}")
    mismatched_finance = db.scalar(text("""
        SELECT COUNT(*) FROM finance_reconciliations r
        JOIN finance_invoices i ON i.reconciliation_id=r.id
        JOIN finance_payments p ON p.reconciliation_id=r.id
        JOIN finance_settlements s ON s.reconciliation_id=r.id
        WHERE ABS(r.total_amount-i.amount_incl_tax)>0.000001
           OR ABS(r.total_amount-p.amount)>0.000001
           OR ABS(r.total_amount-s.settlement_amount)>0.000001
    """))
    if mismatched_finance:
        raise RuntimeError("Finance invoice, payment, settlement and reconciliation amounts differ")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--validate-transaction", action="store_true", help="Run all changes and checks, then roll back")
    args = parser.parse_args()
    tables = preflight(args.backup)
    if not args.apply and not args.validate_transaction:
        print(json.dumps({"dry_run": True, "tables_to_clear": len(set(tables) - PRESERVE), "preserved": sorted(PRESERVE)}, ensure_ascii=False))
        return
    db = SessionLocal()
    try:
        removed = clear_generated_data(db, tables)
        created = seed_core(db)
        created.update(seed_linked_workflows(db))
        result = verify(db)
        if args.validate_transaction:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(json.dumps({"rolled_back": args.validate_transaction, "removed": removed, "created": created, "verified": result}, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
