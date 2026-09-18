"""关键业务失败时的事务回滚测试。"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.inventory.model import InventoryBalance

from .conftest import login


pytestmark = pytest.mark.integration


def test_return_insufficient_stock_rolls_back(client: TestClient, db_session, demo_password: str) -> None:
    """退货库存不足时，申请状态和库存数量都不能被部分修改。"""

    balance = db_session.scalar(select(InventoryBalance).where(InventoryBalance.quantity > 0).order_by(InventoryBalance.id).limit(1))
    assert balance is not None
    before = Decimal(balance.quantity)
    warehouse = login(client, "warehouse_receiver", demo_password)
    manager = login(client, "procurement_manager", demo_password)
    created = client.post("/api/v1/inventory/returns", headers=warehouse, json={"supplier_id": 1, "reason": "故障注入测试", "items": [{"product_id": balance.product_id, "warehouse_id": balance.warehouse_id, "location_id": balance.location_id, "batch_id": balance.batch_id, "unit_id": balance.unit_id, "requested_quantity": str(before + Decimal('1'))}]})
    assert created.status_code == 201, created.text
    return_id = created.json()["id"]
    assert client.post(f"/api/v1/inventory/returns/{return_id}/submit", headers=warehouse).status_code == 200
    assert client.post(f"/api/v1/inventory/returns/{return_id}/approve", headers=manager).status_code == 200
    failed = client.post(f"/api/v1/inventory/returns/{return_id}/execute", headers=warehouse)
    assert failed.status_code == 400
    assert "库存不足" in failed.json()["detail"]
    db_session.refresh(balance)
    assert Decimal(balance.quantity) == before
