"""交期变化影响摘要的确定性规则。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.modules.ai.business_events import (
    AIBusinessEvent,
    build_delivery_change_impact,
    record_delivery_change_event,
)


def _impact(**overrides):
    payload = dict(
        po_no="PO20261110000001",
        order_status="ORDERED",
        previous=date(2026, 11, 12),
        expected=date(2026, 11, 20),
        required_date=date(2026, 11, 18),
        lines=[
            {"line_no": 1, "product_name": "无水乙醇", "remaining_quantity": Decimal("20.000000"), "unit_id": 3},
            {"line_no": 2, "product_name": "甲醇", "remaining_quantity": Decimal("0"), "unit_id": 3},
        ],
        in_transit_deliveries=[],
        today=date(2026, 11, 10),
    )
    payload.update(overrides)
    return build_delivery_change_impact(**payload)


def test_delay_beyond_required_date_is_high_risk():
    impact = _impact()
    assert impact["direction"] == "DELAY"
    assert impact["delta_days"] == 8
    assert impact["risk_level"] == "HIGH"
    assert impact["required_gap_days"] == 2
    assert "延后 8 天" in impact["change_text"]
    assert "晚于申请期望到货" in impact["change_text"]
    assert impact["remaining_line_count"] == 1
    assert impact["remaining_by_unit"] == {"3": "20"}
    assert impact["analysis_mode"] == "DETERMINISTIC"


def test_early_change_keeps_unfulfilled_lines_and_quantity_precision():
    impact = _impact(previous=date(2026, 11, 20), expected=date(2026, 11, 15),
                     required_date=None, lines=[
                         {"line_no": 1, "product_name": "无水乙醇",
                          "remaining_quantity": Decimal("20.125000"), "unit_id": 3},
                     ])
    assert impact["direction"] == "EARLY"
    assert impact["delta_days"] == -5
    assert impact["risk_level"] == "LOW"
    assert impact["remaining_by_unit"] == {"3": "20.125"}


def test_initial_and_unchanged_are_distinguished():
    initial = _impact(previous=None)
    assert initial["direction"] == "INITIAL"
    assert "初次登记" in initial["change_text"]
    unchanged = _impact(previous=date(2026, 11, 12), expected=date(2026, 11, 12), required_date=None)
    assert unchanged["direction"] == "UNCHANGED"
    assert unchanged["risk_level"] == "LOW"


def test_in_transit_dates_are_preserved_as_facts():
    impact = _impact(in_transit_deliveries=[
        {"delivery_no": "DL1", "expected_arrival_date": "2026-11-21", "status": "IN_TRANSIT"},
        {"delivery_no": "DL2", "expected_arrival_date": "2026-11-19", "status": "IN_TRANSIT"},
    ])
    assert impact["in_transit_count"] == 2
    assert impact["in_transit_expected_dates"] == ["2026-11-19", "2026-11-21"]


def _event_db():
    engine = create_engine("sqlite://")
    AIBusinessEvent.__table__.create(engine)
    return Session(engine)


def test_unchanged_date_is_recorded_once_but_skipped():
    db = _event_db()
    order = SimpleNamespace(id=42, po_no="PO1", status="ORDERED")
    update = SimpleNamespace(id=11, previous_date=date(2026, 11, 11),
                             expected_date=date(2026, 11, 11), note=None)
    first = record_delivery_change_event(db, order, update, actor_id=7)
    second = record_delivery_change_event(db, order, update, actor_id=7)
    db.commit()
    assert first.id == second.id
    assert first.triage_status == "SKIPPED"
    assert first.triage["reason"] == "NO_DATE_CHANGE"
    assert db.scalar(select(func.count(AIBusinessEvent.id))) == 1


def test_inactive_order_is_skipped_before_impact_summary():
    db = _event_db()
    order = SimpleNamespace(id=42, po_no="PO1", status="DRAFT")
    update = SimpleNamespace(id=12, previous_date=date(2026, 11, 11),
                             expected_date=date(2026, 11, 20), note=None)
    event = record_delivery_change_event(db, order, update, actor_id=7)
    assert event.triage_status == "SKIPPED"
    assert event.triage["reason"] == "ORDER_NOT_ACTIVE"
    assert event.impact is None


def test_changed_date_links_task_and_notification(monkeypatch):
    from app.modules.ai import business_events as module
    from app.modules.purchase_orders import delivery_tasks

    db = _event_db()
    event = AIBusinessEvent(event_id="f" * 32, event_type="PURCHASE_ORDER_ETA_CHANGED",
                            subject_type="PURCHASE_ORDER", subject_id="42", subject_version=12,
                            dedup_key="po-eta:42:12", source="test", payload={})
    db.add(event)
    db.flush()
    order = SimpleNamespace(id=42, po_no="PO1", status="ORDERED", buyer_id=7)
    update = SimpleNamespace(id=12, previous_date=date(2026, 11, 11),
                             expected_date=date(2026, 11, 20), note="船期延误")
    impact = _impact()
    monkeypatch.setattr(module, "_order_impact", lambda *args, **kwargs: impact)
    monkeypatch.setattr(module, "_notify_delivery_change", lambda *args, **kwargs: [object()])
    monkeypatch.setattr(delivery_tasks, "record_change",
                        lambda *args, **kwargs: SimpleNamespace(id=9))
    result = module.dispatch_delivery_change_event(db, event, order, update)
    assert result.triage_status == "DISPATCHED"
    assert result.task_type == "DELIVERY_CHANGE"
    assert result.task_id == 9
    assert result.triage["verdict"] == "NOTIFY_AND_TASK"
    assert result.triage["model_review_suggested"] is True
    assert result.impact["change_text"] == impact["change_text"]


def test_dispatched_event_replay_does_not_notify_or_create_task_again(monkeypatch):
    """同一事件重投（响应丢失或队列重放）只返回既有分派结果。"""
    from app.modules.ai import business_events as module
    from app.modules.purchase_orders import delivery_tasks

    db = _event_db()
    event = AIBusinessEvent(event_id="e" * 32, event_type="PURCHASE_ORDER_ETA_CHANGED",
                            subject_type="PURCHASE_ORDER", subject_id="42", subject_version=13,
                            dedup_key="po-eta:42:13", source="test", payload={})
    db.add(event)
    db.flush()
    order = SimpleNamespace(id=42, po_no="PO1", status="ORDERED", buyer_id=7)
    update = SimpleNamespace(id=13, previous_date=date(2026, 11, 11),
                             expected_date=date(2026, 11, 20), note=None)
    notices, tasks = [], []
    monkeypatch.setattr(module, "_order_impact", lambda *args, **kwargs: _impact())
    monkeypatch.setattr(module, "_notify_delivery_change",
                        lambda *args, **kwargs: notices.append(1) or [object()])
    monkeypatch.setattr(delivery_tasks, "record_change",
                        lambda *args, **kwargs: tasks.append(1) or SimpleNamespace(id=9))
    first = module.dispatch_delivery_change_event(db, event, order, update)
    replay = module.dispatch_delivery_change_event(db, event, order, update)

    assert replay is first and replay.triage_status == "DISPATCHED"
    assert len(notices) == 1 and len(tasks) == 1