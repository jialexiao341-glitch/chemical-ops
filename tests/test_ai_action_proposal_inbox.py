from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.ai import action_handlers, action_proposals, controller as ai_controller
from app.modules.ai.model import AIAgentActionProposal


@pytest.fixture
def proposal_db(monkeypatch):
    # The production model uses MySQL CURRENT_TIMESTAMP(3) for onupdate;
    # SQLite does not support that expression, so keep timestamp updates DB-neutral here.
    monkeypatch.setattr(AIAgentActionProposal.__table__.c.updated_at, "onupdate", None)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE ai_agent_action_proposals (
                id INTEGER PRIMARY KEY,
                confirmation_id VARCHAR(32) NOT NULL,
                user_id INTEGER NOT NULL,
                action_type VARCHAR(80) NOT NULL,
                resource_type VARCHAR(64),
                resource_id VARCHAR(64),
                preview_version INTEGER NOT NULL,
                payload JSON NOT NULL,
                payload_hash VARCHAR(64) NOT NULL,
                expected_resource_snapshot JSON NOT NULL,
                diff JSON NOT NULL,
                evidence JSON NOT NULL,
                warnings JSON NOT NULL,
                blockers JSON NOT NULL,
                permission_code VARCHAR(100) NOT NULL,
                risk_level VARCHAR(20) NOT NULL,
                idempotency_key VARCHAR(100) NOT NULL,
                expires_at DATETIME NOT NULL,
                status VARCHAR(20) NOT NULL,
                result JSON,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                executed_at DATETIME
            )
            """
        ))
    session = Session(engine, autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _ReadHandler:
    def __init__(self, error=None, permission_code="procurement.requests.write"):
        self.error = error
        self.permission_code = permission_code

    def validate_current(self, *_args, **_kwargs):
        if self.error:
            raise self.error


def _proposal(db, *, owner_id=1, confirmation_id="a" * 32, action_type="purchase_request.update_draft",
              status="PENDING", expires_at=None, request_id=73, evidence=None):
    now = datetime(2026, 1, 1, 12)
    proposal = AIAgentActionProposal(
        confirmation_id=confirmation_id,
        user_id=owner_id,
        action_type=action_type,
        resource_type="purchase_request",
        resource_id=str(request_id),
        preview_version=2,
        payload={"request_id": request_id, "changes": {"purpose": "实验"}},
        payload_hash="payload-hash",
        expected_resource_snapshot={"version": 3, "sensitive": "snapshot-secret"},
        diff=[{"field": "purpose", "before": "旧用途", "after": "实验"}],
        evidence=evidence if evidence is not None else [{"type": "source", "value": "evidence-secret"}],
        warnings=["需要复核"],
        blockers=[],
        permission_code="procurement.requests.write",
        risk_level="LOW",
        idempotency_key=f"key-{confirmation_id}",
        expires_at=expires_at or now + timedelta(minutes=5),
        status=status,
        result=None,
        created_at=now,
        updated_at=now,
        executed_at=None,
    )
    db.add(proposal)
    db.commit()
    return proposal


def _configure_reads(monkeypatch, *, permissions=None, handler=None, request_error=None):
    permissions = permissions or {
        1: ["procurement.requests.read", "procurement.requests.write"],
        2: ["procurement.requests.read", "procurement.requests.write"],
    }
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda _db, user_id: permissions.get(user_id, []))
    monkeypatch.setattr(action_proposals, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    monkeypatch.setattr(action_handlers, "get_handler", lambda action_type: handler or _ReadHandler(
        permission_code="procurement.rfqs.award" if action_type == "rfq.select_quote" else
        "procurement.rfqs.write" if action_type in {"rfq.send", "rfq.create_draft"} else
        "procurement.requests.write"))

    from app.modules.purchase_requests import service as request_service

    def get_request(_db, _user, request_id):
        if request_error:
            raise request_error
        return SimpleNamespace(id=request_id, request_no=f"PR-{request_id:04d}")

    monkeypatch.setattr(request_service, "get_request", get_request)


def test_inbox_list_only_returns_owned_supported_proposals(proposal_db, monkeypatch):
    _configure_reads(monkeypatch)
    _proposal(proposal_db, owner_id=1, confirmation_id="a" * 32)
    _proposal(proposal_db, owner_id=2, confirmation_id="b" * 32)
    _proposal(proposal_db, owner_id=1, confirmation_id="c" * 32, action_type="other.action")

    result = ai_controller.action_proposal_list(
        db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"), page=1, page_size=20, inbox_only=True)

    assert result.total == 1
    assert [item.confirmation_id for item in result.items] == ["a" * 32]
    assert result.items[0].business_reference == "PR-0073"


def test_detail_rejects_another_users_confirmation_id(proposal_db, monkeypatch):
    _configure_reads(monkeypatch)
    _proposal(proposal_db, owner_id=1)

    with pytest.raises(ResourceNotFoundError):
        ai_controller.action_proposal_read(
            "a" * 32, db=proposal_db, user=SimpleNamespace(id=2, status="ACTIVE"))


def test_detail_keeps_proposal_readable_but_disables_it_after_write_permission_revoked(proposal_db, monkeypatch):
    _configure_reads(monkeypatch, permissions={1: ["procurement.requests.read"]})
    _proposal(proposal_db)

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.status == "PENDING"
    assert result.availability == "PERMISSION_REVOKED"
    assert result.requires_user_confirmation is False
    assert result.business_reference == "PR-0073"


def test_inbox_read_persists_expired_state_and_disables_confirmation(proposal_db, monkeypatch):
    _configure_reads(monkeypatch)
    _proposal(proposal_db, expires_at=datetime(2026, 1, 1, 11, 59))

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.status == "EXPIRED"
    assert result.unavailable_reason == "提案已过期，请重新生成"
    assert result.requires_user_confirmation is False
    assert proposal_db.get(AIAgentActionProposal, 1).status == "EXPIRED"


def test_inbox_read_marks_changed_resource_invalidated(proposal_db, monkeypatch):
    _configure_reads(monkeypatch, handler=_ReadHandler(BusinessValidationError("来源版本已变化")))
    _proposal(proposal_db)

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.status == "INVALIDATED"
    assert result.availability == "AVAILABLE"
    assert result.requires_user_confirmation is False
    assert proposal_db.get(AIAgentActionProposal, 1).status == "INVALIDATED"


def test_unreadable_resource_hides_reference_diff_evidence_and_execution_data(proposal_db, monkeypatch):
    _configure_reads(monkeypatch, permissions={1: ["procurement.requests.write"]})
    _proposal(proposal_db)

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))
    response = result.model_dump()

    assert result.availability == "RESOURCE_UNAVAILABLE"
    assert result.business_reference is None
    assert result.source_route is None
    assert result.diff == []
    assert result.evidence == []
    assert not {"payload", "expected_resource_snapshot", "permission_code", "idempotency_key"} & response.keys()


def test_missing_source_resource_hides_its_saved_evidence_and_marks_unavailable(proposal_db, monkeypatch):
    _configure_reads(monkeypatch, request_error=ResourceNotFoundError("not found"))
    _proposal(proposal_db)

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.availability == "RESOURCE_UNAVAILABLE"
    assert result.business_reference is None
    assert result.diff == []
    assert result.evidence == []


def test_rfq_send_inbox_shows_rfq_reference_and_deep_link(proposal_db, monkeypatch):
    permissions = {1: ["procurement.rfqs.read", "procurement.rfqs.write"]}
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda _db, user_id: permissions.get(user_id, []))
    monkeypatch.setattr(action_proposals, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: _ReadHandler(permission_code="procurement.rfqs.write"))
    from app.modules.rfqs import service as rfq_service
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args: SimpleNamespace(id=73, rfq_no="RFQ-0073"))
    proposal = _proposal(proposal_db, action_type="rfq.send")
    proposal.resource_type = "RFQ"
    proposal.permission_code = "procurement.rfqs.write"
    proposal.payload = {"rfq_id": 73}
    proposal_db.commit()

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.business_reference == "RFQ-0073"
    assert result.source_route == "/procurement/rfqs?ai_record_id=73"
    assert result.availability == "AVAILABLE"


def test_rfq_send_inbox_hides_reference_and_evidence_without_rfq_read_permission(proposal_db, monkeypatch):
    permissions = {1: ["procurement.rfqs.write"]}
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda _db, user_id: permissions.get(user_id, []))
    monkeypatch.setattr(action_proposals, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: _ReadHandler(permission_code="procurement.rfqs.write"))
    proposal = _proposal(proposal_db, action_type="rfq.send")
    proposal.permission_code = "procurement.rfqs.write"
    proposal.payload = {"rfq_id": 73}
    proposal_db.commit()

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.availability == "RESOURCE_UNAVAILABLE"
    assert result.business_reference is None
    assert result.source_route is None
    assert result.diff == []
    assert result.evidence == []


def test_rfq_select_quote_inbox_shows_rfq_reference_and_selection_reason(proposal_db, monkeypatch):
    permissions = {1: ["procurement.rfqs.read", "procurement.rfqs.award"]}
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda _db, user_id: permissions.get(user_id, []))
    monkeypatch.setattr(action_proposals, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: _ReadHandler(permission_code="procurement.rfqs.award"))
    from app.modules.rfqs import service as rfq_service
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: SimpleNamespace(id=73, rfq_no="RFQ-0073"))
    proposal = _proposal(proposal_db, action_type="rfq.select_quote")
    proposal.resource_type = "RFQ"
    proposal.permission_code = "procurement.rfqs.award"
    proposal.payload = {"rfq_id": 73, "comparison_id": 2, "quote_id": 3, "selection_reason": "综合成本合适"}
    proposal_db.commit()

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.business_reference == "RFQ-0073"
    assert result.source_route == "/procurement/rfqs?ai_record_id=73"
    assert result.revision_values == {"selection_reason": "综合成本合适"}


def test_rfq_select_quote_list_is_scoped_to_owner(proposal_db, monkeypatch):
    permissions = {1: ["procurement.rfqs.read", "procurement.rfqs.award"]}
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda _db, user_id: permissions.get(user_id, []))
    monkeypatch.setattr(action_proposals, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: _ReadHandler(permission_code="procurement.rfqs.award"))
    from app.modules.rfqs import service as rfq_service
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: SimpleNamespace(id=73, rfq_no="RFQ-0073"))
    own = _proposal(proposal_db, owner_id=1, action_type="rfq.select_quote")
    own.resource_type = "RFQ"
    own.permission_code = "procurement.rfqs.award"
    own.payload = {"rfq_id": 73, "comparison_id": 2, "quote_id": 3, "selection_reason": "综合成本合适"}
    _proposal(proposal_db, owner_id=2, confirmation_id="b" * 32, action_type="rfq.select_quote")
    proposal_db.commit()

    result = ai_controller.action_proposal_list(
        db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"), page=1, page_size=20, inbox_only=True)

    assert result.total == 1
    assert [item.confirmation_id for item in result.items] == [own.confirmation_id]


def test_rfq_select_quote_inbox_disables_confirmation_after_award_permission_revoked(proposal_db, monkeypatch):
    permissions = {1: ["procurement.rfqs.read"]}
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda _db, user_id: permissions.get(user_id, []))
    monkeypatch.setattr(action_proposals, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: _ReadHandler(permission_code="procurement.rfqs.award"))
    from app.modules.rfqs import service as rfq_service
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: SimpleNamespace(id=73, rfq_no="RFQ-0073"))
    proposal = _proposal(proposal_db, action_type="rfq.select_quote")
    proposal.permission_code = "procurement.rfqs.award"
    proposal.payload = {"rfq_id": 73, "comparison_id": 2, "quote_id": 3, "selection_reason": "综合成本合适"}
    proposal_db.commit()

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.availability == "PERMISSION_REVOKED"
    assert result.requires_user_confirmation is False
    assert result.business_reference == "RFQ-0073"


def test_rfq_select_quote_inbox_hides_reason_without_rfq_read_permission(proposal_db, monkeypatch):
    permissions = {1: ["procurement.rfqs.award"]}
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda _db, user_id: permissions.get(user_id, []))
    monkeypatch.setattr(action_proposals, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: _ReadHandler(permission_code="procurement.rfqs.award"))
    proposal = _proposal(proposal_db, action_type="rfq.select_quote")
    proposal.permission_code = "procurement.rfqs.award"
    proposal.payload = {"rfq_id": 73, "comparison_id": 2, "quote_id": 3, "selection_reason": "受限的商务理由"}
    proposal_db.commit()

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.availability == "RESOURCE_UNAVAILABLE"
    assert result.business_reference is None
    assert result.diff == []
    assert result.evidence == []
    assert result.revision_values == {}


def test_purchase_order_proposal_inbox_shows_rfq_reference_and_allowed_revision_fields(proposal_db, monkeypatch):
    permissions = {1: ["procurement.orders.write", "procurement.rfqs.read"]}
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda _db, user_id: permissions.get(user_id, []))
    monkeypatch.setattr(action_proposals, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: _ReadHandler(permission_code="procurement.orders.write"))
    from app.modules.rfqs import service as rfq_service
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: SimpleNamespace(id=73, rfq_no="RFQ-0073"))
    proposal = _proposal(proposal_db, action_type="purchase_order.create_draft")
    proposal.resource_type = "RFQ"
    proposal.resource_id = "73"
    proposal.permission_code = "procurement.orders.write"
    proposal.payload = {"comparison_id": 2, "quote_id": 3, "delivery_address": "仓库 A",
                       "expected_arrival_date": "2026-01-10", "note": "留样"}
    proposal_db.commit()

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.business_reference == "RFQ-0073"
    assert result.source_route == "/procurement/rfqs?ai_record_id=73"
    assert result.revision_values == {"delivery_address": "仓库 A", "expected_arrival_date": "2026-01-10", "note": "留样"}


def test_purchase_order_proposal_inbox_hides_quote_evidence_without_rfq_read_permission(proposal_db, monkeypatch):
    permissions = {1: ["procurement.orders.write"]}
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda _db, user_id: permissions.get(user_id, []))
    monkeypatch.setattr(action_proposals, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: _ReadHandler(permission_code="procurement.orders.write"))
    proposal = _proposal(proposal_db, action_type="purchase_order.create_draft")
    proposal.resource_type = "RFQ"
    proposal.resource_id = "73"
    proposal.permission_code = "procurement.orders.write"
    proposal.payload = {"comparison_id": 2, "quote_id": 3, "delivery_address": "机密地址"}
    proposal.diff = [{"field": "supplier", "after": "secret supplier"}]
    proposal.evidence = [{"type": "purchase_order_terms_check", "items": [{"payment_terms": "secret terms"}]}]
    proposal_db.commit()

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.availability == "PERMISSION_REVOKED"
    assert result.business_reference is None
    assert result.source_route is None
    assert result.diff == []
    assert result.evidence == []
    assert result.revision_values == {}


def test_purchase_order_proposal_revision_only_changes_allowed_order_fields(proposal_db, monkeypatch):
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    proposal = _proposal(proposal_db, action_type="purchase_order.create_draft")
    proposal.permission_code = "procurement.orders.write"
    proposal.resource_type = "RFQ"
    proposal.resource_id = "73"
    proposal.payload = {"comparison_id": 2, "quote_id": 3, "delivery_address": None,
                       "expected_arrival_date": None, "note": None}
    proposal_db.commit()
    seen = []

    class _PrepareHandler(_ReadHandler):
        def prepare(self, _db, _user, payload):
            seen.append(payload)
            return {"payload": payload, "snapshot": {"updated": True}, "resource_id": 73,
                    "diff": [], "evidence": [], "warnings": [], "blockers": []}

    monkeypatch.setattr(action_proposals, "_owned_proposal", lambda *_args, **_kwargs: proposal)
    monkeypatch.setattr(action_proposals, "_authorize", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: _PrepareHandler())

    result = action_proposals.revise_action(
        proposal_db, SimpleNamespace(id=1), proposal.confirmation_id, proposal.preview_version,
        {"delivery_address": "新地址"},
    )

    assert seen[0] == {**proposal.payload, "delivery_address": "新地址"}
    assert proposal.preview_version == 3
    assert result.preview_version == 3


def _draft_evidence():
    return [
        {"type": "tool", "label": "授权库存", "tool": "inventory.query_available",
         "arguments": {"product_id": 9}, "fingerprint": "a" * 64, "totals": [], "sources": []},
        {"type": "tool", "label": "产品目录", "tool": "catalog.search_products",
         "arguments": {"keyword": "乙醇"}, "fingerprint": "b" * 64, "rows": [], "sources": []},
    ]


def _exception_task_proposal(proposal_db):
    proposal = _proposal(proposal_db, action_type="exceptions.create_task",
                         evidence=[{"type": "operation_exception", "id": 5,
                                    "exception_no": "EX20261025000001", "status": "OPEN"}])
    proposal.permission_code = "operations.exceptions.write"
    proposal.resource_type = "OPERATION_EXCEPTION"
    proposal.resource_id = "5"
    proposal.payload = {"exception_id": 5, "title": "联系供应商补交 COA", "priority": "HIGH"}
    proposal_db.commit()
    return proposal


def test_exception_task_inbox_shows_exception_reference_and_evidence(proposal_db, monkeypatch):
    from app.modules.operation_exceptions import service as exception_service

    monkeypatch.setattr(exception_service, "get_exception_for_task_creation",
                        lambda *_args, **_kwargs: SimpleNamespace(id=5, exception_no="EX20261025000001"))
    _configure_reads(monkeypatch, permissions={1: [
        "operations.exceptions.read", "operations.exceptions.write",
    ]}, handler=_ReadHandler(permission_code="operations.exceptions.write"))
    _exception_task_proposal(proposal_db)

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.business_reference == "EX20261025000001"
    assert result.source_route == "/operations/exceptions"
    assert result.availability == "AVAILABLE"
    assert result.requires_user_confirmation is True
    assert result.evidence[0]["exception_no"] == "EX20261025000001"


def test_exception_task_inbox_hides_reference_without_exception_read_permission(proposal_db, monkeypatch):
    _configure_reads(monkeypatch, permissions={1: ["operations.exceptions.write"]},
                     handler=_ReadHandler(permission_code="operations.exceptions.write"))
    _exception_task_proposal(proposal_db)

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.availability == "RESOURCE_UNAVAILABLE"
    assert result.business_reference is None
    assert result.source_route is None
    assert result.evidence == []
    assert result.requires_user_confirmation is False


def test_create_draft_revision_clears_evidence_only_when_product_changes(proposal_db, monkeypatch):
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1, 12))
    proposal = _proposal(proposal_db, action_type="purchase_request.create_draft", evidence=_draft_evidence())
    proposal.payload = {"purpose": "实验", "items": [{"product_id": 9, "quantity": "2", "unit_id": 3}]}
    proposal_db.commit()

    class _PrepareHandler(_ReadHandler):
        def prepare(self, _db, _user, payload):
            return {"payload": payload, "snapshot": {"updated": True}, "resource_id": None,
                    "diff": [], "evidence": [], "warnings": [], "blockers": []}

    monkeypatch.setattr(action_proposals, "_owned_proposal", lambda *_args, **_kwargs: proposal)
    monkeypatch.setattr(action_proposals, "_authorize", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(action_handlers, "get_handler", lambda _type: _PrepareHandler())

    same = {"purpose": "实验", "items": [{"product_id": 9, "quantity": "3", "unit_id": 3}]}
    action_proposals.revise_action(
        proposal_db, SimpleNamespace(id=1), proposal.confirmation_id, proposal.preview_version, same)
    assert len(proposal.evidence) == 2

    changed = {"purpose": "实验", "items": [{"product_id": 10, "quantity": "3", "unit_id": 3}]}
    action_proposals.revise_action(
        proposal_db, SimpleNamespace(id=1), proposal.confirmation_id, proposal.preview_version, changed)
    assert proposal.evidence == []
    assert proposal.preview_version == 4


def test_create_draft_inbox_reads_without_resource_and_hides_unreadable_sources(proposal_db, monkeypatch):
    _configure_reads(monkeypatch, permissions={1: ["procurement.requests.write"]})
    _proposal(proposal_db, action_type="purchase_request.create_draft", evidence=_draft_evidence())

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert result.business_reference == "待创建采购申请"
    assert result.evidence == []
    assert result.availability == "PERMISSION_REVOKED"
    assert result.unavailable_reason == "当前账号已无查看来源库存或报价所需的权限"
    assert result.requires_user_confirmation is False


def test_create_draft_inbox_shows_sources_when_current_permissions_allow(proposal_db, monkeypatch):
    _configure_reads(monkeypatch, permissions={1: [
        "procurement.requests.write", "warehouse.inventory.read", "master.products.read",
    ]})
    _proposal(proposal_db, action_type="purchase_request.create_draft", evidence=_draft_evidence())

    result = ai_controller.action_proposal_read(
        "a" * 32, db=proposal_db, user=SimpleNamespace(id=1, status="ACTIVE"))

    assert [entry["tool"] for entry in result.evidence] == [
        "inventory.query_available", "catalog.search_products"]
    assert result.availability == "AVAILABLE"
    assert result.requires_user_confirmation is True
