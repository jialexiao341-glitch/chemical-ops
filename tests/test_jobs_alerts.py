"""确定性业务主动提醒测试。"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

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
