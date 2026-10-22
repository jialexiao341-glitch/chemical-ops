from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.ai import action_handlers
from app.modules.rfqs import crud as rfq_crud
from app.modules.rfqs import service as rfq_service


def _data(*, status="RESPONDING", comparison_status="DRAFT", quote_status="SUBMITTED", include_quote=True):
    rfq = SimpleNamespace(
        id=14, rfq_no="RFQ-014", requester_id=5, status=status,
        quote_deadline=datetime(2026, 11, 1, 12), requested_delivery_date=date(2026, 11, 10),
        delivery_requirements="避光运输",
        items=[SimpleNamespace(id=31, requested_name="乙醇", quantity=Decimal("2"), unit_id=4,
                               required_delivery_date=None, technical_requirements="纯度99%")],
        suppliers=[SimpleNamespace(supplier_id=8)],
    )
    quote_item = SimpleNamespace(id=41, rfq_item_id=31, unit_price=Decimal("12.5"),
                                 quoted_quantity=Decimal("2"), unit_id=4, tax_rate=Decimal("13"),
                                 moq_quantity=None, moq_unit_id=None, lead_days=10, payment_terms="月结30天")
    quote = SimpleNamespace(id=51, rfq_id=14, quote_no="Q-051", supplier_id=8,
                            quote_version=1, currency_code="CNY", status=quote_status,
                            valid_until=date(2026, 12, 1), items=[quote_item])
    comparison_item = SimpleNamespace(id=61, quote_id=51, rfq_item_id=31, supplier_id=8,
                                      quoted_unit_price=Decimal("12.5"), total_amount=Decimal("25"),
                                      moq_quantity=None, lead_days=10, payment_terms="月结30天",
                                      rank_no=1, selection_flag=1)
    comparison = SimpleNamespace(id=71, rfq_id=14, comparison_no="QC-071", status=comparison_status,
                                 selected_quote_id=None, conclusion="综合报价比较", items=[comparison_item])
    rfq.quotes = [quote] if include_quote else []
    return rfq, comparison, quote


def _handler(monkeypatch, rfq, comparison, quote):
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: rfq)
    monkeypatch.setattr(rfq_crud, "get_comparison", lambda *_args, **_kwargs: comparison)
    monkeypatch.setattr(rfq_crud, "get_quote", lambda *_args, **_kwargs: quote)
    return action_handlers.get_handler("rfq.select_quote")


def test_select_quote_handler_prepares_selection_reason_and_evidence(monkeypatch):
    rfq, comparison, quote = _data()
    handler = _handler(monkeypatch, rfq, comparison, quote)

    prepared = handler.prepare(SimpleNamespace(), SimpleNamespace(id=5), {
        "rfq_id": 14, "comparison_id": 71, "quote_id": 51, "selection_reason": "综合成本合适",
    })

    assert prepared["resource_id"] == 14
    assert prepared["payload"]["selection_reason"] == "综合成本合适"
    assert prepared["snapshot"]["comparison"]["id"] == 71
    assert prepared["snapshot"]["quote"]["id"] == 51
    assert prepared["evidence"][0]["comparison_no"] == "QC-071"
    assert prepared["evidence"][1]["quote_no"] == "Q-051"


@pytest.mark.parametrize("case", ["rfq_status", "comparison_status", "quote_status", "quote_not_in_comparison"])
def test_select_quote_handler_rejects_stale_or_unselectable_resources(monkeypatch, case):
    options = {
        "rfq_status": {"status": "SENT"},
        "comparison_status": {"comparison_status": "CONFIRMED"},
        "quote_status": {"quote_status": "REJECTED"},
        "quote_not_in_comparison": {},
    }
    rfq, comparison, quote = _data(**options[case])
    if case == "quote_not_in_comparison":
        comparison.items[0].quote_id = 999
    handler = _handler(monkeypatch, rfq, comparison, quote)

    with pytest.raises(BusinessValidationError):
        handler.prepare(SimpleNamespace(), SimpleNamespace(id=5), {
            "rfq_id": 14, "comparison_id": 71, "quote_id": 51, "selection_reason": "综合成本合适",
        })


def test_select_quote_handler_revalidates_snapshot_and_uses_transactional_domain_service(monkeypatch):
    from app.modules.rfqs.schema import RFQRead

    rfq, comparison, quote = _data()
    handler = _handler(monkeypatch, rfq, comparison, quote)
    payload = {"rfq_id": 14, "comparison_id": 71, "quote_id": 51, "selection_reason": "综合成本合适"}
    prepared = handler.prepare(SimpleNamespace(), SimpleNamespace(id=5), payload)
    proposal = SimpleNamespace(resource_id="14", payload=prepared["payload"],
                               expected_resource_snapshot=prepared["snapshot"])
    handler.validate_current(SimpleNamespace(), SimpleNamespace(id=5), proposal, for_update=True)

    comparison.status = "CANCELLED"
    with pytest.raises(BusinessValidationError):
        handler.validate_current(SimpleNamespace(), SimpleNamespace(id=5), proposal, for_update=True)
    comparison.status = "DRAFT"
    quote.items[0].unit_price = Decimal("13.5")
    with pytest.raises(BusinessValidationError):
        handler.validate_current(SimpleNamespace(), SimpleNamespace(id=5), proposal, for_update=True)
    quote.items[0].unit_price = Decimal("12.5")

    executed = SimpleNamespace(id=14, status="CLOSED")
    monkeypatch.setattr(rfq_service, "select_quote", lambda _db, _user, _id, data, *, commit: executed)
    monkeypatch.setattr(RFQRead, "model_validate", lambda value: SimpleNamespace(model_dump=lambda **_kwargs: {"id": value.id, "status": value.status}))

    assert handler.execute(SimpleNamespace(), SimpleNamespace(id=5), proposal, commit=False) == {"id": 14, "status": "CLOSED"}


def test_select_quote_domain_service_can_flush_without_committing(monkeypatch):
    class DB:
        commits = 0
        flushes = 0
        def scalar(self, _query):
            return self.scalar_results.pop(0)

        def flush(self):
            self.flushes += 1

        def commit(self):
            self.commits += 1

    rfq, comparison, quote = _data()
    rfq.quotes = [quote, SimpleNamespace(id=52, status="SUBMITTED")]
    rfq.status = "RESPONDING"
    db = DB()
    db.scalar_results = [object(), comparison]
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: rfq)
    monkeypatch.setattr(rfq_crud, "get_quote", lambda *_args, **_kwargs: quote)
    monkeypatch.setattr(rfq_service, "add_audit_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rfq_crud, "get_by_id", lambda *_args, **_kwargs: rfq)

    result = rfq_service.select_quote(
        db, SimpleNamespace(id=5), 14,
        rfq_service.QuoteSelection(comparison_id=71, quote_id=51, selection_reason="综合成本合适"),
        commit=False,
    )

    assert result.status == "CLOSED"
    assert comparison.status == "CONFIRMED"
    assert quote.status == "SELECTED"
    assert db.flushes == 1
    assert db.commits == 0


def test_select_quote_proposal_revision_preserves_resource_ids_and_updates_reason(monkeypatch):
    from datetime import timedelta

    from app.modules.ai import action_proposals

    rfq, comparison, quote = _data()
    handler = _handler(monkeypatch, rfq, comparison, quote)
    proposal = SimpleNamespace(
        confirmation_id="c" * 32, user_id=5, action_type="rfq.select_quote", permission_code="procurement.rfqs.award",
        status="PENDING", expires_at=datetime.now() + timedelta(minutes=5), preview_version=1,
        resource_type="RFQ", resource_id="14", risk_level="HIGH", blockers=[], warnings=[], diff=[], evidence=[],
        expected_resource_snapshot={}, payload={"rfq_id": 14, "comparison_id": 71, "quote_id": 51,
                                    "selection_reason": "原理由"},
    )
    monkeypatch.setattr(action_proposals, "_owned_proposal", lambda *_args, **_kwargs: proposal)
    monkeypatch.setattr(action_proposals, "_authorize", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: handler)

    preview = action_proposals.revise_action(
        SimpleNamespace(commit=lambda: None), SimpleNamespace(id=5), proposal.confirmation_id, 1,
        {"selection_reason": "修订后的理由"},
    )

    assert proposal.payload == {"rfq_id": 14, "comparison_id": 71, "quote_id": 51,
                                "selection_reason": "修订后的理由"}
    assert proposal.preview_version == 2
    assert preview.preview_version == 2
    assert preview.diff[-1] == {"field": "selection_reason", "before": "原理由", "after": "修订后的理由"}


def test_select_quote_handler_rejects_rfq_outside_requesters_visible_scope(monkeypatch):
    from app.core.errors import ResourceNotFoundError

    rfq, comparison, quote = _data()
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        ResourceNotFoundError("询价单不存在或当前用户不可见")))
    monkeypatch.setattr(rfq_crud, "get_comparison", lambda *_args, **_kwargs: comparison)
    monkeypatch.setattr(rfq_crud, "get_quote", lambda *_args, **_kwargs: quote)
    handler = action_handlers.get_handler("rfq.select_quote")

    with pytest.raises(ResourceNotFoundError, match="不可见"):
        handler.prepare(SimpleNamespace(), SimpleNamespace(id=99), {
            "rfq_id": 14, "comparison_id": 71, "quote_id": 51, "selection_reason": "综合成本合适",
        })
