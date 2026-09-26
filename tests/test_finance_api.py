"""财务对账、发票、付款和结算闭环测试。"""

import pytest
from decimal import Decimal
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.deliveries.model import Delivery
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.suppliers.model import Supplier
from app.modules.system.model import User

from .conftest import login


pytestmark = pytest.mark.integration


def test_finance_viewer_cannot_write(client: TestClient, demo_password: str) -> None:
    """财务查看者只能查询，不能创建对账单。"""

    headers = login(client, "finance_viewer", demo_password)
    response = client.post("/api/v1/finance/reconciliations", headers=headers, json={"po_id": 1})
    assert response.status_code == 403
    assert response.json()["message"] == "无权访问"


def test_finance_full_settlement_flow(client: TestClient, db_session, demo_password: str) -> None:
    """验证对账、发票核验、付款审批和结算关闭可以顺序完成。"""

    clerk = login(client, "finance_clerk", demo_password)
    manager = login(client, "finance_manager", demo_password)

    supplier_id = db_session.scalar(select(Supplier.id).where(Supplier.status == "ACTIVE").limit(1))
    buyer_id = db_session.scalar(select(User.id).where(User.username == "buyer"))
    assert supplier_id is not None and buyer_id is not None
    suffix = uuid4().hex[:10]
    order = PurchaseOrder(po_no=f"TEST-FIN-{suffix}", supplier_id=supplier_id,
        buyer_id=buyer_id, order_amount=Decimal("1000"), currency_code="CNY", status="COMPLETED")
    db_session.add(order)
    db_session.flush()
    db_session.add(Delivery(delivery_no=f"TEST-DLV-{suffix}", po_id=order.id,
        supplier_id=supplier_id, status="ACCEPTED"))
    db_session.flush()

    created = client.post("/api/v1/finance/reconciliations", headers=clerk, json={"po_id": order.id, "note": "接口测试对账"})
    assert created.status_code == 201, created.text
    reconciliation_id = created.json()["id"]
    duplicate = client.post("/api/v1/finance/reconciliations", headers=clerk, json={"po_id": order.id})
    assert duplicate.status_code == 409

    invoice = client.post(
        "/api/v1/finance/invoices",
        headers=clerk,
        json={
            "reconciliation_id": reconciliation_id,
            "invoice_number": "TEST-FINANCE-001",
            "invoice_date": "2026-09-17",
            "amount_excl_tax": "885",
            "tax_amount": "115",
            "amount_incl_tax": "1000",
        },
    )
    assert invoice.status_code == 201, invoice.text
    invoice_id = invoice.json()["id"]
    assert client.post(f"/api/v1/finance/invoices/{invoice_id}/submit", headers=clerk).status_code == 200
    assert client.post(f"/api/v1/finance/invoices/{invoice_id}/verify", headers=manager).status_code == 200
    assert client.post(f"/api/v1/finance/reconciliations/{reconciliation_id}/confirm", headers=manager, json={}).status_code == 200

    payment = client.post(
        "/api/v1/finance/payments",
        headers=clerk,
        json={"reconciliation_id": reconciliation_id, "amount": "1000", "payment_method": "BANK_TRANSFER"},
    )
    assert payment.status_code == 201, payment.text
    payment_id = payment.json()["id"]
    assert client.post(f"/api/v1/finance/payments/{payment_id}/approve", headers=manager).status_code == 200
    paid = client.post(f"/api/v1/finance/payments/{payment_id}/paid", headers=clerk, json={"transaction_ref": "TEST-BANK-001"})
    assert paid.status_code == 200, paid.text

    settlement = client.post("/api/v1/finance/settlements", headers=clerk, json={"reconciliation_id": reconciliation_id})
    assert settlement.status_code == 201, settlement.text
    settlement_id = settlement.json()["id"]
    confirmed = client.post(f"/api/v1/finance/settlements/{settlement_id}/confirm", headers=manager)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"

    reconciliation = client.get(f"/api/v1/finance/reconciliations/{reconciliation_id}", headers=manager)
    assert reconciliation.status_code == 200
    assert reconciliation.json()["status"] == "CLOSED"
