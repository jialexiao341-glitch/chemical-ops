"""Batch impact evidence must survive review without changing inventory."""

import pytest
from sqlalchemy import and_, or_, select

from app.modules.inventory.model import InventoryBalance, InventoryTransaction
from app.modules.inventory import service as inventory_service
from app.modules.insights.model import BatchCheckEvent, BatchCheckItem, InsightSnapshot
from app.modules.system.model import User

from .conftest import login


pytestmark = pytest.mark.integration


def test_batch_snapshot_and_checklist_are_scoped_and_idempotent(client, db_session, demo_password):
    receiver = db_session.scalar(select(User).where(User.username == "warehouse_receiver"))
    balance = next((row for row in db_session.scalars(select(InventoryBalance).order_by(InventoryBalance.id)).all() if receiver is not None and inventory_service._can_access_warehouse(db_session, receiver, row.warehouse_id)), None)
    if balance is None:
        pytest.skip("测试数据库缺少库存余额")
    admin = login(client, "system_admin", demo_password)
    warehouse = login(client, "warehouse_receiver", demo_password)
    viewer = login(client, "finance_viewer", demo_password)
    base = f"/api/v1/insights/batch-impact/{balance.id}"

    snapshot_response = client.post(f"{base}/snapshots", headers=admin)
    assert snapshot_response.status_code == 200, snapshot_response.text
    snapshot_id = snapshot_response.json()["id"]
    assert db_session.get(InsightSnapshot, snapshot_id).result_json["kind"] == "batch-impact"
    assert len(client.get(f"{base}/snapshots", headers=admin).json()) == 1
    assert client.get(f"{base}/snapshots", headers=warehouse).json() == []
    assert client.post(f"{base}/checks", headers=viewer, params={"snapshot_id": snapshot_id}).status_code == 403

    first = client.post(f"{base}/checks", headers=admin, params={"snapshot_id": snapshot_id})
    assert first.status_code == 200, first.text
    assert first.json()
    again = client.post(f"{base}/checks", headers=admin, params={"snapshot_id": snapshot_id})
    assert again.status_code == 200, again.text
    assert [item["id"] for item in again.json()] == [item["id"] for item in first.json()]
    outbound = db_session.scalars(select(InventoryTransaction).where(InventoryTransaction.batch_id == balance.batch_id, or_(InventoryTransaction.transaction_type == "OUTBOUND", and_(InventoryTransaction.transaction_type == "INBOUND", InventoryTransaction.source_type == "INVENTORY_TRANSFER")))).all()
    assert {item["transaction_id"] for item in first.json() if item["transaction_id"] is not None} == {row.id for row in outbound}

    item = next(row for row in first.json() if row["balance_id"] == balance.id)
    item_url = f"{base}/checks/{item['id']}"
    assignees = client.get(f"{base}/assignees", headers=admin)
    assert assignees.status_code == 200, assignees.text
    assert receiver.id in {person["id"] for person in assignees.json()[str(item["id"])]}
    assigned = client.patch(item_url, headers=admin, json={"assignee_id": receiver.id})
    assert assigned.status_code == 200, assigned.text
    missing_note = client.patch(item_url, headers=admin, json={"status": "CHECKED"})
    assert missing_note.status_code == 400
    checked = client.patch(item_url, headers=warehouse, json={"status": "CHECKED", "finding": "已核对该库位余额与来源流水"})
    assert checked.status_code == 200, checked.text
    self_review = client.patch(item_url, headers=warehouse, json={"status": "VERIFIED"})
    assert self_review.status_code == 400
    reviewed = client.patch(item_url, headers=admin, json={"status": "VERIFIED"})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["reviewed_by"] != reviewed.json()["checked_by"]
    assert db_session.get(InventoryBalance, balance.id).quantity == balance.quantity
    assert db_session.scalar(select(BatchCheckItem).where(BatchCheckItem.id == item["id"])).status == "VERIFIED"
    events = client.get(f"{item_url}/events", headers=admin)
    assert events.status_code == 200
    assert len(events.json()) == 3
    assert db_session.scalar(select(BatchCheckEvent).where(BatchCheckEvent.check_id == item["id"])) is not None
