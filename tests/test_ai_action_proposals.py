from datetime import datetime

import pytest
from pydantic import ValidationError


def test_action_proposal_confirm_requires_literal_true_and_current_version():
    from app.modules.ai.schema import AIActionProposalConfirm

    confirmation_id = "a" * 32
    with pytest.raises(ValidationError):
        AIActionProposalConfirm(confirmation_id=confirmation_id, preview_version=1, confirm=False)
    with pytest.raises(ValidationError):
        AIActionProposalConfirm(confirmation_id=confirmation_id, preview_version="1", confirm=True)
    data = AIActionProposalConfirm(confirmation_id=confirmation_id, preview_version=2, confirm=True)
    assert data.preview_version == 2


def test_action_proposal_schemas_forbid_extra_fields():
    from app.modules.ai.schema import AIActionProposalCreate, AIActionProposalRevise

    with pytest.raises(ValidationError):
        AIActionProposalCreate(action_type="purchase_request.create_draft", payload={}, arbitrary_service="x")
    with pytest.raises(ValidationError):
        AIActionProposalRevise(confirmation_id="a" * 32, preview_version=1, payload={}, execute=True)


def test_action_proposal_model_declares_unique_confirmation_and_idempotency_keys():
    from app.modules.ai.model import AIAgentActionProposal

    constraints = {constraint.name: tuple(column.name for column in constraint.columns)
                   for constraint in AIAgentActionProposal.__table__.constraints
                   if constraint.__class__.__name__ == "UniqueConstraint"}
    assert constraints["uq_ai_action_proposal_confirmation"] == ("confirmation_id",)
    assert constraints["uq_ai_action_proposal_user_idempotency"] == ("user_id", "idempotency_key")
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.errors import AuthorizationError, BusinessValidationError, DuplicateResourceError
from app.modules.ai import action_handlers, action_proposals
from app.modules.ai.schema import AIActionProposalConfirm


class _DB:
    def __init__(self):
        self.rows = []
        self.commits = 0
        self.writes = 0

    def add(self, row):
        self.rows.append(row)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1

    def scalar(self, _query):
        return self.rows[-1] if self.rows else None


class _Handler:
    permission_code = "procurement.requests.write"
    resource_type = None

    def prepare(self, _db, _user, payload):
        return {"payload": payload, "snapshot": {}, "diff": [{"field": "purpose", "after": payload["purpose"]}],
                "evidence": [], "warnings": [], "blockers": [], "resource_id": None, "risk_level": "LOW"}

    def validate_current(self, *_args):
        return None

    def execute(self, db, _user, proposal, *, commit=False):
        assert commit is False
        db.writes += 1
        return {"request_no": "PR-001", "purpose": proposal.payload["purpose"]}


def _register(monkeypatch):
    monkeypatch.setitem(action_handlers._HANDLERS, "test.create", _Handler())
    monkeypatch.setattr(action_proposals, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda *_args: ["procurement.requests.write"])
    monkeypatch.setattr(action_proposals, "_now", lambda: datetime(2026, 1, 1))


def test_action_proposal_preview_does_not_write_business_data(monkeypatch):
    _register(monkeypatch)
    db = _DB()
    preview = action_proposals.propose_action(db, SimpleNamespace(id=5, status="ACTIVE"), "test.create",
                                             {"purpose": "实验"}, idempotency_key="req-1")
    assert preview.status == "PENDING"
    assert db.writes == 0
    assert db.commits == 1


def test_action_proposal_confirm_executes_once_and_replay_returns_saved_result(monkeypatch):
    _register(monkeypatch)
    db = _DB()
    user = SimpleNamespace(id=5, status="ACTIVE")
    preview = action_proposals.propose_action(db, user, "test.create", {"purpose": "实验"}, idempotency_key="req-2")
    request = AIActionProposalConfirm(confirmation_id=preview.confirmation_id, preview_version=1, confirm=True)
    first = action_proposals.confirm_action(db, user, request)
    second = action_proposals.confirm_action(db, user, request)
    assert first == second == {"request_no": "PR-001", "purpose": "实验"}
    assert db.writes == 1


def test_action_proposal_rejects_expired_confirmation(monkeypatch):
    _register(monkeypatch)
    db = _DB()
    user = SimpleNamespace(id=5, status="ACTIVE")
    preview = action_proposals.propose_action(db, user, "test.create", {"purpose": "实验"}, idempotency_key="req-3")
    db.rows[0].expires_at = datetime(2025, 12, 31)
    request = AIActionProposalConfirm(confirmation_id=preview.confirmation_id, preview_version=1, confirm=True)
    with pytest.raises(DuplicateResourceError, match="过期"):
        action_proposals.confirm_action(db, user, request)
    assert db.writes == 0


def test_action_proposal_rejects_tampered_payload_before_execution(monkeypatch):
    _register(monkeypatch)
    db = _DB()
    user = SimpleNamespace(id=5, status="ACTIVE")
    preview = action_proposals.propose_action(db, user, "test.create", {"purpose": "实验"}, idempotency_key="req-4")
    db.rows[0].payload["purpose"] = "篡改"
    request = AIActionProposalConfirm(confirmation_id=preview.confirmation_id, preview_version=1, confirm=True)
    with pytest.raises(BusinessValidationError, match="校验"):
        action_proposals.confirm_action(db, user, request)
    assert db.writes == 0


def test_action_proposal_rechecks_permission_at_confirmation(monkeypatch):
    _register(monkeypatch)
    db = _DB()
    user = SimpleNamespace(id=5, status="ACTIVE")
    preview = action_proposals.propose_action(db, user, "test.create", {"purpose": "实验"}, idempotency_key="req-5")
    monkeypatch.setattr(action_proposals, "get_user_permission_codes", lambda *_args: [])
    request = AIActionProposalConfirm(confirmation_id=preview.confirmation_id, preview_version=1, confirm=True)
    with pytest.raises(AuthorizationError):
        action_proposals.confirm_action(db, user, request)
    assert db.writes == 0


def test_action_proposal_cancel_requires_current_version(monkeypatch):
    _register(monkeypatch)
    db = _DB()
    user = SimpleNamespace(id=5, status="ACTIVE")
    preview = action_proposals.propose_action(db, user, "test.create", {"purpose": "实验"}, idempotency_key="req-6")
    with pytest.raises(DuplicateResourceError):
        action_proposals.cancel_action(db, user, preview.confirmation_id, 2)
    action_proposals.cancel_action(db, user, preview.confirmation_id, 1)
    assert db.rows[0].status == "CANCELLED"


def test_action_proposal_rejects_unregistered_handler(monkeypatch):
    _register(monkeypatch)
    with pytest.raises(BusinessValidationError, match="不支持"):
        action_proposals.propose_action(_DB(), SimpleNamespace(id=5, status="ACTIVE"), "arbitrary.service", {}, idempotency_key="req-7")
