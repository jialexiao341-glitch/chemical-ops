"""业务事件到运营建议通知的首期规则。"""

from types import SimpleNamespace

from app.modules.ai import proactive
from app.modules.jobs import service


def _exception(**overrides):
    values = {
        "id": 88,
        "exception_no": "EX20261025000088",
        "exception_type": "LOW_STOCK",
        "description": "产品 无水乙醇 当前可用库存 0 升，低于安全库存阈值 10 升",
        "owner_id": 7,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_low_stock_suggestion_contains_actionable_instruction():
    suggestion = proactive.build_exception_suggestion(_exception())
    assert suggestion["title"] == "运营建议：低库存补货建议"
    assert "EX20261025000088" in suggestion["instruction"]
    assert "补货申请" in suggestion["instruction"]
    assert suggestion["roles"] == ("WAREHOUSE", "PROCUREMENT_MANAGER")


def test_unknown_exception_type_does_not_create_suggestion():
    assert proactive.build_exception_suggestion(_exception(exception_type="OTHER")) is None


def test_publish_sends_suggestion_to_owner_and_roles(monkeypatch):
    calls = []
    monkeypatch.setattr(proactive, "notify_users", lambda _db, **kwargs: calls.append(kwargs))
    from contextlib import nullcontext
    db = SimpleNamespace(scalar=lambda *_: None, begin_nested=lambda: nullcontext(), add=lambda *_: None, flush=lambda: None)
    proactive.publish_exception_suggestion(db, _exception(exception_type="OVERDUE"))

    assert calls[0]["recipient_ids"] == [7]
    assert calls[0]["role_codes"] == ("PROCUREMENT_MANAGER",)
    assert calls[0]["notification_type"] == "OPERATION_SUGGESTION"
    assert calls[0]["related_type"] == "OPERATION_EXCEPTION"
    assert calls[0]["related_id"] == 88


def test_scan_publishes_suggestion_after_new_exception(monkeypatch):
    from datetime import date, timedelta
    from decimal import Decimal

    batch = SimpleNamespace(id=12, batch_no="LOT-12", expiry_date=date.today() + timedelta(days=5))
    db = SimpleNamespace(
        execute=lambda _query: SimpleNamespace(all=lambda: [(batch, "乙醇", Decimal("18.5"))]),
        commit=lambda: None,
    )
    created = _exception(exception_type="INVENTORY_EXPIRY", description="批次临期提醒")
    published = []
    monkeypatch.setattr(service, "create_automatic_exception", lambda *_args, **_kwargs: created)
    monkeypatch.setattr(service, "notify_users", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "_publish_suggestion", lambda _db, exception: published.append(exception))

    result = service.scan_expiring_inventory(db, SimpleNamespace(id=7))

    assert result["created_count"] == 1
    assert published == [created]
