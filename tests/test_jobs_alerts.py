"""确定性业务主动提醒测试。"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.core.config import Settings
from app.modules.jobs import service
from app.modules.operation_exceptions.schema import OperationExceptionCreate


def test_inventory_expiry_exception_schema_accepts_batch_source() -> None:
    exception = OperationExceptionCreate(
        exception_type="INVENTORY_EXPIRY",
        source_type="INVENTORY_BATCH",
        source_id=12,
        severity="HIGH",
        description="批次临期提醒",
    )

    assert exception.source_type == "INVENTORY_BATCH"


def test_scheduled_alerts_require_explicit_rollout_enablement() -> None:
    assert Settings().business_alerts_scheduler_enabled is False
    assert Settings().quality_pending_alert_hours == 24


def test_expiring_inventory_creates_one_linked_exception_and_notification(monkeypatch) -> None:
    batch = SimpleNamespace(id=12, batch_no="LOT-12", expiry_date=date.today() + timedelta(days=5))
    db = SimpleNamespace(
        execute=lambda _query: SimpleNamespace(all=lambda: [(batch, "乙醇", Decimal("18.5"))]),
        commit=lambda: None,
    )
    created = []
    notifications = []

    def create_exception(_db, actor, **kwargs):
        created.append((actor, kwargs))
        return SimpleNamespace(id=88)

    monkeypatch.setattr(service, "create_automatic_exception", create_exception)
    monkeypatch.setattr(service, "notify_users", lambda _db, **kwargs: notifications.append(kwargs))

    result = service.scan_expiring_inventory(db, SimpleNamespace(id=7))

    assert result == {"scanned_count": 1, "created_count": 1}
    actor, exception = created[0]
    assert actor.id == 7
    assert exception["exception_type"] == "INVENTORY_EXPIRY"
    assert exception["source_type"] == "INVENTORY_BATCH"
    assert exception["source_id"] == batch.id
    assert exception["severity"] == "HIGH"
    assert "18.5" in exception["description"]
    assert notifications[0]["related_id"] == 88
    assert notifications[0]["role_codes"] == ["WAREHOUSE", "PROCUREMENT_MANAGER"]


def test_pending_quality_scan_creates_a_deduplicated_alert(monkeypatch) -> None:
    now = datetime.now()
    acceptance = SimpleNamespace(
        id=31,
        acceptance_no="QA-31",
        delivery_id=22,
        inspector_id=7,
        created_at=now - timedelta(hours=30),
    )
    db = SimpleNamespace(
        execute=lambda _query: SimpleNamespace(all=lambda: [(acceptance, "DL-22", 14, "PO-14")]),
        commit=lambda: None,
    )
    created = []
    notifications = []

    def create_exception(_db, actor, **kwargs):
        created.append((actor, kwargs))
        return SimpleNamespace(id=92)

    monkeypatch.setattr(service, "create_automatic_exception", create_exception)
    monkeypatch.setattr(service, "notify_users", lambda _db, **kwargs: notifications.append(kwargs))

    result = service.scan_pending_quality_acceptances(db, SimpleNamespace(id=4), threshold_hours=24)

    assert result == {"scanned_count": 1, "created_count": 1}
    actor, exception = created[0]
    assert actor.id == 4
    assert exception["exception_type"] == "QUALITY_PENDING"
    assert exception["source_type"] == "QUALITY_ACCEPTANCE"
    assert exception["source_id"] == acceptance.id
    assert exception["po_id"] == 14
    assert "30 小时" in exception["description"]
    assert notifications[0]["recipient_ids"] == [7]
    assert notifications[0]["role_codes"] == ["QUALITY", "PROCUREMENT_MANAGER"]
