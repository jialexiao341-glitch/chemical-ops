"""Regression cases for complete samples, consumption and shared read scope."""
import asyncio
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.ai.text2sql import QueryPlan, build_statement, _validate_scoped_statement
from app.modules.ai.catalog import CATALOG
from app.modules.deliveries.model import Delivery
from app.modules.doc_kb.retrieve import resolve_doc_targets
from app.modules.finance import service as finance
from app.modules.finance.model import FinanceReconciliation, FinanceInvoice, FinancePayment, FinanceSettlement
from app.modules.insights.controller import _supplier_score, _replenishment
from app.modules.inventory.model import InventoryBalance, InventoryTransaction
from app.modules.purchase_orders import service as orders
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.suppliers.model import Supplier
from app.modules.system.model import User
from tests.conftest import login


def user(db, name):
    value = db.scalar(select(User).where(User.username == name))
    assert value is not None
    return value


def test_supplier_counts_all_records_including_older_than_other_suppliers(db_session):
    admin = user(db_session, "system_admin")
    suffix = uuid4().hex[:10]
    target = Supplier(supplier_code=f"REG-{suffix}", supplier_name="完整样本供应商")
    other = Supplier(supplier_code=f"OTHER-{suffix}", supplier_name="其他供应商")
    db_session.add_all([target, other]); db_session.flush()
    for index in range(105):
        db_session.add(PurchaseOrder(po_no=f"REG-{suffix}-{index}", supplier_id=target.id, buyer_id=admin.id, status="ORDERED"))
    for index in range(105):
        db_session.add(PurchaseOrder(po_no=f"OTHER-{suffix}-{index}", supplier_id=other.id, buyer_id=admin.id, status="ORDERED"))
    db_session.flush()
    target_order = db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.supplier_id == target.id))
    other_order = db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.supplier_id == other.id))
    for supplier, order in [(target, target_order), (other, other_order)]:
        for index in range(105):
            db_session.add(Delivery(delivery_no=f"DEL-{supplier.id}-{suffix}-{index}", po_id=order.id, supplier_id=supplier.id, status="RECEIVED", expected_arrival_date=date.today(), actual_arrival_date=date.today()))
    db_session.flush()
    result = _supplier_score(db_session, admin, target.id)
    assert next(x.value for x in result.evidence if x.label == "采购订单") == "105"
    assert next(x.value for x in result.evidence if x.label == "准时到货") == "105/105"
    assert not any("最近 100" in x for x in result.limitations)


def test_consumption_excludes_transfers_returns_and_uses_same_inventory_scope(db_session):
    admin = user(db_session, "system_admin")
    balance = db_session.scalar(select(InventoryBalance))
    assert balance is not None
    before = {x.label: x.value for x in _replenishment(db_session, admin, balance.id).evidence}
    old_quantity, old_count = before["已记录领用出库"].split(" · ")
    expected_consumed = Decimal(old_quantity) + 30
    suffix = uuid4().hex[:10]
    for source, quantity in [("ISSUE_REQUEST", 30), ("INVENTORY_TRANSFER", 90), ("INVENTORY_RETURN", 60)]:
        db_session.add(InventoryTransaction(transaction_no=f"REG-{suffix}-{source[-8:]}", transaction_type="OUTBOUND", source_type=source, quantity=quantity, warehouse_id=balance.warehouse_id, location_id=balance.location_id, product_id=balance.product_id, batch_id=balance.batch_id, unit_id=balance.unit_id, operator_id=admin.id, created_at=datetime.now()))
    db_session.flush()
    result = _replenishment(db_session, admin, balance.id)
    evidence = {x.label: x.value for x in result.evidence}
    new_quantity, new_count = evidence["已记录领用出库"].split(" · ")
    assert Decimal(new_quantity) == expected_consumed
    assert int(new_count.split()[0]) == int(old_count.split()[0]) + 1
    expected = sum((max(Decimal(0), x.quantity-x.locked_quantity) for x in db_session.scalars(select(InventoryBalance).where(InventoryBalance.product_id == balance.product_id, InventoryBalance.unit_id == balance.unit_id, InventoryBalance.status == "AVAILABLE"))), Decimal(0))
    assert evidence["范围内可用库存"].startswith(f"{expected.normalize():f} · 单位 #{balance.unit_id}")
    assert evidence["粗略日均 / 可用量覆盖天数"].startswith(f"{(expected_consumed / 30).quantize(Decimal('0.01'))} /")
    assert "不计消耗：调拨出库" in evidence
    assert "不计消耗：供应商退货" in evidence


def test_financial_scope_matches_lists_details_queries_and_does_not_grant_order_writes(client, db_session, demo_password):
    clerk = user(db_session, "finance_clerk")
    viewer = user(db_session, "finance_viewer")
    buyer = user(db_session, "system_admin")
    supplier = db_session.scalar(select(Supplier))
    suffix = uuid4().hex[:10]
    # No department and a different buyer makes the order invisible to an ordinary viewer.
    order = PurchaseOrder(po_no=f"SCOPE-{suffix}", supplier_id=supplier.id, buyer_id=buyer.id, department_id=None, status="COMPLETED", order_amount=100)
    db_session.add(order); db_session.flush()
    rec = FinanceReconciliation(reconciliation_no=f"REC-{suffix}", po_id=order.id, supplier_id=supplier.id, total_amount=100, created_by=clerk.id)
    db_session.add(rec); db_session.flush()
    documents = [
        FinanceInvoice(invoice_no=f"INV-{suffix}", reconciliation_id=rec.id, po_id=order.id, supplier_id=supplier.id, invoice_number=suffix, invoice_date=date.today(), amount_excl_tax=100, tax_amount=0, amount_incl_tax=100, submitted_by=clerk.id),
        FinancePayment(payment_no=f"PAY-{suffix}", reconciliation_id=rec.id, po_id=order.id, supplier_id=supplier.id, amount=100, payment_method="BANK_TRANSFER", requested_by=clerk.id),
        FinanceSettlement(settlement_no=f"SET-{suffix}", reconciliation_id=rec.id, po_id=order.id, supplier_id=supplier.id, settlement_amount=100, created_by=clerk.id),
    ]
    db_session.add_all(documents); db_session.flush()
    assert orders.read_order(db_session, clerk, order.id).id == order.id
    with pytest.raises(ResourceNotFoundError):
        orders.get_order(db_session, clerk, order.id)
    headers = login(client, "finance_clerk", demo_password)
    restricted = login(client, "finance_viewer", demo_password)
    for name, value in [("reconciliations", rec), *zip(["invoices", "payments", "settlements"], documents)]:
        assert client.get(f"/api/v1/finance/{name}/{value.id}", headers=headers).status_code == 200
        denied = client.get(f"/api/v1/finance/{name}/{value.id}", headers=restricted)
        assert denied.status_code in {403, 404}
        page = client.get(f"/api/v1/finance/{name}", headers=headers, params={"page_size":100}).json()
        assert value.id in {x["id"] for x in page["items"]}
        page = client.get(f"/api/v1/finance/{name}", headers=restricted)
        if page.status_code == 200:
            assert value.id not in {x["id"] for x in page.json()["items"]}
    for name, value in [("invoices", documents[0]), ("payments", documents[1])]:
        params = {"reconciliation_id": rec.id, "page_size": 100}
        allowed_page = client.get(f"/api/v1/finance/{name}", headers=headers, params=params)
        assert allowed_page.status_code == 200
        assert allowed_page.json()["total"] == 1
        assert [row["id"] for row in allowed_page.json()["items"]] == [value.id]

        restricted_page = client.get(f"/api/v1/finance/{name}", headers=restricted, params=params)
        if restricted_page.status_code == 200:
            assert restricted_page.json()["total"] == 0
            assert restricted_page.json()["items"] == []
        else:
            assert restricted_page.status_code == 403
    with pytest.raises(ResourceNotFoundError):
        finance.confirm_reconciliation(db_session, viewer, rec.id, None)
    assert rec.status == "DRAFT"
    items, _ = finance.list_reconciliations(db_session, viewer, status=None, supplier_id=supplier.id, page=1, page_size=100)
    assert rec.id not in {x.id for x in items}
    assert client.get(f"/api/v1/insights/finance-difference/{order.id}", headers=headers).status_code == 200
    assert client.get(f"/api/v1/insights/finance-difference/{order.id}", headers=restricted).status_code in {403,404}
    for dataset in ["purchase_orders", "finance_reconciliations", "finance_invoices", "finance_payments"]:
        plan = QueryPlan(dataset=dataset, metric="count", time_field=None)
        statement = build_statement(plan, db_session, viewer)
        _validate_scoped_statement(statement, db_session, CATALOG[dataset].tables, literal_binds=False)
        # Restricted aggregates exclude all rows of the otherwise visible financial order.
        if dataset.startswith("finance"):
            model = {"finance_reconciliations":FinanceReconciliation,"finance_invoices":FinanceInvoice,"finance_payments":FinancePayment}[dataset]
            scoped = statement.where(model.po_id == order.id)
            assert db_session.execute(scoped).scalar() == 0
            allowed = build_statement(plan, db_session, clerk).where(model.po_id == order.id)
            assert db_session.execute(allowed).scalar() == 1


@pytest.mark.parametrize("question,expected", [
    ("Ｅｔｈｙｌｅｎｅ  ｇｌｙｃｏｌ 的闪点", ["107-21-1"]),
    ("1 – Butanol 的分子式", ["71-36-3"]),
    ("MEG 的沸点", ["107-21-1"]),
    ("Methanol 的沸点", []),
    ("比较氯乙醇和乙醇", ["107-07-3", "64-17-5"]),
    ("查 technical data sheet", []),
])
def test_names_use_document_metadata_and_do_not_match_english_substrings(question, expected):
    batches = iter([
        [("64-17-5", "乙醇", "Ethanol", None), ("107-07-3", "氯乙醇", None, None)],
        [("107-21-1", None, {"name_en":"Ethylene glycol","synonyms":["MEG"]}), ("71-36-3",None,{"name_en":"1-Butanol"}), ("107-21-1",None,{"name_en":"Technical Data Sheet"})],
    ])
    db = SimpleNamespace(execute=lambda _stmt: SimpleNamespace(all=lambda: next(batches)))
    assert asyncio.run(resolve_doc_targets(db, question)) == expected


def test_ambiguous_document_alias_requires_cas():
    def db():
        batches = iter([[], [("64-17-5",None,{"synonyms":["shared"]}), ("67-56-1",None,{"synonyms":["shared"]})]])
        return SimpleNamespace(execute=lambda _stmt:SimpleNamespace(all=lambda:next(batches)))
    with pytest.raises(BusinessValidationError, match="多个化学品"):
        asyncio.run(resolve_doc_targets(db(), "shared 的闪点"))
    assert asyncio.run(resolve_doc_targets(db(), "shared CAS 64-17-5 的闪点")) == ["64-17-5"]


@pytest.mark.parametrize("dataset", ["purchase_requests", "deliveries", "quality_acceptances", "inventory", "exceptions"])
def test_aggregate_scope_excludes_foreign_records_and_preserves_authorized_records(db_session, dataset):
    from app.modules.purchase_requests.model import PurchaseRequest
    from app.modules.quality_acceptances.model import QualityAcceptance
    from app.modules.quality_acceptances import service as quality
    from app.modules.inventory.model import Warehouse, WarehouseLocation
    from app.modules.operation_exceptions.model import OperationException

    actor = user(db_session, "quality_inspector" if dataset == "quality_acceptances" else "warehouse_receiver" if dataset == "inventory" else "buyer")
    other = user(db_session, "system_admin")
    actor.department_id = None
    suffix = uuid4().hex[:12]
    template_order = db_session.scalar(select(PurchaseOrder))
    order = PurchaseOrder(po_no=f"SQL-SCOPE-{suffix}", supplier_id=template_order.supplier_id, buyer_id=other.id, department_id=None)
    db_session.add(order); db_session.flush()
    delivery = Delivery(delivery_no=f"SQL-DEL-{suffix}", po_id=order.id, supplier_id=order.supplier_id, status="RECEIVED")
    db_session.add(delivery); db_session.flush()
    if dataset == "purchase_requests":
        record = PurchaseRequest(request_no=f"SQL-REQ-{suffix}", applicant_id=other.id, purpose="scope regression")
        authorize = lambda: setattr(record, "applicant_id", actor.id)
    elif dataset == "deliveries":
        record = delivery
        authorize = lambda: setattr(order, "buyer_id", actor.id)
    elif dataset == "quality_acceptances":
        record = QualityAcceptance(acceptance_no=f"SQL-QA-{suffix}", delivery_id=delivery.id, inspector_id=other.id, result="PENDING")
        authorize = lambda: setattr(record, "inspector_id", actor.id)
    elif dataset == "exceptions":
        record = OperationException(exception_no=f"SQL-EX-{suffix}", exception_type="DELIVERY", source_type="OTHER", source_id=order.id, owner_id=other.id, description="scope regression")
        authorize = lambda: setattr(record, "owner_id", actor.id)
    else:
        from app.modules.system.model import UserWarehouseGrant, UserWarehouseScope
        template = db_session.scalar(select(InventoryBalance))
        warehouse = Warehouse(warehouse_code=f"SQL-WH-{suffix}", warehouse_name="scope regression", manager_id=other.id)
        db_session.add(warehouse); db_session.flush()
        location = WarehouseLocation(warehouse_id=warehouse.id, location_code=f"SQL-LOC-{suffix}", location_name="scope regression")
        db_session.add(location); db_session.flush()
        record = InventoryBalance(product_id=template.product_id, batch_id=template.batch_id, warehouse_id=warehouse.id, location_id=location.id, unit_id=template.unit_id, quantity=Decimal("1"), locked_quantity=Decimal("0"), status="AVAILABLE")
        if db_session.get(UserWarehouseScope, actor.id) is None:
            db_session.add(UserWarehouseScope(user_id=actor.id))
            db_session.flush()
        authorize = lambda: db_session.add(UserWarehouseGrant(user_id=actor.id, warehouse_id=warehouse.id))
    db_session.add(record); db_session.flush()
    model = type(record)
    plan = QueryPlan(dataset=dataset, metric="count", time_field=None)
    statement = build_statement(plan, db_session, actor).where(model.id == record.id)
    _validate_scoped_statement(statement, db_session, CATALOG[dataset].tables, literal_binds=False)
    assert db_session.execute(statement).scalar() == 0
    resource_type = {"deliveries": "DELIVERY", "quality_acceptances": "QUALITY_ACCEPTANCE", "exceptions": "OPERATION_EXCEPTION"}.get(dataset)
    if resource_type:
        from app.modules.files.service import _can_access_resource_instance
        assert not _can_access_resource_instance(db_session, actor, resource_type, record)
    if dataset == "quality_acceptances":
        with pytest.raises(ResourceNotFoundError):
            quality.get_acceptance(db_session, actor, record.id)
    authorize(); db_session.flush()
    statement = build_statement(plan, db_session, actor).where(model.id == record.id)
    _validate_scoped_statement(statement, db_session, CATALOG[dataset].tables, literal_binds=False)
    assert db_session.execute(statement).scalar() == 1
    if resource_type:
        assert _can_access_resource_instance(db_session, actor, resource_type, record)
    if dataset == "quality_acceptances":
        assert quality.get_acceptance(db_session, actor, record.id).id == record.id


@pytest.mark.parametrize("username", ["warehouse_receiver", "buyer", "finance_viewer"])
def test_quality_readonly_scope_matches_detail_total_sql_and_attachment(db_session, username):
    from app.modules.quality_acceptances.model import QualityAcceptance
    from app.modules.quality_acceptances import service as quality
    from app.modules.files.service import _can_access_resource_instance

    actor = user(db_session, username)
    other = user(db_session, "system_admin")
    actor.department_id = None
    template = db_session.scalar(select(PurchaseOrder))
    suffix = uuid4().hex[:12]
    order = PurchaseOrder(po_no=f"QA-READ-{suffix}", supplier_id=template.supplier_id, buyer_id=other.id)
    db_session.add(order); db_session.flush()
    delivery = Delivery(delivery_no=f"QA-READ-{suffix}", po_id=order.id, supplier_id=order.supplier_id)
    db_session.add(delivery); db_session.flush()
    acceptance = QualityAcceptance(acceptance_no=f"QA-READ-{suffix}", delivery_id=delivery.id, inspector_id=other.id, result="PENDING")
    db_session.add(acceptance); db_session.flush()
    plan = QueryPlan(dataset="quality_acceptances", metric="count", time_field=None)
    for visible in (False, True):
        if visible:
            order.buyer_id = actor.id
            db_session.flush()
        condition = build_statement(plan, db_session, actor).where(QualityAcceptance.id == acceptance.id)
        _validate_scoped_statement(condition, db_session, CATALOG[plan.dataset].tables, literal_binds=False)
        assert db_session.execute(condition).scalar() == int(visible)
        rows, total = quality.list_acceptances(db_session, actor, result=None, page=1, page_size=100)
        assert total == db_session.execute(build_statement(plan, db_session, actor)).scalar()
        assert len(rows) == min(total, 100)
        assert (acceptance.id in {row.id for row in rows}) == visible
        assert _can_access_resource_instance(db_session, actor, "QUALITY_ACCEPTANCE", acceptance) == visible
        if visible:
            assert quality.get_acceptance(db_session, actor, acceptance.id).id == acceptance.id
        else:
            with pytest.raises(ResourceNotFoundError):
                quality.get_acceptance(db_session, actor, acceptance.id)
