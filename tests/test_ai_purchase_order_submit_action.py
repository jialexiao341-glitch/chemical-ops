"""采购订单提交审批提案：草稿校验、快照与领域事务。"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.ai import action_handlers, schema
from app.modules.purchase_orders import service as order_service


def _order(status="DRAFT", item_count=1):
    return SimpleNamespace(
        id=1153, po_no="PO20261004004266", status=status, updated_at=datetime(2026, 10, 25, 4, 0, 0),
        supplier_id=3, buyer_id=5, order_amount=Decimal("1200.00"), currency_code="CNY",
        department_id=2, delivery_address=None, order_date=None, expected_arrival_date=None,
        supplier_confirmed_at=None, approved_at=None, cancelled_at=None, cancel_reason=None, note=None,
        source_comparison_id=None, source_quote_id=None, source_request_id=None,
        created_at=datetime(2026, 10, 25), items=[object()] * item_count, approvals=[], events=[],
    )


def _patch(monkeypatch, order):
    monkeypatch.setattr(order_service, "get_order_by_no", lambda *_args, **_kwargs: order)
    monkeypatch.setattr(order_service, "get_order", lambda *_args, **_kwargs: order)


def test_prepare_requires_draft_with_items_and_builds_snapshot(monkeypatch):
    order = _order()
    _patch(monkeypatch, order)
    handler = action_handlers.PurchaseOrderSubmitHandler()
    prepared = handler.prepare(None, SimpleNamespace(id=5), {"po_no": order.po_no})

    assert prepared["payload"] == {"order_id": order.id}
    assert prepared["snapshot"]["status"] == "DRAFT"
    assert prepared["snapshot"]["item_count"] == 1
    assert prepared["evidence"][0]["po_no"] == order.po_no
    assert prepared["risk_level"] == "HIGH"

    _patch(monkeypatch, _order(status="APPROVING"))
    with pytest.raises(BusinessValidationError, match="草稿"):
        handler.prepare(None, SimpleNamespace(id=5), {"po_no": order.po_no})
    _patch(monkeypatch, _order(item_count=0))
    with pytest.raises(BusinessValidationError, match="明细"):
        handler.prepare(None, SimpleNamespace(id=5), {"po_no": order.po_no})


def test_validate_current_rejects_changed_order(monkeypatch):
    order = _order()
    _patch(monkeypatch, order)
    handler = action_handlers.PurchaseOrderSubmitHandler()
    prepared = handler.prepare(None, SimpleNamespace(id=5), {"po_no": order.po_no})
    proposal = SimpleNamespace(payload=prepared["payload"],
                               expected_resource_snapshot=prepared["snapshot"])

    handler.validate_current(None, SimpleNamespace(id=5), proposal, for_update=False)
    order.updated_at = datetime(2026, 10, 25, 5, 0, 0)
    with pytest.raises(BusinessValidationError, match="已变化"):
        handler.validate_current(None, SimpleNamespace(id=5), proposal, for_update=False)


def test_execute_uses_domain_service_with_caller_transaction(monkeypatch):
    order = _order(item_count=0)
    _patch(monkeypatch, order)
    calls = []

    def submit(_db, _user, order_id, *, commit=True):
        calls.append((order_id, commit))
        order.status = "APPROVING"
        return order

    monkeypatch.setattr(order_service, "submit_order", submit)
    proposal = SimpleNamespace(payload={"order_id": order.id})
    result = action_handlers.PurchaseOrderSubmitHandler().execute(
        None, SimpleNamespace(id=5), proposal, commit=False)

    assert calls == [(order.id, False)]
    assert result["status"] == "APPROVING"
    assert result["po_no"] == order.po_no


def test_understanding_requires_exact_order_number():
    with pytest.raises(ValueError):
        schema.Understanding(purpose="purchase_order_submit")
    decision = schema.Understanding(purpose="purchase_order_submit",
                                    slots={"po_no": "PO20261004004266"})
    assert decision.route == "purchase_order_submit"
    assert decision.execution_mode == "none"
