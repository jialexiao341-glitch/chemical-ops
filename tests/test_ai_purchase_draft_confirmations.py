"""采购申请草稿确认必须原子消费快照，重复执行只返回原结果。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.errors import AuthorizationError, BusinessValidationError, DuplicateResourceError
from app.modules.ai import purchase_draft_confirmations as confirmations
from app.modules.ai.schema import AIPurchaseDraftConfirm


class _DB:
    def __init__(self, confirmation):
        self.confirmation = confirmation
        self.commits = 0

    def scalar(self, _query):
        return self.confirmation

    def commit(self):
        self.commits += 1


def _confirmation(*, status="PENDING", expires_at=None):
    return SimpleNamespace(
        confirmation_id="a" * 32,
        user_id=5,
        preview_version=1,
        request_hash=confirmations._hash({
            "purpose": "实验采购", "priority": "NORMAL", "currency_code": "CNY",
            "items": [{"requested_name": "乙醇", "product_id": None, "quantity": "2", "unit_id": 3}],
        }),
        draft_payload={
            "purpose": "实验采购", "priority": "NORMAL", "currency_code": "CNY",
            "items": [{"requested_name": "乙醇", "product_id": None, "quantity": "2", "unit_id": 3}],
        },
        object_versions={"actor_department_id": 2, "products": {}, "units": {}},
        status=status,
        expires_at=expires_at or datetime.utcnow() + timedelta(minutes=5),
        result={"request_no": "PR001", "status": "DRAFT"} if status == "EXECUTED" else None,
    )


def test_same_confirmation_replay_returns_saved_result_without_second_write(monkeypatch):
    confirmation = _confirmation()
    db = _DB(confirmation)
    calls = []
    monkeypatch.setattr(confirmations, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(confirmations, "get_user_permission_codes", lambda *_args: ["procurement.requests.write"])

    class _Read:
        @classmethod
        def model_validate(cls, request):
            return cls()

        def model_dump(self, **_kwargs):
            return {"request_no": "PR001", "status": "DRAFT"}

    monkeypatch.setattr(confirmations, "PurchaseRequestRead", _Read)
    monkeypatch.setattr(confirmations.purchase_request_service, "create_request", lambda *_args, **kwargs: calls.append(kwargs) or SimpleNamespace(id=41))
    user = SimpleNamespace(id=5, status="ACTIVE", department_id=2)
    data = AIPurchaseDraftConfirm(confirmation_id="a" * 32, preview_version=1, confirm=True)

    first = confirmations.confirm_purchase_draft(db, user, data)
    assert confirmation.status == "EXECUTED"
    assert confirmation.purchase_request_id == 41
    assert confirmation.executed_at is not None
    confirmation.status = "EXECUTED"
    confirmation.result = first
    second = confirmations.confirm_purchase_draft(db, user, data)

    assert first == second == {"request_no": "PR001", "status": "DRAFT"}
    assert calls == [{"commit": False}]
    assert db.commits == 1


def test_permission_revocation_blocks_confirmation(monkeypatch):
    monkeypatch.setattr(confirmations, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(confirmations, "get_user_permission_codes", lambda *_args: [])
    data = AIPurchaseDraftConfirm(confirmation_id="a" * 32, preview_version=1, confirm=True)
    with pytest.raises(AuthorizationError):
        confirmations.confirm_purchase_draft(_DB(_confirmation()), SimpleNamespace(id=5, status="ACTIVE", department_id=2), data)


def test_expired_preview_is_marked_and_rejected(monkeypatch):
    monkeypatch.setattr(confirmations, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(confirmations, "get_user_permission_codes", lambda *_args: ["procurement.requests.write"])
    db = _DB(_confirmation(expires_at=datetime.utcnow() - timedelta(seconds=1)))
    data = AIPurchaseDraftConfirm(confirmation_id="a" * 32, preview_version=1, confirm=True)
    with pytest.raises(DuplicateResourceError, match="过期"):
        confirmations.confirm_purchase_draft(db, SimpleNamespace(id=5, status="ACTIVE", department_id=2), data)
    assert db.confirmation.status == "EXPIRED"
    assert db.commits == 1


def test_changed_snapshot_parameters_are_rejected_before_domain_write(monkeypatch):
    monkeypatch.setattr(confirmations, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(confirmations, "get_user_permission_codes", lambda *_args: ["procurement.requests.write"])
    confirmation = _confirmation()
    confirmation.draft_payload["purpose"] = "修改后的用途"
    db = _DB(confirmation)
    writes = []
    monkeypatch.setattr(confirmations.purchase_request_service, "create_request", lambda *_args, **_kwargs: writes.append(True))
    data = AIPurchaseDraftConfirm(confirmation_id="a" * 32, preview_version=1, confirm=True)
    with pytest.raises(BusinessValidationError, match="参数校验"):
        confirmations.confirm_purchase_draft(db, SimpleNamespace(id=5, status="ACTIVE", department_id=2), data)
    assert not writes


def test_changed_user_department_invalidates_preview(monkeypatch):
    monkeypatch.setattr(confirmations, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(confirmations, "get_user_permission_codes", lambda *_args: ["procurement.requests.write"])
    data = AIPurchaseDraftConfirm(confirmation_id="a" * 32, preview_version=1, confirm=True)
    with pytest.raises(DuplicateResourceError, match="部门已变化"):
        confirmations.confirm_purchase_draft(
            _DB(_confirmation()), SimpleNamespace(id=5, status="ACTIVE", department_id=7), data
        )


def test_confirm_requires_explicit_true_and_exact_preview_version(monkeypatch):
    with pytest.raises(ValidationError):
        AIPurchaseDraftConfirm(confirmation_id="a" * 32, preview_version=1, confirm=False)
    monkeypatch.setattr(confirmations, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(confirmations, "get_user_permission_codes", lambda *_args: ["procurement.requests.write"])
    data = AIPurchaseDraftConfirm(confirmation_id="a" * 32, preview_version=2, confirm=True)
    with pytest.raises(DuplicateResourceError, match="版本已变化"):
        confirmations.confirm_purchase_draft(
            _DB(_confirmation()), SimpleNamespace(id=5, status="ACTIVE", department_id=2), data
        )
