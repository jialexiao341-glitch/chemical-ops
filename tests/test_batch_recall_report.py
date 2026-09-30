"""A recall drill records a reproducible quantity and traceability state."""

import pytest
from decimal import Decimal
from sqlalchemy import select

from app.modules.insights.model import InsightSnapshot
from app.modules.inventory.model import InventoryBalance, InventoryTransaction
from app.modules.system.model import User

from .conftest import login


pytestmark = pytest.mark.integration


def test_recall_report_is_scoped_saved_and_keeps_its_original_state(client, db_session, demo_password):
    balance = db_session.scalar(select(InventoryBalance).order_by(InventoryBalance.id))
    assert balance is not None
    admin = login(client, "system_admin", demo_password)
    viewer = login(client, "finance_viewer", demo_password)
    base = f"/api/v1/insights/batch-impact/{balance.id}"

    assert client.post(f"{base}/recall-reports", headers=viewer).status_code in {403, 404}
    first = client.post(f"{base}/recall-reports", headers=admin)
    assert first.status_code == 200, first.text
    original = first.json()["result_json"]
    assert original["kind"] == "batch-recall-report"
    assert original["batch_id"] == balance.batch_id
    assert any(row["balance_id"] == balance.id for row in original["slots"])
    assert original["visible_transaction_count"] == len(db_session.scalars(select(InventoryTransaction).where(InventoryTransaction.batch_id == balance.batch_id)).all())
    assert db_session.get(InsightSnapshot, first.json()["id"]).result_json == original

    snapshot = client.post(f"{base}/snapshots", headers=admin)
    assert snapshot.status_code == 200, snapshot.text
    checks = client.post(f"{base}/checks", headers=admin, params={"snapshot_id": snapshot.json()["id"]})
    assert checks.status_code == 200, checks.text
    second = client.post(f"{base}/recall-reports", headers=admin)
    assert second.status_code == 200, second.text
    assert second.json()["result_json"]["missing_check_count"] <= original["missing_check_count"]
    assert client.get(f"{base}/recall-reports/{first.json()['id']}", headers=admin).json()["result_json"] == original
    assert len(client.get(f"{base}/recall-reports", headers=admin).json()) == 2
    assert client.get(f"{base}/recall-reports/{first.json()['id']}", headers=viewer).status_code in {403, 404}
    assert db_session.get(InventoryBalance, balance.id).quantity == balance.quantity


def test_recall_report_marks_unresolved_source_and_unknown_adjustment(client, db_session, demo_password):
    balance = db_session.scalar(select(InventoryBalance).order_by(InventoryBalance.id))
    admin_user = db_session.scalar(select(User).where(User.username == "system_admin"))
    assert balance is not None and admin_user is not None
    for number, tx_type in enumerate(("OUTBOUND", "ADJUSTMENT"), start=1):
        db_session.add(InventoryTransaction(
            transaction_no=f"TEST-RECALL-{balance.id}-{number}", transaction_type=tx_type,
            warehouse_id=balance.warehouse_id, location_id=balance.location_id,
            product_id=balance.product_id, batch_id=balance.batch_id, unit_id=balance.unit_id,
            quantity=Decimal("2"), source_type="UNKNOWN", source_id=99999999,
            operator_id=admin_user.id,
        ))
    db_session.flush()
    admin = login(client, "system_admin", demo_password)
    response = client.post(f"/api/v1/insights/batch-impact/{balance.id}/recall-reports", headers=admin)
    assert response.status_code == 200, response.text
    report = response.json()["result_json"]
    assert report["status"] == "INCOMPLETE"
    assert report["missing_source_count"] >= 2
    assert any(row["balance_id"] == balance.id and row["status"] == "UNKNOWN" for row in report["slots"])
    assert not any(row["balance_id"] is None and row["location_id"] == balance.location_id and row["warehouse_id"] == balance.warehouse_id and row["unit_id"] == balance.unit_id for row in report["slots"])
    assert any(row["transaction_no"] == f"TEST-RECALL-{balance.id}-1" and not row["source_found"] for row in report["outflows"])
