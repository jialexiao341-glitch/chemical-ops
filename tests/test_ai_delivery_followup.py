"""交期草稿仅使用服务端订单事实，保存不发送。"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.ai import action_handlers, action_proposals, capabilities
from app.modules.purchase_orders import followup, service as order_service


def order_fixture():
    return SimpleNamespace(
        id=41, po_no="PO20261004004266", supplier_id=7, buyer_id=3,
        department_id=2, status="PARTIAL", expected_arrival_date=date(2026, 10, 25),
        supplier_confirmed_at=None, updated_at=datetime(2026, 10, 25, 4),
        items=[SimpleNamespace(
            id=51, line_no=1, product_name_snapshot="乙醇", unit_id=1,
            order_quantity=Decimal("50.000000"), received_quantity=Decimal("12.500000"),
            planned_arrival_date=date(2026, 10, 24), status="PARTIAL",
        ), SimpleNamespace(
            id=52, line_no=2, product_name_snapshot="甲醇", unit_id=2,
            order_quantity=Decimal("20"), received_quantity=Decimal("20"),
            planned_arrival_date=None, status="FULFILLED",
        )],
    )


@pytest.fixture
def source(monkeypatch):
    order = order_fixture()
    calls = []

    def get_order(_db, _user, order_id, *, for_update=False):
        assert order_id == order.id
        calls.append(for_update)
        return order

    monkeypatch.setattr(order_service, "get_order", get_order)
    monkeypatch.setattr(followup, "business_today", lambda: date(2026, 10, 26))
    db = SimpleNamespace(get=lambda _model, key: SimpleNamespace(unit_name={1: "升", 2: "千克"}[key]))
    return db, SimpleNamespace(id=3), order, calls


def test_registered_as_page_action_and_owned_inbox():
    assert "deliveries.followup_draft" in action_proposals.INBOX_ACTION_TYPES
    assert capabilities.ACTION_ENTRIES["deliveries.followup_draft"][1] == "business_page"
    assert action_handlers.required_permissions("deliveries.followup_draft") == {
        "procurement.orders.read", "procurement.orders.write",
    }


def test_body_uses_line_dates_decimal_units_and_only_outstanding_lines(source):
    db, user, order, _ = source
    result = followup.build_followup(db, user, order.id, note="请反馈分批发货安排")
    assert "PO20261004004266" in result["message"]
    assert "37.5 升" in result["message"]
    assert "12.5 升" in result["message"]
    assert "2026-10-24" in result["message"]
    assert "甲醇" not in result["message"]
    assert "50.000000" not in result["message"]
    assert "请反馈分批发货安排" in result["message"]
    assert result["snapshot"]["business_date"] == "2026-10-26"
    assert result["snapshot"]["supplier_id"] == 7
    assert result["warnings"]  # 草稿未发送，以及独立物流数据边界


@pytest.mark.parametrize("status", ["DRAFT", "APPROVING", "APPROVED", "COMPLETED", "CANCELLED"])
def test_inactive_fulfilment_states_cannot_prepare(source, status):
    db, user, order, _ = source
    order.status = status
    with pytest.raises(BusinessValidationError, match="已下单|部分到货"):
        followup.build_followup(db, user, order.id)


def test_fully_received_lines_cannot_be_followed_up(source):
    db, user, order, _ = source
    order.items[0].received_quantity = Decimal("50")
    with pytest.raises(BusinessValidationError, match="待收"):
        followup.build_followup(db, user, order.id)


def test_missing_dates_are_not_invented_and_today_is_not_overdue(source):
    db, user, order, _ = source
    order.expected_arrival_date = None
    order.items[0].planned_arrival_date = None
    result = followup.build_followup(db, user, order.id)
    assert "未维护" in result["message"]
    assert "逾期" not in result["message"]
    order.items[0].planned_arrival_date = date(2026, 10, 26)
    assert "逾期" not in followup.build_followup(db, user, order.id)["message"]


def test_scope_errors_propagate_without_a_draft(source, monkeypatch):
    db, user, order, _ = source
    def denied(*args, **kwargs):
        raise ResourceNotFoundError("采购订单不存在")
    monkeypatch.setattr(order_service, "get_order", denied)
    with pytest.raises(ResourceNotFoundError):
        followup.build_followup(db, user, order.id)


@pytest.mark.parametrize("payload", [
    {"order_id": True}, {"order_id": 0}, {"order_id": "41"},
    {"order_id": 41, "message": "伪造交期"},
    {"order_id": 41, "followup_note": " "},
    {"order_id": 41, "followup_note": "字" * 1001},
])
def test_invalid_or_client_fact_overrides_are_rejected(source, payload):
    db, user, _, _ = source
    with pytest.raises(BusinessValidationError):
        action_handlers.get_handler("deliveries.followup_draft").prepare(db, user, payload)


@pytest.mark.parametrize("change", ["receipt", "eta", "confirmation", "unit", "business_date"])
def test_confirmation_rejects_changed_facts_even_without_order_timestamp_change(source, monkeypatch, change):
    db, user, order, _ = source
    handler = action_handlers.get_handler("deliveries.followup_draft")
    prepared = handler.prepare(db, user, {"order_id": order.id})
    proposal = SimpleNamespace(payload=prepared["payload"], expected_resource_snapshot=prepared["snapshot"])
    if change == "receipt":
        order.items[0].received_quantity += 1
    elif change == "eta":
        order.items[0].planned_arrival_date = date(2026, 10, 28)
    elif change == "confirmation":
        order.supplier_confirmed_at = datetime(2026, 10, 26, 6)
    elif change == "unit":
        db.get = lambda *_: SimpleNamespace(unit_name="毫升")
    else:
        monkeypatch.setattr(followup, "business_today", lambda: date(2026, 10, 27))
    with pytest.raises(BusinessValidationError, match="变化"):
        handler.validate_current(db, user, proposal)


def test_confirm_result_is_only_the_reviewed_draft_and_holds_order_lock(source):
    db, user, order, calls = source
    handler = action_handlers.get_handler("deliveries.followup_draft")
    prepared = handler.prepare(db, user, {"order_id": order.id, "followup_note": "请回复"})
    proposal = SimpleNamespace(payload=prepared["payload"], expected_resource_snapshot=prepared["snapshot"])
    handler.validate_current(db, user, proposal)
    result = handler.execute(db, user, proposal, commit=False)
    assert result["status"] == "DRAFT"
    assert result["sent"] is False
    assert result["message"] == prepared["diff"][0]["after"]
    assert True in calls
    assert order.status == "PARTIAL"
    assert order.items[0].received_quantity == Decimal("12.5")
