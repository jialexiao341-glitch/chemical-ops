"""Finance differences keep receipt lines separate from document totals."""

from decimal import Decimal
import re
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation
from app.modules.insights.model import FinanceDifferenceCheck, FinanceDifferenceEvent
from app.modules.products.model import Product
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderItem
from app.modules.suppliers.model import Supplier
from app.modules.system.model import User

from .conftest import login


pytestmark = pytest.mark.integration


def test_receipt_line_and_document_review_are_separate(client, db_session, demo_password):
    clerk_user = db_session.scalar(select(User).where(User.username == "finance_clerk"))
    manager_user = db_session.scalar(select(User).where(User.username == "finance_manager"))
    supplier = db_session.scalar(select(Supplier).where(Supplier.status == "ACTIVE"))
    product = db_session.scalar(select(Product).where(Product.status == "ACTIVE"))
    assert clerk_user and manager_user and supplier and product
    suffix = uuid4().hex[:10]
    order = PurchaseOrder(po_no=f"TEST-DIFF-{suffix}", supplier_id=supplier.id, buyer_id=clerk_user.id, department_id=clerk_user.department_id, order_amount=Decimal("1100"), currency_code="CNY", status="PARTIAL")
    db_session.add(order)
    db_session.flush()
    line = PurchaseOrderItem(po_id=order.id, line_no=1, product_id=product.id, product_name_snapshot=product.product_name, order_quantity=Decimal("10"), received_quantity=Decimal("6"), unit_id=product.unit_id, unit_price=Decimal("100"), tax_rate=Decimal("10"), status="PARTIAL")
    db_session.add(line)
    db_session.flush()
    delivery = Delivery(delivery_no=f"TEST-DIFF-DLV-{suffix}", po_id=order.id, supplier_id=supplier.id, status="ACCEPTED")
    db_session.add(delivery)
    db_session.flush()
    db_session.add(DeliveryItem(delivery_id=delivery.id, po_item_id=line.id, product_id=product.id, line_no=1, planned_quantity=Decimal("10"), actual_quantity=Decimal("6"), short_quantity=Decimal("4"), unit_id=product.unit_id))
    reconciliation = FinanceReconciliation(reconciliation_no=f"TEST-DIFF-REC-{suffix}", po_id=order.id, supplier_id=supplier.id, currency_code="CNY", total_amount=Decimal("1100"), status="DRAFT", created_by=clerk_user.id)
    db_session.add(reconciliation)
    db_session.flush()
    db_session.add_all([
        FinanceInvoice(invoice_no=f"TEST-INV-A-{suffix}", reconciliation_id=reconciliation.id, po_id=order.id, supplier_id=supplier.id, invoice_number=f"A-{suffix}", invoice_date=date(2026, 9, 30), amount_excl_tax=Decimal("500"), tax_amount=Decimal("50"), amount_incl_tax=Decimal("550"), currency_code="CNY", status="VERIFIED", submitted_by=clerk_user.id),
        FinanceInvoice(invoice_no=f"TEST-INV-B-{suffix}", reconciliation_id=reconciliation.id, po_id=order.id, supplier_id=supplier.id, invoice_number=f"B-{suffix}", invoice_date=date(2026, 9, 30), amount_excl_tax=Decimal("100"), tax_amount=Decimal("10"), amount_incl_tax=Decimal("110"), currency_code="CNY", status="REJECTED", submitted_by=clerk_user.id),
        FinancePayment(payment_no=f"TEST-PAY-A-{suffix}", reconciliation_id=reconciliation.id, po_id=order.id, supplier_id=supplier.id, amount=Decimal("200"), currency_code="CNY", payment_method="BANK_TRANSFER", status="PAID", requested_by=clerk_user.id),
        FinancePayment(payment_no=f"TEST-PAY-B-{suffix}", reconciliation_id=reconciliation.id, po_id=order.id, supplier_id=supplier.id, amount=Decimal("100"), currency_code="CNY", payment_method="BANK_TRANSFER", status="REQUESTED", requested_by=clerk_user.id),
    ])
    db_session.flush()

    clerk = login(client, "finance_clerk", demo_password)
    manager = login(client, "finance_manager", demo_password)
    viewer = login(client, "finance_viewer", demo_password)
    base = f"/api/v1/insights/finance-difference/{order.id}"
    analysis = client.get(base, headers=clerk)
    assert analysis.status_code == 200, analysis.text
    evidence = analysis.json()["evidence"]
    # 展示层会去掉小数尾零；按数值验证业务结果，不依赖金额展示为 660 或 660.00。
    def number_after(value, label):
        match = re.search(re.escape(label) + r"\s+(-?\d+(?:\.\d+)?)", value)
        assert match is not None, value
        return Decimal(match.group(1))

    line_evidence = next(row['value'] for row in evidence if row['label'].startswith('订单行 '))
    assert number_after(line_evidence, '已验收到货') == Decimal('6')
    assert number_after(line_evidence, '已验收到货含税估算') == Decimal('660')
    arrival = next(row['value'] for row in evidence if row['label'].startswith('到货行 '))
    assert number_after(arrival, '短交') == Decimal('4')
    for label, expected in [('已核验发票 / 未开票差额', (Decimal('550'), Decimal('550'))),
                            ('已付款 / 未付款差额', (Decimal('200'), Decimal('900')))]:
        value = next(row['value'] for row in evidence if row['label'] == label)
        assert tuple(Decimal(part.strip()) for part in value.removesuffix(' CNY').split('/')) == expected
    assert any("发票和付款没有订单行分摊字段" in item for item in analysis.json()["limitations"])

    snapshot = client.post(f"{base}/snapshots", headers=clerk)
    assert snapshot.status_code == 200, snapshot.text
    assert client.post(f"{base}/checks", headers=viewer, params={"snapshot_id": snapshot.json()["id"]}).status_code == 403
    first = client.post(f"{base}/checks", headers=clerk, params={"snapshot_id": snapshot.json()["id"]})
    assert first.status_code == 200, first.text
    assert {row["scope_key"] for row in first.json()} >= {f"LINE:{line.id}", "DOCUMENTS"}
    assert len([row for row in first.json() if row['scope_key'].startswith('INVOICE:')]) == 2
    repeated = client.post(f"{base}/checks", headers=clerk, params={"snapshot_id": snapshot.json()["id"]})
    assert [row["id"] for row in repeated.json()] == [row["id"] for row in first.json()]
    check = first.json()[0]
    check_url = f"{base}/checks/{check['id']}"
    assigned = client.patch(check_url, headers=clerk, json={"assignee_id": manager_user.id})
    assert assigned.status_code == 200, assigned.text
    checked = client.patch(check_url, headers=manager, json={"status": "CHECKED", "finding": "已按到货明细核实"})
    assert checked.status_code == 200, checked.text
    assert client.patch(check_url, headers=manager, json={"status": "VERIFIED"}).status_code == 400
    reviewed = client.patch(check_url, headers=clerk, json={"status": "VERIFIED"})
    assert reviewed.status_code == 200, reviewed.text
    assert db_session.get(FinanceDifferenceCheck, check["id"]).status == "VERIFIED"
    assert len(client.get(f"{check_url}/events", headers=clerk).json()) == 3
    assert db_session.scalar(select(FinanceDifferenceEvent).where(FinanceDifferenceEvent.check_id == check["id"])) is not None
