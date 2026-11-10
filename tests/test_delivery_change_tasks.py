"""交期变化待办的事务与去重边界。"""

from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_changed_dates_coalesce_and_roll_back():
    from app.modules.purchase_orders.delivery_tasks import DeliveryChangeTask, record_change

    engine = create_engine("sqlite://")
    DeliveryChangeTask.__table__.create(engine)
    with Session(engine) as db:
        order = SimpleNamespace(id=42, buyer_id=7)
        first = SimpleNamespace(id=11, previous_date=date(2026, 11, 11), expected_date=date(2026, 11, 12))
        second = SimpleNamespace(id=12, previous_date=date(2026, 11, 12), expected_date=date(2026, 11, 13))
        record_change(db, order, first, assignee_id=7)
        record_change(db, order, first, assignee_id=7)
        record_change(db, order, second, assignee_id=7)
        db.flush()
        tasks = db.scalars(select(DeliveryChangeTask)).all()
        assert len(tasks) == 1
        assert tasks[0].latest_update_id == 12
        assert tasks[0].assignee_id == 7
        db.rollback()
        assert db.scalars(select(DeliveryChangeTask)).all() == []


def test_unchanged_date_does_not_create_task():
    from app.modules.purchase_orders.delivery_tasks import DeliveryChangeTask, record_change

    engine = create_engine("sqlite://")
    DeliveryChangeTask.__table__.create(engine)
    with Session(engine) as db:
        order = SimpleNamespace(id=42, buyer_id=7)
        update = SimpleNamespace(id=11, previous_date=date(2026, 11, 11), expected_date=date(2026, 11, 11))
        record_change(db, order, update, assignee_id=7)
        assert db.scalars(select(DeliveryChangeTask)).all() == []
