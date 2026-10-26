"""退货和补货申请接口测试。"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.inventory.model import InventoryBalance, InventoryBatch, Warehouse
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.system.model import User

from .conftest import login


pytestmark = pytest.mark.integration


def test_return_repeat_execute_is_rejected(client: TestClient, db_session, demo_password: str) -> None:
    """退货执行两次时第二次不能重复扣库存。"""

    balance = db_session.scalar(select(InventoryBalance).where(InventoryBalance.quantity > 0).order_by(InventoryBalance.id).limit(1))
    assert balance is not None
    batch = db_session.get(InventoryBatch, balance.batch_id)
    assert batch is not None and batch.supplier_id is not None
    warehouse = login(client, "warehouse_receiver", demo_password)
    manager = login(client, "procurement_manager", demo_password)
    body = {
        "supplier_id": batch.supplier_id,
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


def test_warehouse_user_can_only_read_returns_in_authorized_warehouses(
    client: TestClient, db_session, demo_password: str
) -> None:
    """仓库人员的退货列表、详情和办理入口使用同一授权仓库范围。"""

    balance = db_session.scalar(
        select(InventoryBalance)
        .where(InventoryBalance.quantity > 0)
        .order_by(InventoryBalance.id)
        .limit(1)
    )
    warehouse_user = db_session.scalar(select(User).where(User.username == "warehouse_receiver"))
    other_user = db_session.scalar(
        select(User).where(User.id != warehouse_user.id).order_by(User.id).limit(1)
    ) if warehouse_user else None
    assert balance is not None and warehouse_user is not None and other_user is not None
    warehouse_record = db_session.get(Warehouse, balance.warehouse_id)
    batch = db_session.get(InventoryBatch, balance.batch_id)
    assert warehouse_record is not None and batch is not None and batch.supplier_id is not None
    warehouse_record.manager_id = warehouse_user.id
    db_session.flush()

    headers = login(client, "warehouse_receiver", demo_password)
    created = client.post(
        "/api/v1/inventory/returns",
        headers=headers,
        json={
            "supplier_id": batch.supplier_id,
            "reason": "授权仓库范围回归",
            "items": [{
                "product_id": balance.product_id,
                "warehouse_id": balance.warehouse_id,
                "location_id": balance.location_id,
                "batch_id": balance.batch_id,
                "unit_id": balance.unit_id,
                "requested_quantity": "0.000001",
            }],
        },
    )
    assert created.status_code == 201, created.text
    return_id = created.json()["id"]
    before_scope_change = client.get("/api/v1/inventory/returns", headers=headers)
    assert before_scope_change.status_code == 200
    assert return_id in {row["id"] for row in before_scope_change.json()["items"]}

    warehouse_record.manager_id = other_user.id
    db_session.flush()
    scoped = client.get("/api/v1/inventory/returns", headers=headers)
    assert scoped.status_code == 200
    assert return_id not in {row["id"] for row in scoped.json()["items"]}
    assert client.get(f"/api/v1/inventory/returns/{return_id}", headers=headers).status_code == 404
    assert client.post(f"/api/v1/inventory/returns/{return_id}/submit", headers=headers).status_code == 404
    assert client.post(f"/api/v1/inventory/returns/{return_id}/cancel", headers=headers).status_code == 404


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
    assert client.post(f"/api/v1/replenishments/{replenishment_id}/approve", headers=manager).status_code == 400
    admin = login(client, "system_admin", demo_password)
    assert client.post(f"/api/v1/replenishments/{replenishment_id}/approve", headers=admin).status_code == 200
    completed = client.post(f"/api/v1/replenishments/{replenishment_id}/complete", headers=manager, json={"fulfillment_po_id": order.id})
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "COMPLETED"


def test_return_insufficient_stock_rolls_back(client: TestClient, db_session, demo_password: str) -> None:
    """退货库存不足时，申请状态和库存数量都不能被部分修改。"""

    balance = db_session.scalar(select(InventoryBalance).where(InventoryBalance.quantity > 0).order_by(InventoryBalance.id).limit(1))
    assert balance is not None
    batch = db_session.get(InventoryBatch, balance.batch_id)
    assert batch is not None and batch.supplier_id is not None
    before = Decimal(balance.quantity)
    warehouse = login(client, "warehouse_receiver", demo_password)
    manager = login(client, "procurement_manager", demo_password)
    created = client.post("/api/v1/inventory/returns", headers=warehouse, json={"supplier_id": batch.supplier_id, "reason": "故障注入测试", "items": [{"product_id": balance.product_id, "warehouse_id": balance.warehouse_id, "location_id": balance.location_id, "batch_id": balance.batch_id, "unit_id": balance.unit_id, "requested_quantity": str(before + Decimal('1'))}]})
    assert created.status_code == 201, created.text
    return_id = created.json()["id"]
    assert client.post(f"/api/v1/inventory/returns/{return_id}/submit", headers=warehouse).status_code == 200
    assert client.post(f"/api/v1/inventory/returns/{return_id}/approve", headers=manager).status_code == 200
    failed = client.post(f"/api/v1/inventory/returns/{return_id}/execute", headers=warehouse)
    assert failed.status_code == 400
    assert "库存不足" in failed.json()["detail"]
    db_session.refresh(balance)
    assert Decimal(balance.quantity) == before
