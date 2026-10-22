"""中选报价生成订单草稿动作契约。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.ai import action_handlers
from app.modules.purchase_orders import service as order_service


def _source():
    rfq = SimpleNamespace(
        id=14, rfq_no="RFQ-014", requester_id=5, source_request_id=9, status="CLOSED",
        quote_deadline=None, requested_delivery_date=date(2026, 11, 10), delivery_requirements="避光运输",
        items=[SimpleNamespace(id=31, line_no=1, product_id=22, requested_name="乙醇",
                               quantity=Decimal("2"), unit_id=4, required_delivery_date=date(2026, 11, 10),
                               technical_requirements="纯度99%", source_request_item_id=81)],
        suppliers=[SimpleNamespace(supplier_id=8)],
    )
    quote_item = SimpleNamespace(
        id=41, rfq_item_id=31, supplier_product_id=81, supplier_model="Q-1", quoted_quantity=Decimal("2"),
        unit_id=4, unit_price=Decimal("12.5"), tax_rate=Decimal("13"), lead_days=10,
        payment_terms="月结30天", moq_quantity=None, moq_unit_id=None,
    )
    quote = SimpleNamespace(
        id=51, rfq_id=14, quote_no="Q-051", supplier_id=8, quote_version=1,
        currency_code="CNY", status="SELECTED", valid_until=date(2026, 12, 1), items=[quote_item], rfq=rfq,
    )
    comparison = SimpleNamespace(
        id=71, rfq_id=14, comparison_no="QC-071", status="CONFIRMED", selected_quote_id=51,
        conclusion="综合成本适合", items=[],
    )
    request_item = SimpleNamespace(id=81, quantity=Decimal("3"), fulfilled_quantity=Decimal("1"))
    request = SimpleNamespace(
        id=9, request_no="PR-009", applicant_id=5, department_id=2, status="APPROVED", purpose="实验用料",
        priority="NORMAL", budget_amount=None, currency_code="CNY", expected_date=date(2026, 11, 10),
        items=[request_item], updated_at=None,
    )
    return rfq, comparison, quote, request, {31: rfq.items[0]}, {31: quote_item}


@pytest.fixture
def handler_source(monkeypatch):
    rfq, comparison, quote, request, rfq_items, quote_items = _source()
    monkeypatch.setattr(order_service, "_validate_source", lambda *_args, **_kwargs: (
        comparison, quote, request, rfq_items, quote_items,
    ))
    from app.modules.rfqs import service as rfq_service

    monkeypatch.setattr(rfq_service, "get_rfq", lambda _db, _user, rfq_id, **_kwargs: (
        rfq if rfq_id == rfq.id else (_ for _ in ()).throw(ResourceNotFoundError("询价不可见"))
    ))
    return rfq, comparison, quote, request


def test_handler_is_registered_and_requires_order_write_plus_rfq_read():
    assert "purchase_order.create_draft" in action_handlers.registered_action_types()
    assert action_handlers.required_permissions("purchase_order.create_draft") == {
        "procurement.orders.write", "procurement.rfqs.read",
    }


def test_prepare_builds_source_backed_line_preview_without_writes(handler_source):
    handler = action_handlers.get_handler("purchase_order.create_draft")
    db = SimpleNamespace(scalar=lambda _query: None, get=lambda *_args: SimpleNamespace(unit_name="升"), added=[])
    user = SimpleNamespace(id=5)

    prepared = handler.prepare(db, user, {"comparison_id": 71, "quote_id": 51})

    assert db.added == []
    assert prepared["resource_type"] == "RFQ"
    assert prepared["resource_id"] == 14
    assert prepared["payload"] == {
        "comparison_id": 71, "quote_id": 51, "delivery_address": None,
        "expected_arrival_date": None, "note": None,
    }
    assert any("收货地址" in warning for warning in prepared["warnings"])
    line = prepared["evidence"][0]["items"][0]
    assert line["payment_terms"] == "月结30天"
    assert line["available_request_quantity"] == "2"
    assert any(item["field"] == "expected_arrival_date" for item in prepared["diff"])


@pytest.mark.parametrize("payload", [
    {"comparison_id": 71, "quote_id": 51, "supplier_id": 8},
    {"comparison_id": True, "quote_id": 51},
])
def test_prepare_rejects_client_supplied_source_fields_and_invalid_identifiers(handler_source, payload):
    handler = action_handlers.get_handler("purchase_order.create_draft")

    with pytest.raises(BusinessValidationError):
        handler.prepare(SimpleNamespace(scalar=lambda _query: None), SimpleNamespace(id=5), payload)


def test_prepare_rejects_inaccessible_rfq_even_when_quote_id_is_known(handler_source, monkeypatch):
    from app.modules.rfqs import service as rfq_service

    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        ResourceNotFoundError("询价不可见")))
    handler = action_handlers.get_handler("purchase_order.create_draft")

    with pytest.raises(ResourceNotFoundError):
        handler.prepare(SimpleNamespace(scalar=lambda _query: None), SimpleNamespace(id=5),
                        {"comparison_id": 71, "quote_id": 51})


@pytest.mark.parametrize("field,value", [
    ("status", "DRAFT"),
    ("selected_quote_id", 99),
])
def test_prepare_rejects_unconfirmed_or_different_selected_quote(handler_source, field, value):
    _rfq, comparison, _quote, _request = handler_source
    setattr(comparison, field, value)
    handler = action_handlers.get_handler("purchase_order.create_draft")

    with pytest.raises(BusinessValidationError):
        handler.prepare(SimpleNamespace(scalar=lambda _query: None), SimpleNamespace(id=5),
                        {"comparison_id": 71, "quote_id": 51})


def test_prepare_rejects_unapproved_source_request(handler_source):
    _rfq, _comparison, _quote, request = handler_source
    request.status = "PENDING"
    handler = action_handlers.get_handler("purchase_order.create_draft")

    with pytest.raises(BusinessValidationError, match="未审批通过"):
        handler.prepare(SimpleNamespace(scalar=lambda _query: None), SimpleNamespace(id=5),
                        {"comparison_id": 71, "quote_id": 51})


def test_prepare_rejects_existing_order_for_comparison(handler_source):
    handler = action_handlers.get_handler("purchase_order.create_draft")

    with pytest.raises(BusinessValidationError, match="已经生成"):
        handler.prepare(SimpleNamespace(scalar=lambda _query: 99), SimpleNamespace(id=5),
                        {"comparison_id": 71, "quote_id": 51})


def test_validate_current_rebuilds_snapshot_and_execute_uses_commit_false(handler_source, monkeypatch):
    from app.modules.purchase_orders.schema import PurchaseOrderRead

    handler = action_handlers.get_handler("purchase_order.create_draft")
    db = SimpleNamespace(scalar=lambda _query: None, get=lambda *_args: SimpleNamespace(unit_name="升"))
    user = SimpleNamespace(id=5)
    payload = {"comparison_id": 71, "quote_id": 51, "delivery_address": "仓库 A",
               "expected_arrival_date": None, "note": None}
    prepared = handler.prepare(db, user, payload)
    proposal = SimpleNamespace(payload=prepared["payload"], resource_id="14",
                               expected_resource_snapshot=prepared["snapshot"])
    handler.validate_current(db, user, proposal, for_update=True)

    calls = []
    order = SimpleNamespace(id=77)
    monkeypatch.setattr(order_service, "create_order", lambda *_args, **kwargs: calls.append(kwargs) or order)
    monkeypatch.setattr(PurchaseOrderRead, "model_validate", lambda value: SimpleNamespace(
        model_dump=lambda **_kwargs: {"id": value.id, "po_no": "PO77", "status": "DRAFT"}
    ))
    assert handler.execute(db, user, proposal, commit=False) == {"id": 77, "po_no": "PO77", "status": "DRAFT"}
    assert calls == [{"commit": False}]
