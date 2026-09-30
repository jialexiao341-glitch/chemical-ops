"""Require current evidence, a responsible owner and an independent reviewer."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.insights.model import InsightSnapshot
from app.modules.inventory import service as inventory_service
from app.modules.inventory.model import InventoryBalance, InventoryBatch
from app.modules.system.model import User
from .conftest import login


pytestmark = pytest.mark.integration


@pytest.fixture
def drill(client, db_session, demo_password):
    receiver = db_session.scalar(select(User).where(User.username == "warehouse_receiver"))
    sample = next(row for row in db_session.scalars(select(InventoryBalance).order_by(InventoryBalance.id)).all() if inventory_service._can_access_warehouse(db_session, receiver, row.warehouse_id))
    batch = InventoryBatch(product_id=sample.product_id, batch_no="TEST-REPORT-WORKFLOW")
    db_session.add(batch)
    db_session.flush()
    balance = InventoryBalance(warehouse_id=sample.warehouse_id, location_id=sample.location_id, product_id=sample.product_id, batch_id=batch.id, unit_id=sample.unit_id, quantity=Decimal(0), locked_quantity=Decimal(0))
    db_session.add(balance)
    db_session.flush()
    admin = login(client, "system_admin", demo_password)
    warehouse = login(client, "warehouse_receiver", demo_password)
    base = f"/api/v1/insights/batch-impact/{balance.id}"
    snapshot = client.post(f"{base}/snapshots", headers=admin)
    assert snapshot.status_code == 200, snapshot.text
    checks = client.post(f"{base}/checks", headers=admin, params={"snapshot_id": snapshot.json()["id"]})
    assert checks.status_code == 200, checks.text
    check_id = checks.json()[0]["id"]
    return base, balance, admin, warehouse, receiver, check_id


def ready_report(client, drill):
    base, _, admin, warehouse, _, check_id = drill
    checked = client.patch(f"{base}/checks/{check_id}", headers=warehouse, json={"status": "CHECKED", "finding": "账面和流水均为零，来源范围已核实"})
    assert checked.status_code == 200, checked.text
    verified = client.patch(f"{base}/checks/{check_id}", headers=admin, json={"status": "VERIFIED"})
    assert verified.status_code == 200, verified.text
    report = client.post(f"{base}/recall-reports", headers=admin)
    assert report.status_code == 200, report.text
    assert report.json()["result_json"]["status"] == "READY_FOR_REVIEW"
    return report.json()


def test_report_requires_complete_checks_and_independent_final_review(client, db_session, drill):
    base, balance, admin, warehouse, _, _ = drill
    incomplete = client.post(f"{base}/recall-reports", headers=admin).json()
    assert client.post(f"{base}/recall-reports/{incomplete['id']}/workflow", headers=admin, json={"action": "SUBMIT", "conclusion": "完成"}).status_code == 400
    report = ready_report(client, drill)
    url = f"{base}/recall-reports/{report['id']}/workflow"
    assert client.get(f"{base}/recall-reports/{report['id']}", headers=warehouse).status_code == 404
    assert client.post(url, headers=admin, json={"action": "SUBMIT", "conclusion": "  "}).status_code == 400
    submitted = client.post(url, headers=admin, json={"action": "SUBMIT", "conclusion": "批次影响范围已逐项核实，数量无差异"})
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["workflow"]["submitted_at"]
    assert client.get(f"{base}/recall-reports/{report['id']}", headers=warehouse).status_code == 200
    assert client.post(url, headers=admin, json={"action": "COMPLETE", "reason": "通过"}).status_code == 400
    assert client.post(url, headers=warehouse, json={"action": "COMPLETE", "reason": "  "}).status_code == 400
    completed = client.post(url, headers=warehouse, json={"action": "COMPLETE", "reason": "复核来源和数量，确认演练完成"})
    assert completed.status_code == 200, completed.text
    workflow = completed.json()["workflow"]
    assert workflow["status"] == "COMPLETED" and workflow["completed_at"]
    assert workflow["submitted_by"] != workflow["reviewed_by"]
    assert [event["action"] for event in workflow["events"]] == ["SUBMIT", "COMPLETE"]
    assert client.post(url, headers=admin, json={"action": "ASSIGN", "owner_id": workflow["reviewed_by"]}).status_code == 400
    assert db_session.get(InsightSnapshot, report["id"]).result_json == report["result_json"]
    assert db_session.get(InventoryBalance, balance.id).quantity == Decimal(0)


def test_report_assignment_return_and_changed_evidence_are_checked(client, db_session, drill):
    base, balance, admin, warehouse, receiver, _ = drill
    report = ready_report(client, drill)
    url = f"{base}/recall-reports/{report['id']}/workflow"
    owners = client.get(f"{base}/recall-reports/{report['id']}/owners", headers=admin)
    assert owners.status_code == 200, owners.text
    assert receiver.id in {person["id"] for person in owners.json()}
    assigned = client.post(url, headers=admin, json={"action": "ASSIGN", "owner_id": receiver.id})
    assert assigned.status_code == 200, assigned.text
    assert client.post(url, headers=admin, json={"action": "SUBMIT", "conclusion": "完成"}).status_code == 400
    submitted = client.post(url, headers=warehouse, json={"action": "SUBMIT", "conclusion": "本批次已核查"})
    assert submitted.status_code == 200, submitted.text
    returned = client.post(url, headers=admin, json={"action": "RETURN", "reason": "请补充范围确认说明"})
    assert returned.status_code == 200, returned.text
    assert returned.json()["workflow"]["status"] == "RETURNED"
    submitted = client.post(url, headers=warehouse, json={"action": "SUBMIT", "conclusion": "本批次所有库位均已核查，系统外去向已说明"})
    assert submitted.status_code == 200, submitted.text
    balance.quantity = Decimal("1")
    db_session.flush()
    stale = client.post(url, headers=admin, json={"action": "COMPLETE", "reason": "确认完成"})
    assert stale.status_code == 400, stale.text
    assert "重新生成" in stale.text
    assert db_session.get(InsightSnapshot, report["id"]).result_json == report["result_json"]


def test_report_cannot_bypass_permissions_or_reopened_checks(client, db_session, demo_password, drill):
    base, _, admin, warehouse, _, check_id = drill
    report = ready_report(client, drill)
    url = f"{base}/recall-reports/{report['id']}/workflow"
    viewer = db_session.scalar(select(User).where(User.username == "finance_viewer"))
    assert client.post(url, headers=admin, json={"action": "ASSIGN", "owner_id": viewer.id}).status_code == 400
    viewer_headers = login(client, "finance_viewer", demo_password)
    assert client.post(url, headers=viewer_headers, json={"action": "SUBMIT", "conclusion": "完成"}).status_code == 403
    submitted = client.post(url, headers=admin, json={"action": "SUBMIT", "conclusion": "所有核查已完成"})
    assert submitted.status_code == 200, submitted.text
    reopened = client.patch(f"{base}/checks/{check_id}", headers=warehouse, json={"status": "OPEN"})
    assert reopened.status_code == 200, reopened.text
    final = client.post(url, headers=warehouse, json={"action": "COMPLETE", "reason": "确认完成"})
    assert final.status_code == 400, final.text
    current = client.get(f"{base}/recall-reports/{report['id']}", headers=admin).json()
    assert current["workflow"]["status"] == "SUBMITTED" and current["workflow"]["completed_at"] is None
