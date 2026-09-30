"""Reviewed exception suggestions reuse the existing task workflow."""

import pytest
from sqlalchemy import select

from app.modules.insights.model import ExceptionActionDecision, ExceptionActionEvent, InsightSnapshot
from app.modules.operation_exceptions.model import OperationTask
from app.modules.system.model import User

from .conftest import login


pytestmark = pytest.mark.integration


def test_exception_suggestion_decision_is_idempotent_and_blocks_early_close(client, db_session, demo_password):
    manager = login(client, "procurement_manager", demo_password)
    viewer = login(client, "finance_viewer", demo_password)
    manager_user = db_session.scalar(select(User).where(User.username == "procurement_manager"))
    created = client.post("/api/v1/operation-exceptions", headers=manager, json={
        "exception_type": "OTHER", "source_type": "OTHER", "source_id": 987654332,
        "owner_id": manager_user.id, "severity": "HIGH", "description": "核查来源与影响",
    })
    assert created.status_code == 201, created.text
    exception_id = created.json()["id"]
    base = f"/api/v1/insights/exception-action/{exception_id}/decision"
    assert client.post(base, headers=viewer, json={"decision": "ADOPTED", "reason": "未经授权"}).status_code == 403

    rejected = client.post(base, headers=manager, json={"decision": "REJECTED", "reason": "已核实，无需处理任务"})
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["task_id"] is None
    adopted = client.post(base, headers=manager, json={"decision": "ADOPTED", "reason": "需要跟进来源"})
    assert adopted.status_code == 200, adopted.text
    task_id = adopted.json()["task_id"]
    assert task_id is not None
    assert db_session.get(OperationTask, task_id).assignee_id == manager_user.id
    assert db_session.get(OperationTask, task_id).priority == "HIGH"
    assert client.post(base, headers=manager, json={"decision": "ADOPTED", "reason": "重复点击"}).json()["task_id"] == task_id
    assert len(client.get(f"{base}/events", headers=manager).json()) == 2
    assert db_session.scalar(select(ExceptionActionDecision).where(ExceptionActionDecision.exception_id == exception_id)) is not None
    assert len(db_session.scalars(select(ExceptionActionEvent).where(ExceptionActionEvent.decision_id == adopted.json()["id"])).all()) == 2
    assert db_session.get(InsightSnapshot, adopted.json()["snapshot_id"]).result_json["kind"] == "exception-action"

    early = client.patch(f"/api/v1/operation-exceptions/{exception_id}", headers=manager, json={"status": "RESOLVED"})
    assert early.status_code == 400
    task_url = f"/api/v1/operation-exceptions/{exception_id}/tasks/{task_id}"
    assert client.patch(task_url, headers=manager, json={"status": "PROCESSING"}).status_code == 200
    assert client.patch(task_url, headers=manager, json={"status": "COMPLETED", "completion_note": "来源核实完成"}).status_code == 200
    resolved = client.patch(f"/api/v1/operation-exceptions/{exception_id}", headers=manager, json={"status": "RESOLVED"})
    assert resolved.status_code == 200, resolved.text
