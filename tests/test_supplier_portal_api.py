"""供应商门户订单隔离和确认测试。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from uuid import uuid4

from app.core.security import hash_password
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.supplier_portal.model import SupplierPortalAccount
from app.modules.suppliers.model import Supplier
from app.modules.system.model import Role, User, UserRole

from .conftest import login


pytestmark = pytest.mark.integration


def test_supplier_portal_isolated_and_confirmation_is_idempotent(client: TestClient, db_session, demo_password: str) -> None:
    """供应商账号只能访问自己的订单，订单确认重复执行会被拒绝。"""

    supplier_id = db_session.scalar(select(Supplier.id).where(Supplier.status == "ACTIVE").limit(1))
    buyer_id = db_session.scalar(select(User.id).where(User.username == "buyer"))
    role_id = db_session.scalar(select(Role.id).where(Role.role_code == "SUPPLIER_PORTAL"))
    assert supplier_id is not None and buyer_id is not None and role_id is not None
    suffix = uuid4().hex[:10]
    user = User(username=f"portal_test_{suffix}", password_hash=hash_password(demo_password),
        display_name="测试供应商门户", status="ACTIVE")
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role_id))
    db_session.add(SupplierPortalAccount(user_id=user.id, supplier_id=supplier_id, status="ACTIVE"))
    order = PurchaseOrder(po_no=f"TEST-PORTAL-{suffix}", supplier_id=supplier_id,
        buyer_id=buyer_id, order_amount=0, currency_code="CNY", status="ORDERED")
    db_session.add(order)
    db_session.flush()
    portal = login(client, user.username, demo_password)
    listed = client.get("/api/v1/supplier-portal/orders", headers=portal)
    assert listed.status_code == 200, listed.text
    order_ids = [item["id"] for item in listed.json()["items"]]
    assert order.id in order_ids

    confirmed = client.post(f"/api/v1/supplier-portal/orders/{order.id}/confirm", headers=portal)
    assert confirmed.status_code == 200, confirmed.text
    repeated = client.post(f"/api/v1/supplier-portal/orders/{order.id}/confirm", headers=portal)
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
