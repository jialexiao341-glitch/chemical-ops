"""管理员供应商绑定：可选范围、权限、幂等和门户隔离。"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.supplier_portal.model import SupplierPortalAccount
from app.modules.suppliers.model import Supplier
from app.modules.system.audit import AuditLog
from app.modules.system.model import Role, User, UserRole

from .conftest import login


pytestmark = pytest.mark.integration


@pytest.fixture
def binding_case(db_session):
    suffix = uuid4().hex[:10]
    user = User(username=f"binding_{suffix}", display_name="绑定测试账号", password_hash="unused", status="ACTIVE")
    suppliers = [
        Supplier(supplier_code=f"BIND-{suffix}-{i}", supplier_name=f"绑定测试供应商{i}", status=status)
        for i, status in enumerate(["ACTIVE", "ACTIVE", "INACTIVE"])
    ]
    db_session.add_all([user, *suppliers])
    db_session.flush()
    role = db_session.scalar(select(Role.id).where(Role.role_code == "SUPPLIER_PORTAL"))
    assert role is not None
    db_session.add(UserRole(user_id=user.id, role_id=role))
    db_session.flush()
    return user, suppliers


def test_binding_options_include_all_active_suppliers(client, db_session, demo_password, binding_case):
    """选择器不截断在第一页，且不暴露停用供应商与联系方式。"""
    _, suppliers = binding_case
    suffix = uuid4().hex[:10]
    db_session.add_all([
        Supplier(supplier_code=f"BIND-OPTIONS-{suffix}-{i:03}", supplier_name=f"选项测试供应商{i}", status="ACTIVE")
        for i in range(101)
    ])
    db_session.flush()
    headers = login(client, "system_admin", demo_password)
    response = client.get("/api/v1/system/supplier-binding-options", headers=headers)
    assert response.status_code == 200, response.text
    options = response.json()
    expected_ids = set(db_session.scalars(select(Supplier.id).where(Supplier.status == "ACTIVE")))
    assert {item["id"] for item in options} == expected_ids
    assert suppliers[2].id not in expected_ids
    assert all(set(item) == {"id", "supplier_code", "supplier_name"} for item in options)


def test_binding_create_repeat_replace_reactivate_and_scope(client, db_session, demo_password, binding_case):
    user, suppliers = binding_case
    headers = login(client, "system_admin", demo_password)
    portal_headers = login(client, user.username, demo_password)
    path = f"/api/v1/system/users/{user.id}/supplier-binding"
    assert client.get(path, headers=headers).json() is None
    assert client.get("/api/v1/supplier-portal/orders", headers=portal_headers).status_code == 403
    buyer_id = db_session.scalar(select(User.id).where(User.username == "buyer"))
    orders = [PurchaseOrder(po_no=f"BIND-PO-{uuid4().hex[:12]}", supplier_id=s.id,
                            buyer_id=buyer_id, order_amount=0, currency_code="CNY", status="ORDERED")
              for s in suppliers[:2]]
    db_session.add_all(orders)
    db_session.flush()

    def save(supplier):
        response = client.put(path, headers=headers, json={"supplier_id": supplier.id})
        assert response.status_code == 200, response.text
        assert response.json()["supplier_code"] == supplier.supplier_code
        assert response.json()["status"] == "ACTIVE"

    def audit_count():
        return db_session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action_type == "BIND_SUPPLIER", AuditLog.resource_id == user.id))

    save(suppliers[0])
    assert audit_count() == 1
    save(suppliers[0])
    assert audit_count() == 1
    for supplier, expected, excluded in [(suppliers[0], orders[0], orders[1]), (suppliers[1], orders[1], orders[0])]:
        save(supplier)
        response = client.get("/api/v1/supplier-portal/orders", headers=portal_headers)
        assert response.status_code == 200, response.text
        ids = {item["id"] for item in response.json()["items"]}
        assert expected.id in ids and excluded.id not in ids
    account = db_session.scalar(select(SupplierPortalAccount).where(SupplierPortalAccount.user_id == user.id))
    account.status = "INACTIVE"
    db_session.flush()
    assert client.get(path, headers=headers).json()["status"] == "INACTIVE"
    save(suppliers[1])
    assert audit_count() == 3
    assert db_session.scalar(select(func.count()).select_from(SupplierPortalAccount).where(
        SupplierPortalAccount.user_id == user.id)) == 1
    log = db_session.scalar(select(AuditLog).where(AuditLog.action_type == "BIND_SUPPLIER", AuditLog.resource_id == user.id).order_by(AuditLog.id.desc()))
    assert log.actor_id == db_session.scalar(select(User.id).where(User.username == "system_admin"))


@pytest.mark.parametrize("username", ["buyer", "supplier_portal"])
def test_binding_management_requires_user_write(client, demo_password, binding_case, username):
    user, suppliers = binding_case
    headers = login(client, username, demo_password)
    path = f"/api/v1/system/users/{user.id}/supplier-binding"
    assert client.get("/api/v1/system/supplier-binding-options", headers=headers).status_code == 403
    assert client.get(path, headers=headers).status_code == 403
    assert client.put(path, headers=headers, json={"supplier_id": suppliers[0].id}).status_code == 403


def test_binding_rejects_invalid_targets_without_changing_existing(client, db_session, demo_password, binding_case):
    user, suppliers = binding_case
    headers = login(client, "system_admin", demo_password)
    path = f"/api/v1/system/users/{user.id}/supplier-binding"
    assert client.put(path, headers=headers, json={"supplier_id": suppliers[0].id}).status_code == 200
    for supplier_id, expected in [(suppliers[2].id, 400), (2147483647, 404), (0, 422), (None, 422)]:
        response = client.put(path, headers=headers, json={"supplier_id": supplier_id})
        assert response.status_code == expected, response.text
        assert client.get(path, headers=headers).json()["supplier_id"] == suppliers[0].id
    assert client.put("/api/v1/system/users/2147483647/supplier-binding", headers=headers,
                      json={"supplier_id": suppliers[0].id}).status_code == 404
    user.status = "INACTIVE"
    db_session.flush()
    assert client.put(path, headers=headers, json={"supplier_id": suppliers[1].id}).status_code == 400
    assert client.get(path, headers=headers).json()["supplier_id"] == suppliers[0].id


@pytest.mark.parametrize("username", ["system_admin", "buyer", "quality_manager"])
def test_binding_rejects_internal_roles(client, db_session, demo_password, binding_case, username):
    _, suppliers = binding_case
    admin = login(client, "system_admin", demo_password)
    user_id = db_session.scalar(select(User.id).where(User.username == username))
    response = client.put(f"/api/v1/system/users/{user_id}/supplier-binding", headers=admin,
                          json={"supplier_id": suppliers[0].id})
    assert response.status_code == 400, response.text
    assert "供应商门户角色" in response.json()["detail"]


def test_changing_portal_role_disables_binding(client, db_session, demo_password, binding_case):
    user, suppliers = binding_case
    admin = login(client, "system_admin", demo_password)
    path = f"/api/v1/system/users/{user.id}"
    assert client.put(path + '/supplier-binding', headers=admin, json={"supplier_id": suppliers[0].id}).status_code == 200
    buyer = db_session.scalar(select(Role.id).where(Role.role_code == "BUYER"))
    response = client.patch(path, headers=admin, json={"role_ids": [buyer]})
    assert response.status_code == 200, response.text
    assert response.json()["role_codes"] == ["BUYER"]
    assert client.get(path + '/supplier-binding', headers=admin).json()["status"] == 'INACTIVE'
