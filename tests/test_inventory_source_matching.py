"""Detect wrong line attribution and transfer problems even when totals balance."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.insights.source_matching import match_source, match_sources, transfer_pairs
from app.modules.inventory.model import (
    InventoryBalance, InventoryBatch, InventoryIssueItem, InventoryIssueRequest,
    InventoryStocktakeItem, InventoryStocktakeRequest, InventoryTransaction,
    InventoryTransferItem, InventoryTransferRequest, WarehouseLocation,
)
from app.modules.inventory_returns.model import InventoryReturnItem, InventoryReturnRequest
from app.modules.purchase_orders.model import PurchaseOrderItem
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.suppliers.model import Supplier
from app.modules.system.model import User
from .conftest import login


pytestmark = pytest.mark.integration


@pytest.fixture
def executed_line(db_session, request):
    kind = request.param
    balance = db_session.scalar(select(InventoryBalance).order_by(InventoryBalance.id))
    user = db_session.scalar(select(User).where(User.username == "system_admin"))
    assert balance is not None and user is not None
    fields = dict(product_id=balance.product_id, batch_id=balance.batch_id, unit_id=balance.unit_id)
    slot = dict(warehouse_id=balance.warehouse_id, location_id=balance.location_id)
    qty = Decimal("5")
    direction = "OUTBOUND"
    if kind == "ISSUE_REQUEST":
        document = InventoryIssueRequest(issue_no="TEST-SOURCE-ISSUE", applicant_id=user.id, purpose="来源核对", status="COMPLETED")
        db_session.add(document)
        db_session.flush()
        item = InventoryIssueItem(issue_request_id=document.id, line_no=1, **fields, **slot, requested_quantity=qty, issued_quantity=qty, status="ISSUED")
    elif kind == "INVENTORY_RETURN":
        supplier = db_session.scalar(select(Supplier).order_by(Supplier.id))
        document = InventoryReturnRequest(return_no="TEST-SOURCE-RETURN", supplier_id=supplier.id, applicant_id=user.id, reason="来源核对", status="COMPLETED")
        db_session.add(document)
        db_session.flush()
        item = InventoryReturnItem(return_request_id=document.id, line_no=1, **fields, **slot, requested_quantity=qty, returned_quantity=qty, status="RETURNED")
    elif kind == "INVENTORY_STOCKTAKE":
        document = InventoryStocktakeRequest(stocktake_no="TEST-SOURCE-STOCKTAKE", applicant_id=user.id, warehouse_id=balance.warehouse_id, purpose="来源核对", status="COMPLETED")
        db_session.add(document)
        db_session.flush()
        item = InventoryStocktakeItem(stocktake_request_id=document.id, line_no=1, **fields, location_id=balance.location_id, book_quantity=Decimal("10"), counted_quantity=Decimal("5"), difference_quantity=-qty, status="ADJUSTED")
        direction = "ADJUSTMENT"
    elif kind == "INVENTORY_TRANSFER":
        target = db_session.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id != balance.warehouse_id).order_by(WarehouseLocation.id))
        assert target is not None
        document = InventoryTransferRequest(transfer_no="TEST-SOURCE-TRANSFER", applicant_id=user.id, purpose="来源核对", status="COMPLETED")
        db_session.add(document)
        db_session.flush()
        item = InventoryTransferItem(transfer_request_id=document.id, line_no=1, **fields, source_warehouse_id=balance.warehouse_id, source_location_id=balance.location_id, target_warehouse_id=target.warehouse_id, target_location_id=target.id, requested_quantity=qty, transferred_quantity=qty, status="TRANSFERRED")
    else:
        po_item = db_session.scalar(select(PurchaseOrderItem).order_by(PurchaseOrderItem.id))
        order = db_session.get(PurchaseOrder, po_item.po_id)
        document = Delivery(delivery_no="TEST-SOURCE-DELIVERY", po_id=order.id, supplier_id=order.supplier_id, status="ACCEPTED")
        db_session.add(document)
        db_session.flush()
        batch = InventoryBatch(product_id=po_item.product_id, batch_no="TEST-SOURCE-BATCH", source_delivery_id=document.id)
        db_session.add(batch)
        db_session.flush()
        fields = dict(product_id=po_item.product_id, batch_id=batch.id, unit_id=po_item.unit_id)
        item = DeliveryItem(delivery_id=document.id, po_item_id=po_item.id, product_id=po_item.product_id, unit_id=po_item.unit_id, line_no=1, batch_no=batch.batch_no, planned_quantity=qty, actual_quantity=qty)
        direction = "INBOUND"
    db_session.add(item)
    db_session.flush()
    tx = InventoryTransaction(transaction_no=f"TEST-SOURCE-{kind}", transaction_type=direction, **fields, **slot, quantity=qty, source_type=kind, source_id=document.id, operator_id=user.id, delivery_item_id=item.id if kind == "DELIVERY" else None)
    db_session.add(tx)
    db_session.flush()
    return document, item, tx


@pytest.mark.parametrize("executed_line", ["DELIVERY", "ISSUE_REQUEST", "INVENTORY_RETURN", "INVENTORY_STOCKTAKE", "INVENTORY_TRANSFER"], indirect=True)
def test_matches_exact_execution_and_rejects_quantity_direction_and_state(db_session, executed_line):
    document, item, tx = executed_line
    matched = match_source(db_session, tx)
    assert matched["status"] == "MATCHED"
    assert matched["item_id"] == item.id
    assert Decimal(matched["signed_quantity"]) == (tx.quantity if tx.transaction_type == "INBOUND" else -tx.quantity)
    tx.quantity += 1
    assert match_source(db_session, tx)["status"] == "CONFLICT"
    tx.quantity -= 1
    original_direction = tx.transaction_type
    tx.transaction_type = "UNKNOWN"
    assert match_source(db_session, tx)["status"] == "CONFLICT"
    tx.transaction_type = original_direction
    document.status = "DRAFT"
    assert match_source(db_session, tx)["status"] == "CONFLICT"


@pytest.mark.parametrize("executed_line", ["ISSUE_REQUEST"], indirect=True)
def test_repeated_movements_and_ambiguous_lines_are_not_matched(db_session, executed_line):
    document, item, tx = executed_line
    duplicate = InventoryTransaction(transaction_no="TEST-SOURCE-DUPLICATE", transaction_type=tx.transaction_type, warehouse_id=tx.warehouse_id, location_id=tx.location_id, product_id=tx.product_id, batch_id=tx.batch_id, unit_id=tx.unit_id, quantity=tx.quantity, source_type=tx.source_type, source_id=tx.source_id, operator_id=tx.operator_id)
    db_session.add(duplicate)
    db_session.flush()
    assert {row["status"] for row in match_sources(db_session, [tx, duplicate]).values()} == {"DUPLICATE"}
    ambiguous = InventoryIssueItem(issue_request_id=document.id, line_no=2, product_id=item.product_id, batch_id=item.batch_id, unit_id=item.unit_id, warehouse_id=item.warehouse_id, location_id=item.location_id, requested_quantity=item.requested_quantity, issued_quantity=item.issued_quantity, status="ISSUED")
    db_session.add(ambiguous)
    db_session.flush()
    assert match_source(db_session, tx)["status"] == "AMBIGUOUS"


@pytest.mark.parametrize("executed_line", ["INVENTORY_TRANSFER"], indirect=True)
def test_transfer_pairs_require_both_unique_exact_visible_sides(db_session, executed_line):
    document, item, outbound = executed_line
    inbound = InventoryTransaction(transaction_no="TEST-SOURCE-TRANSFER-IN", transaction_type="INBOUND", warehouse_id=item.target_warehouse_id, location_id=item.target_location_id, product_id=item.product_id, batch_id=item.batch_id, unit_id=item.unit_id, quantity=item.transferred_quantity, source_type="INVENTORY_TRANSFER", source_id=document.id, operator_id=outbound.operator_id)
    db_session.add(inbound)
    db_session.flush()
    def pair(rows, scope=None):
        return next(row for row in transfer_pairs(db_session, item.batch_id, scope, rows, match_sources(db_session, rows)) if row["item_id"] == item.id)
    assert pair([outbound, inbound])["status"] == "MATCHED"
    assert pair([outbound])["status"] == "MISSING_SIDE"
    inbound.quantity += 1
    assert pair([outbound, inbound])["status"] == "CONFLICT"
    limited = pair([outbound], {item.source_warehouse_id})
    assert limited["status"] == "OUT_OF_SCOPE"
    assert limited["inbound_ids"] == [] and limited["inbound_quantity"] is None


@pytest.mark.parametrize("executed_line", ["INVENTORY_TRANSFER"], indirect=True)
def test_report_and_checklist_include_both_transfer_sides(client, db_session, demo_password, executed_line, monkeypatch):
    from app.modules.inventory import service as inventory_service

    document, item, outbound = executed_line
    inbound = InventoryTransaction(transaction_no="TEST-SOURCE-REPORT-IN", transaction_type="INBOUND", warehouse_id=item.target_warehouse_id, location_id=item.target_location_id, product_id=item.product_id, batch_id=item.batch_id, unit_id=item.unit_id, quantity=item.transferred_quantity, source_type="INVENTORY_TRANSFER", source_id=document.id, operator_id=outbound.operator_id)
    db_session.add(inbound)
    db_session.flush()
    balance = db_session.scalar(select(InventoryBalance).where(InventoryBalance.batch_id == item.batch_id, InventoryBalance.warehouse_id == item.source_warehouse_id, InventoryBalance.location_id == item.source_location_id))
    admin = login(client, "system_admin", demo_password)
    base = f"/api/v1/insights/batch-impact/{balance.id}"
    snapshot = client.post(f"{base}/snapshots", headers=admin)
    assert snapshot.status_code == 200, snapshot.text
    response = client.post(f"{base}/checks", headers=admin, params={"snapshot_id": snapshot.json()["id"]})
    assert response.status_code == 200, response.text
    assert {outbound.id, inbound.id} <= {row["transaction_id"] for row in response.json()}
    response = client.post(f"{base}/recall-reports", headers=admin)
    assert response.status_code == 200, response.text
    report_id = response.json()["id"]
    report = response.json()["result_json"]
    pair = next(row for row in report["transfer_pairs"] if row["item_id"] == item.id)
    assert pair["status"] == "MATCHED" and pair["review_status"] == "PENDING"
    assert pair["outbound_ids"] == [outbound.id] and pair["inbound_ids"] == [inbound.id]
    assert next(row for row in report["source_matches"] if row["transaction_id"] == inbound.id)["status"] == "MATCHED"
    monkeypatch.setattr(inventory_service, "accessible_warehouse_ids", lambda *_: {item.source_warehouse_id})
    response = client.post(f"{base}/recall-reports", headers=admin)
    assert response.status_code == 200, response.text
    limited = response.json()["result_json"]
    pair = next(row for row in limited["transfer_pairs"] if row["item_id"] == item.id)
    assert pair["status"] == "OUT_OF_SCOPE" and pair["inbound_quantity"] is None
    assert pair["inbound_ids"] == []
    assert inbound.id not in {row["transaction_id"] for row in limited["source_matches"]}
    assert client.get(f"{base}/recall-reports/{report_id}", headers=admin).status_code == 404
