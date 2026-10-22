from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.ai import action_handlers
from app.modules.rfqs import service as rfq_service


def _rfq(status="DRAFT", items=None, suppliers=None):
    return SimpleNamespace(
        id=14, rfq_no="RFQ-014", requester_id=5, status=status,
        quote_deadline=datetime(2026, 11, 1, 12), requested_delivery_date=date(2026, 11, 10),
        delivery_requirements="避光运输", items=items if items is not None else [
            SimpleNamespace(id=31, requested_name="乙醇", quantity=2, unit_id=4,
                            required_delivery_date=None, technical_requirements="纯度 99%")],
        suppliers=suppliers if suppliers is not None else [SimpleNamespace(supplier_id=8)],
    )


def test_rfq_send_handler_prepares_only_existing_visible_draft(monkeypatch):
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args: _rfq())
    handler = action_handlers.get_handler("rfq.send")

    prepared = handler.prepare(SimpleNamespace(), SimpleNamespace(id=5), {"rfq_id": 14})

    assert prepared["resource_id"] == 14
    assert prepared["payload"] == {"rfq_id": 14}
    assert prepared["snapshot"]["status"] == "DRAFT"
    assert prepared["evidence"][0]["rfq_no"] == "RFQ-014"


@pytest.mark.parametrize("rfq", [_rfq(status="SENT"), _rfq(items=[]), _rfq(suppliers=[])])
def test_rfq_send_handler_rejects_non_sendable_draft(monkeypatch, rfq):
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: rfq)
    handler = action_handlers.get_handler("rfq.send")

    with pytest.raises(BusinessValidationError):
        handler.prepare(SimpleNamespace(), SimpleNamespace(id=5), {"rfq_id": 14})


def test_rfq_send_handler_revalidates_snapshot_and_executes_without_committing(monkeypatch):
    from app.modules.rfqs.schema import RFQRead

    rfq = _rfq()
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: rfq)
    handler = action_handlers.get_handler("rfq.send")
    prepared = handler.prepare(SimpleNamespace(), SimpleNamespace(id=5), {"rfq_id": 14})
    proposal = SimpleNamespace(resource_id="14", payload=prepared["payload"],
                               expected_resource_snapshot=prepared["snapshot"])
    handler.validate_current(SimpleNamespace(), SimpleNamespace(id=5), proposal, for_update=True)

    changed = _rfq(status="SENT")
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: changed)
    with pytest.raises(BusinessValidationError):
        handler.validate_current(SimpleNamespace(), SimpleNamespace(id=5), proposal, for_update=True)

    executed = _rfq(status="SENT")
    monkeypatch.setattr(rfq_service, "send_rfq", lambda _db, _user, _id, *, commit: executed)
    monkeypatch.setattr(RFQRead, "model_validate", lambda value: SimpleNamespace(model_dump=lambda **_kwargs: {"id": value.id, "status": value.status}))
    assert handler.execute(SimpleNamespace(), SimpleNamespace(id=5), proposal, commit=False) == {"id": 14, "status": "SENT"}


def test_send_rfq_flushes_without_committing_for_action_transaction(monkeypatch):
    class DB:
        commits = 0
        flushes = 0

        def flush(self):
            self.flushes += 1

        def commit(self):
            self.commits += 1

    db = DB()
    rfq = _rfq()
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: rfq)
    monkeypatch.setattr(rfq_service, "add_audit_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rfq_service.crud, "get_by_id", lambda *_args: rfq)

    result = rfq_service.send_rfq(db, SimpleNamespace(id=5), 14, commit=False)

    assert result.status == "SENT"
    assert db.flushes == 1
    assert db.commits == 0
