"""库存 FIFO 成本和有效期预警接口测试。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from decimal import Decimal

from app.modules.inventory.model import InventoryBalance

from .conftest import login


pytestmark = pytest.mark.integration


def test_fifo_outbound_request_is_idempotent(client: TestClient, db_session, demo_password: str) -> None:
    """相同 request_no 重试时返回原结果，不重复扣库存。"""

    balance = db_session.scalar(select(InventoryBalance).where(InventoryBalance.quantity > 0).order_by(InventoryBalance.id).limit(1))
    assert balance is not None
    headers = login(client, "warehouse_receiver", demo_password)
    body = {"request_no": "TEST-FIFO-001", "product_id": balance.product_id, "warehouse_id": balance.warehouse_id, "location_id": balance.location_id, "unit_id": balance.unit_id, "quantity": "0.000001", "note": "FIFO 测试"}
    first = client.post("/api/v1/inventory/fifo-outbounds", headers=headers, json=body)
    assert first.status_code == 201, first.text
    second = client.post("/api/v1/inventory/fifo-outbounds", headers=headers, json=body)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert Decimal(second.json()["total_cost"]) == Decimal(first.json()["total_cost"])


def test_expiry_alert_endpoint_validates_window(client: TestClient, demo_password: str) -> None:
    """有效期预警接口接受合法天数并返回规范列表。"""

    headers = login(client, "warehouse_receiver", demo_password)
    response = client.get("/api/v1/inventory/expiry-alerts?days=30", headers=headers)
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)
