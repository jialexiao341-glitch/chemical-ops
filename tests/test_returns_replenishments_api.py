"""退货和补货申请接口测试。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.inventory.model import InventoryBalance
from app.modules.purchase_orders.model import PurchaseOrder

from .conftest import login


pytestmark = pytest.mark.integration


def test_return_repeat_execute_is_rejected(client: TestClient, db_session, demo_password: str) -> None:
    """退货执行两次时第二次不能重复扣库存。"""

    balance = db_session.scalar(select(InventoryBalance).where(InventoryBalance.quantity > 0).order_by(InventoryBalance.id).limit(1))
    assert balance is not None
    warehouse = login(client, "warehouse_receiver", demo_password)
    manager = login(client, "procurement_manager", demo_password)
    body = {
        "supplier_id": 1,
        "reason": "自动化测试退货",
        "items": [{
            "product_id": balance.product_id,
            "warehouse_id": balance.warehouse_id,
            "location_id": balance.location_id,
            "batch_id": balance.batch_id,
            "unit_id": balance.unit_id,
            "requested_quantity": "0.000001",
        }],
    }
    created = client.post("/api/v1/inventory/returns", headers=warehouse, json=body)
    assert created.status_code == 201, created.text
    return_id = created.json()["id"]
    assert client.post(f"/api/v1/inventory/returns/{return_id}/submit", headers=warehouse).status_code == 200
    assert client.post(f"/api/v1/inventory/returns/{return_id}/approve", headers=manager).status_code == 200
    assert client.post(f"/api/v1/inventory/returns/{return_id}/execute", headers=warehouse).status_code == 200
    repeated = client.post(f"/api/v1/inventory/returns/{return_id}/execute", headers=warehouse)
    assert repeated.status_code == 400
    assert "只有已审批的退货申请可以执行" in repeated.json()["detail"]


def test_replenishment_flow_can_link_fulfillment_order(client: TestClient, db_session, demo_password: str) -> None:
    """补货申请审批后可以关联已正式下单的采购订单完成。"""

    order = db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.status == "COMPLETED").order_by(PurchaseOrder.id).limit(1))
    assert order is not None
    manager = login(client, "procurement_manager", demo_password)
    body = {
        "supplier_id": order.supplier_id,
        "source_po_id": order.id,
        "reason": "自动化测试补货",
        "items": [{"product_id": order.items[0].product_id, "unit_id": order.items[0].unit_id, "requested_quantity": "1"}],
    }
    created = client.post("/api/v1/replenishments", headers=manager, json=body)
    assert created.status_code == 201, created.text
    replenishment_id = created.json()["id"]
    assert client.post(f"/api/v1/replenishments/{replenishment_id}/submit", headers=manager).status_code == 200
    assert client.post(f"/api/v1/replenishments/{replenishment_id}/approve", headers=manager).status_code == 200
    completed = client.post(f"/api/v1/replenishments/{replenishment_id}/complete", headers=manager, json={"fulfillment_po_id": order.id})
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "COMPLETED"
