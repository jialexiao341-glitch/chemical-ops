"""异常处理任务提案：准确编号、任务字段与领域服务边界。"""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import BusinessValidationError
from app.modules.ai import action_handlers
from app.modules.operation_exceptions import service as exception_service
from app.modules.operation_exceptions.schema import OperationTaskRead


class _DB:
    def __init__(self):
        self.users = {}

    def get(self, _model, user_id):
        return self.users.get(user_id)


def _exception(**overrides):
    values = {
        "id": 5,
        "exception_no": "EX20261025000001",
        "exception_type": "DOCUMENT",
        "status": "OPEN",
        "owner_id": 7,
        "updated_at": datetime(2026, 10, 25, 2, 0, 0),
        "source_type": "PURCHASE_ORDER",
        "source_id": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _patch_service(monkeypatch, exception):
    monkeypatch.setattr(exception_service, "get_exception_by_no", lambda *_args, **_kwargs: exception)
    monkeypatch.setattr(exception_service, "get_exception_for_task_creation",
                        lambda *_args, **_kwargs: exception)
    monkeypatch.setattr(exception_service, "validate_assignee", lambda *_args, **_kwargs: None)


def test_prepare_normalizes_task_fields_and_snapshots_exception(monkeypatch):
    exception = _exception()
    _patch_service(monkeypatch, exception)
    handler = action_handlers.ExceptionTaskCreateHandler()
    prepared = handler.prepare(_DB(), SimpleNamespace(id=7, status="ACTIVE", department_id=2), {
        "exception_no": "EX20261025000001",
        "title": "联系供应商补交 COA",
        "priority": "HIGH",
        "due_at": "2026-10-30",
    })

    assert prepared["resource_id"] == 5
    assert prepared["payload"]["exception_id"] == 5
    assert prepared["payload"]["due_at"] == "2026-10-30T23:59:59"
    assert prepared["snapshot"]["exception"]["status"] == "OPEN"
    assert prepared["snapshot"]["assignee"] is None
    assert prepared["evidence"] == [{
        "type": "operation_exception", "id": 5, "exception_no": "EX20261025000001",
        "status": "OPEN", "exception_type": "DOCUMENT",
    }]
    assert {item["field"] for item in prepared["diff"]} == {"title", "priority", "due_at"}


def test_prepare_rejects_closed_exception_and_untrusted_fields(monkeypatch):
    _patch_service(monkeypatch, _exception(status="CLOSED"))
    handler = action_handlers.ExceptionTaskCreateHandler()
    user = SimpleNamespace(id=7, status="ACTIVE", department_id=2)
    with pytest.raises(BusinessValidationError, match="已关闭或已取消"):
        handler.prepare(_DB(), user, {"exception_no": "EX20261025000001", "title": "补交资料"})

    _patch_service(monkeypatch, _exception())
    with pytest.raises(BusinessValidationError, match="不允许的字段"):
        handler.prepare(_DB(), user, {"exception_no": "EX20261025000001", "title": "补交资料", "status": "CLOSED"})
    with pytest.raises(BusinessValidationError, match="只能提供准确异常编号"):
        handler.prepare(_DB(), user, {"exception_id": 5, "exception_no": "EX20261025000001", "title": "补交资料"})
    with pytest.raises(BusinessValidationError, match="准确的运营异常编号"):
        handler.prepare(_DB(), user, {"exception_no": " ", "title": "补交资料"})


def test_validate_current_rejects_changed_exception(monkeypatch):
    exception = _exception()
    _patch_service(monkeypatch, exception)
    handler = action_handlers.ExceptionTaskCreateHandler()
    user = SimpleNamespace(id=7, status="ACTIVE", department_id=2)
    prepared = handler.prepare(_DB(), user, {"exception_no": "EX20261025000001", "title": "补交资料"})
    proposal = SimpleNamespace(payload=prepared["payload"], expected_resource_snapshot=prepared["snapshot"],
                               resource_id="5")

    handler.validate_current(_DB(), user, proposal, for_update=False)
    exception.status = "PROCESSING"
    with pytest.raises(BusinessValidationError, match="已变化"):
        handler.validate_current(_DB(), user, proposal, for_update=False)


def test_execute_uses_domain_service_with_caller_transaction(monkeypatch):
    _patch_service(monkeypatch, _exception())
    task = SimpleNamespace(
        id=11, exception_id=5, title="补交资料", assignee_id=None, priority="NORMAL",
        due_at=None, status="OPEN", created_at=datetime(2026, 10, 25), updated_at=datetime(2026, 10, 25),
        completed_at=None, completion_note=None,
    )
    calls = []
    monkeypatch.setattr(exception_service, "create_task",
                        lambda _db, _user, exception_id, data, *, commit=True:
                        calls.append((exception_id, data, commit)) or task)
    proposal = SimpleNamespace(resource_id="5", payload={"exception_id": 5, "title": "补交资料"})
    result = action_handlers.ExceptionTaskCreateHandler().execute(
        _DB(), SimpleNamespace(id=7, status="ACTIVE"), proposal, commit=False)

    assert calls and calls[0][0] == 5 and calls[0][2] is False
    assert result == OperationTaskRead.model_validate(task).model_dump(mode="json")
    assert result["title"] == "补交资料"


def test_exception_task_understanding_requires_number_and_safe_fields():
    from app.modules.ai.schema import Understanding

    with pytest.raises(ValueError):
        Understanding(purpose="exception_task", slots={}, action_fields={"title": "补交资料"})
    with pytest.raises(ValueError):
        Understanding(purpose="exception_task", slots={"exception_no": "EX20261025000001"},
                      action_fields={"priority": "HIGH"})
    with pytest.raises(ValueError):
        Understanding(purpose="exception_task", slots={"exception_no": "EX20261025000001"},
                      action_fields={"title": "补交资料", "assignee_id": 7})
    with pytest.raises(ValueError):
        Understanding(purpose="exception_task", slots={"exception_no": "EX20261025000001"},
                      action_fields={"title": "补交资料", "priority": "IMMEDIATE"})

    valid = Understanding(purpose="exception_task", slots={"exception_no": "EX20261025000001"},
                          action_fields={"title": "补交资料", "priority": "HIGH", "due_at": "2026-10-30"})
    assert valid.route == "exception_task"
    assert valid.execution_mode == "none" and valid.tasks == [] and valid.sub_tasks == []


def test_exception_task_proposal_creates_task_only_after_confirmation(client, demo_password):
    from tests.conftest import login

    token = login(client, "system_admin", demo_password)
    source_id = uuid4().int % 1_000_000_000 + 1
    created = client.post("/api/v1/operation-exceptions", headers=token, json={
        "exception_type": "OTHER", "source_type": "OTHER", "source_id": source_id,
        "description": "验收用异常：供应商资料缺失", "severity": "MEDIUM",
    })
    assert created.status_code == 201, created.text
    exception = created.json()

    proposal = client.post("/api/v1/ai/action-proposals", headers=token, json={
        "action_type": "exceptions.create_task",
        "payload": {"exception_no": exception["exception_no"], "title": "联系供应商补交 COA",
                    "priority": "HIGH", "due_at": "2026-10-30"},
        "idempotency_key": uuid4().hex,
    })
    assert proposal.status_code == 200, proposal.text
    preview = proposal.json()
    assert preview["status"] == "PENDING" and preview["requires_user_confirmation"] is True
    assert preview["resource_id"] == str(exception["id"])
    assert preview["evidence"][0]["exception_no"] == exception["exception_no"]
    before = client.get(f"/api/v1/operation-exceptions/{exception['id']}/tasks", headers=token)
    assert before.status_code == 200 and before.json()["total"] == 0

    confirmed = client.post(
        f"/api/v1/ai/action-proposals/{preview['confirmation_id']}/confirm", headers=token,
        json={"confirmation_id": preview["confirmation_id"], "preview_version": 1, "confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    task = confirmed.json()
    assert task["title"] == "联系供应商补交 COA" and task["priority"] == "HIGH"
    assert task["due_at"].startswith("2026-10-30T23:59:59")

    after = client.get(f"/api/v1/operation-exceptions/{exception['id']}/tasks", headers=token)
    assert after.status_code == 200 and after.json()["total"] == 1
    detail = client.get(f"/api/v1/operation-exceptions/{exception['id']}", headers=token)
    assert detail.json()["status"] == "PROCESSING"
