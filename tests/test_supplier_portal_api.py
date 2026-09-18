"""供应商门户订单隔离和确认测试。"""

import pytest
from fastapi.testclient import TestClient

from .conftest import login


pytestmark = pytest.mark.integration


def test_supplier_portal_isolated_and_confirmation_is_idempotent(client: TestClient, demo_password: str) -> None:
    """供应商账号只能访问自己的订单，订单确认重复执行会被拒绝。"""

    portal = login(client, "supplier_portal_demo", demo_password)
    listed = client.get("/api/v1/supplier-portal/orders", headers=portal)
    assert listed.status_code == 200, listed.text
    order_ids = [item["id"] for item in listed.json()["items"]]
    assert 1 in order_ids

    confirmed = client.post("/api/v1/supplier-portal/orders/1/confirm", headers=portal)
    assert confirmed.status_code == 200, confirmed.text
    repeated = client.post("/api/v1/supplier-portal/orders/1/confirm", headers=portal)
    assert repeated.status_code == 400
    assert "已经完成供应商确认" in repeated.json()["detail"]


def test_internal_buyer_cannot_use_supplier_portal(client: TestClient, demo_password: str) -> None:
    """内部采购员没有供应商门户权限。"""

    buyer = login(client, "buyer", demo_password)
    response = client.get("/api/v1/supplier-portal/orders", headers=buyer)
    assert response.status_code == 403
    assert response.json()["message"] == "无权访问"


def test_internal_admin_without_supplier_binding_cannot_use_supplier_portal(client: TestClient, demo_password: str) -> None:
    """系统管理员没有供应商门户绑定时也不能冒充供应商访问门户。"""

    admin = login(client, "system_admin", demo_password)
    response = client.get("/api/v1/supplier-portal/orders", headers=admin)
    assert response.status_code == 403
    assert response.json()["message"] == "无权访问"
