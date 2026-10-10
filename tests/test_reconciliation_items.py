"""多产品、多到货、部分退货的行级对账回归。"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.inventory import service as inventory_service
from app.modules.inventory.model import InventoryBalance, InventoryBatch, WarehouseLocation
from app.modules.inventory.schema import InboundCreate
from app.modules.inventory_returns.model import InventoryReturnItem, InventoryReturnRequest
from app.modules.products.model import Product
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderItem
from app.modules.suppliers.model import Supplier
from app.modules.system.model import User
from .conftest import login

pytestmark = pytest.mark.integration


@pytest.fixture
def scenario(client, db_session, demo_password):
    headers = login(client, "system_admin", demo_password)
    approver_headers = login(client, "procurement_manager", demo_password)
    user = db_session.scalar(select(User).where(User.username == "system_admin"))
    products = list(db_session.scalars(select(Product).where(Product.status == "ACTIVE").limit(2)))
    supplier = db_session.scalar(select(Supplier).where(Supplier.status == "ACTIVE"))
    location = db_session.scalar(select(WarehouseLocation).where(WarehouseLocation.status == "ACTIVE"))
    suffix = uuid4().hex[:10]
    order = PurchaseOrder(po_no=f"TEST-ROW-{suffix}", supplier_id=supplier.id, buyer_id=user.id, order_amount=Decimal("314.3950528"), currency_code="CNY", status="COMPLETED")
    db_session.add(order); db_session.flush()
    lines = []
    for number, (product, price, tax) in enumerate(zip(products, ["10.123456", "20"], ["13", "0"]), 1):
        line = PurchaseOrderItem(po_id=order.id, line_no=number, product_id=product.id, product_name_snapshot=product.product_name, unit_id=product.unit_id, order_quantity=Decimal(10), received_quantity=Decimal(10), unit_price=Decimal(price), tax_rate=Decimal(tax))
        db_session.add(line); lines.append(line)
    db_session.flush()
    receipts = []
    for number, quantities in enumerate([(3, 4), (7, 6)], 1):
        delivery = Delivery(delivery_no=f"TEST-ROW-D{number}-{suffix}", po_id=order.id, supplier_id=supplier.id, status="ACCEPTED")
        db_session.add(delivery); db_session.flush()
        for line, qty in zip(lines, quantities):
            receipt = DeliveryItem(delivery_id=delivery.id, po_item_id=line.id, line_no=line.line_no, product_id=line.product_id, unit_id=line.unit_id, planned_quantity=qty, actual_quantity=qty)
            db_session.add(receipt); receipts.append(receipt)
        db_session.flush()
        inventory_service.create_inbound(db_session, user, InboundCreate(delivery_id=delivery.id, warehouse_id=location.warehouse_id, location_id=location.id))
    batch = db_session.scalar(select(InventoryBatch).where(InventoryBatch.source_delivery_id == receipts[0].delivery_id, InventoryBatch.product_id == lines[0].product_id))
    balance = db_session.scalar(select(InventoryBalance).where(InventoryBalance.batch_id == batch.id, InventoryBalance.location_id == location.id))
    return dict(headers=headers, approver_headers=approver_headers, order=order, lines=lines, receipts=receipts, balance=balance, supplier=supplier, user=user)


def return_body(s, quantity="2", linked=True):
    balance, receipt = s["balance"], s["receipts"][0]
    item = {key: getattr(balance, key) for key in ("product_id", "warehouse_id", "location_id", "batch_id", "unit_id")}
    item["requested_quantity"] = quantity
    if linked:
        item["source_delivery_item_id"] = receipt.id
    return {"supplier_id": s["supplier"].id, "po_id": s["order"].id, "reason": "多到货部分退货", "items": [item]}


def complete_return(client, s, quantity="2", linked=True):
    result = client.post("/api/v1/inventory/returns", headers=s["headers"], json=return_body(s, quantity, linked))
    assert result.status_code == 201, result.text
    identifier = result.json()["id"]
    for action in ("submit", "approve", "execute"):
        response = client.post(f"/api/v1/inventory/returns/{identifier}/{action}", headers=s["approver_headers"] if action == "approve" else s["headers"])
        assert response.status_code == 200, response.text
    return response.json()


def create_reconciliation(client, s):
    response = client.post("/api/v1/finance/reconciliations", headers=s["headers"], json={"po_id": s["order"].id})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def refresh(client, s, identifier, treatment="DEDUCT", note="供应商确认按退回数量扣款", precision=2):
    return client.post(f"/api/v1/finance/reconciliations/{identifier}/items/refresh", headers=s["headers"], json={"amount_precision": precision, "decisions": [{"po_item_id": s["lines"][0].id, "return_treatment": treatment, "treatment_note": note}]})


@pytest.mark.parametrize("treatment,quantity,total", [("DEDUCT", "8", "291.52"), ("REPLACEMENT", "10", "314.39")])
def test_partial_return_by_line_and_saved_versions(client, scenario, treatment, quantity, total):
    s = scenario
    returned = complete_return(client, s)
    assert returned["items"][0]["source_po_item_id"] == s["lines"][0].id
    assert returned["items"][0]["product_name"]
    identifier = create_reconciliation(client, s)
    path = f"/api/v1/finance/reconciliations/{identifier}"
    pending = client.get(path + "/items", headers=s["headers"]).json()
    assert pending["items"][0]["return_treatment"] == "PENDING"
    assert client.post(path + "/confirm", headers=s["headers"], json={}).status_code == 400
    result = refresh(client, s, identifier, treatment)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["version_no"] == 2
    assert Decimal(data["total_amount"]) == Decimal(total)
    first, second = data["items"]
    assert Decimal(first["reconciliation_quantity"]) == Decimal(quantity)
    assert Decimal(first["returned_quantity"]) == 2
    assert Decimal(second["returned_quantity"]) == 0
    assert len(first["basis_json"]["receipts"]) == 2
    assert not data["source_changed"]
    old = client.get(path + "/items", headers=s["headers"], params={"version": 1}).json()
    assert old["items"][0]["return_treatment"] == "PENDING"
    assert Decimal(old["total_amount"]) == Decimal("314.39")
    assert client.post(path + "/confirm", headers=s["headers"], json={}).status_code == 200
    assert refresh(client, s, identifier).status_code == 400


def test_changed_source_blocks_confirmation_and_preserves_history(client, db_session, scenario):
    s = scenario
    identifier = create_reconciliation(client, s)
    complete_return(client, s)
    path = f"/api/v1/finance/reconciliations/{identifier}"
    changed = client.get(path + "/items", headers=s["headers"]).json()
    assert changed["source_changed"]
    assert Decimal(changed["items"][0]["returned_quantity"]) == 0
    rejected = client.post(path + "/confirm", headers=s["headers"], json={})
    assert rejected.status_code == 400 and "来源已变化" in rejected.text
    assert refresh(client, s, identifier).status_code == 200


def test_source_candidates_and_mismatched_product_or_over_return(client, scenario):
    s = scenario
    sources = client.get("/api/v1/inventory/returns/sources", headers=s["headers"], params={"balance_id": s["balance"].id})
    assert sources.status_code == 200, sources.text
    assert sources.json()[0]["source_delivery_item_id"] == s["receipts"][0].id
    body = return_body(s)
    body["items"][0]["source_delivery_item_id"] = s["receipts"][1].id
    assert client.post("/api/v1/inventory/returns", headers=s["headers"], json=body).status_code == 400
    assert client.post("/api/v1/inventory/returns", headers=s["headers"], json=return_body(s, "4")).status_code == 400
    complete_return(client, s)
    assert client.post("/api/v1/inventory/returns", headers=s["headers"], json=return_body(s, "2")).status_code == 400


def test_unlinked_legacy_return_requires_manual_source_review(client, scenario):
    s = scenario
    complete_return(client, s, linked=False)
    identifier = create_reconciliation(client, s)
    data = client.get(f"/api/v1/finance/reconciliations/{identifier}/items", headers=s["headers"]).json()
    assert any("尚未关联" in warning for warning in data["warnings"])
    assert all(Decimal(row["returned_quantity"]) == 0 for row in data["items"])
    assert client.post(f"/api/v1/finance/reconciliations/{identifier}/confirm", headers=s["headers"], json={}).status_code == 400


def test_precision_and_required_treatment_note(client, scenario):
    s = scenario
    complete_return(client, s)
    identifier = create_reconciliation(client, s)
    assert refresh(client, s, identifier, note=" ").status_code == 400
    result = refresh(client, s, identifier, precision=3)
    assert result.status_code == 200, result.text
    first = result.json()["items"][0]
    assert Decimal(first["amount_excl_tax"]) == Decimal("80.988")
    assert Decimal(first["tax_amount"]) == Decimal("10.528")
    assert Decimal(result.json()["total_amount"]) == Decimal("291.516")


def test_read_only_finance_and_existing_invoice_block_refresh(client, scenario, demo_password):
    s = scenario
    identifier = create_reconciliation(client, s)
    viewer = login(client, "finance_viewer", demo_password)
    path = f"/api/v1/finance/reconciliations/{identifier}"
    assert client.get(path + "/items", headers=viewer).status_code in {403, 404}
    assert client.post(path + "/items/refresh", headers=viewer, json={}).status_code in {403, 404}
    invoice = client.post("/api/v1/finance/invoices", headers=s["headers"], json={"reconciliation_id": identifier, "invoice_number": uuid4().hex, "invoice_date": "2026-09-30", "amount_excl_tax": "1", "tax_amount": "0", "amount_incl_tax": "1"})
    assert invoice.status_code == 201, invoice.text
    assert refresh(client, s, identifier, treatment="NONE").status_code == 400


def test_all_returned_can_close_zero_payable_without_payment(client, db_session, scenario, demo_password):
    s = scenario
    items = []
    for receipt in s["receipts"]:
        batch = db_session.scalar(select(InventoryBatch).where(InventoryBatch.source_delivery_id == receipt.delivery_id, InventoryBatch.product_id == receipt.product_id))
        balance = db_session.scalar(select(InventoryBalance).where(InventoryBalance.batch_id == batch.id))
        item = {key: getattr(balance, key) for key in ("product_id", "warehouse_id", "location_id", "batch_id", "unit_id")}
        items.append(dict(item, source_delivery_item_id=receipt.id, requested_quantity=str(receipt.actual_quantity)))
    created = client.post("/api/v1/inventory/returns", headers=s["headers"], json={"supplier_id": s["supplier"].id, "reason": "全部退货", "items": items})
    assert created.status_code == 201, created.text
    for action in ("submit", "approve", "execute"):
        response = client.post(f"/api/v1/inventory/returns/{created.json()['id']}/{action}", headers=s["approver_headers"] if action == "approve" else s["headers"])
        assert response.status_code == 200, response.text
    identifier = create_reconciliation(client, s)
    path = f"/api/v1/finance/reconciliations/{identifier}"
    refreshed = client.post(path + "/items/refresh", headers=s["headers"], json={"decisions": [{"po_item_id": line.id, "return_treatment": "DEDUCT", "treatment_note": "供应商确认全部退货扣款"} for line in s["lines"]]})
    assert refreshed.status_code == 200, refreshed.text
    assert Decimal(refreshed.json()["total_amount"]) == 0
    assert client.post(path + "/confirm", headers=s["headers"], json={}).status_code == 200
    settlement = client.post("/api/v1/finance/settlements", headers=s["headers"], json={"reconciliation_id": identifier})
    assert settlement.status_code == 201, settlement.text
    assert client.post(f"/api/v1/finance/settlements/{settlement.json()['id']}/confirm", headers=s["headers"]).status_code == 400
    finance_approver = login(client, "finance_manager", demo_password)
    assert client.post(f"/api/v1/finance/settlements/{settlement.json()['id']}/confirm", headers=finance_approver).status_code == 200


def test_submitted_return_and_partial_quality_do_not_confirm(client, db_session, scenario):
    s = scenario
    created = client.post("/api/v1/inventory/returns", headers=s["headers"], json=return_body(s))
    assert created.status_code == 201
    assert client.post(f"/api/v1/inventory/returns/{created.json()['id']}/submit", headers=s["headers"]).status_code == 200
    identifier = create_reconciliation(client, s)
    assert client.post(f"/api/v1/finance/reconciliations/{identifier}/confirm", headers=s["headers"], json={}).status_code == 400
    delivery = db_session.get(Delivery, s["receipts"][0].delivery_id)
    delivery.status = "INSPECTING"; db_session.flush()
    assert refresh(client, s, identifier, treatment="NONE").status_code == 400


def test_new_return_after_snapshot_refreshes_to_pending_and_ai_reads_saved_basis(client, scenario):
    s = scenario
    identifier = create_reconciliation(client, s)
    complete_return(client, s)
    response = client.post(f"/api/v1/finance/reconciliations/{identifier}/items/refresh", headers=s["headers"], json={"decisions": []})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["return_treatment"] == "PENDING"
    assert refresh(client, s, identifier).status_code == 200
    analysis = client.get(f"/api/v1/insights/finance-difference/{s['order'].id}", headers=s["headers"])
    assert analysis.status_code == 200, analysis.text
    assert any("对账行 1" in row["label"] and "91.52" in row["value"] for row in analysis.json()["evidence"])
    assert not any("退货明细未直接关联" in warning for warning in analysis.json()["limitations"])
