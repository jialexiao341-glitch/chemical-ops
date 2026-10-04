"""供应商对账协同、分页与输入边界的事务回滚验收。"""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.modules.finance.model import FinanceReconciliation
from app.modules.supplier_portal.model import SupplierPortalAccount
from app.modules.suppliers.model import Supplier
from app.modules.system.model import Role, User, UserRole
from .conftest import login
from .test_reconciliation_items import scenario  # noqa: F401 -- shared business-chain fixture

pytestmark = pytest.mark.integration


@pytest.fixture
def collaboration(client, db_session, demo_password, scenario):
    role = db_session.scalar(select(Role).where(Role.role_code == "SUPPLIER_PORTAL"))
    user = User(username=f"collaboration_{uuid4().hex[:10]}", display_name="对账验收供应商",
                password_hash=hash_password(demo_password), status="ACTIVE")
    db_session.add(user)
    db_session.flush()
    db_session.add_all([UserRole(user_id=user.id, role_id=role.id),
                       SupplierPortalAccount(user_id=user.id, supplier_id=scenario["supplier"].id, status="ACTIVE")])
    db_session.flush()
    response = client.post("/api/v1/finance/reconciliations", headers=scenario["headers"],
                           json={"po_id": scenario["order"].id})
    assert response.status_code == 201, response.text
    return {**scenario, "portal": login(client, user.username, demo_password), "rec_id": response.json()["id"]}


def test_supplier_reconciliation_round_trip(client, collaboration):
    s = collaboration
    path = f"/api/v1/supplier-portal/reconciliations/{s['rec_id']}"
    listed = client.get("/api/v1/supplier-portal/reconciliations",
                        headers=s["portal"], params={"keyword": s["order"].po_no, "status": "DRAFT", "page_size": 1})
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == s["rec_id"]
    second = client.get("/api/v1/supplier-portal/reconciliations", headers=s["portal"],
                        params={"keyword": s["order"].po_no, "page_size": 1, "page": 2})
    assert second.status_code == 200 and second.json()["items"] == []
    supplier_message = client.post(path + "/messages", headers=s["portal"], json={"message": " 请核对批次数量 "})
    assert supplier_message.status_code == 201, supplier_message.text
    assert supplier_message.json()["message"] == "请核对批次数量"
    reply = client.post(f"/api/v1/finance/reconciliations/{s['rec_id']}/supplier-messages",
                        headers=s["headers"], json={"message": "已按收货记录复核"})
    assert reply.status_code == 201, reply.text
    messages = client.get(path + "/messages", headers=s["portal"])
    assert messages.status_code == 200, messages.text
    assert [row["author_type"] for row in messages.json()["items"]] == ["SUPPLIER", "BUYER"]
    confirmed = client.post(path + "/confirm", headers=s["portal"], json={})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"
    assert client.post(path + "/confirm", headers=s["portal"], json={}).status_code == 400
    assert client.post(path + "/dispute", headers=s["portal"], json={"reason": "   "}).status_code == 400
    disputed = client.post(path + "/dispute", headers=s["portal"], json={"reason": "需要复核数量"})
    assert disputed.status_code == 200, disputed.text
    assert disputed.json()["status"] == "DISPUTED"
    assert client.post(path + "/confirm", headers=s["portal"], json={}).status_code == 200


def test_reconciliation_cross_supplier_access_is_rejected(client, db_session, demo_password, collaboration):
    s = collaboration
    other_supplier = db_session.scalar(select(Supplier).where(Supplier.id != s["supplier"].id))
    role_id = db_session.scalar(select(Role.id).where(Role.role_code == "SUPPLIER_PORTAL"))
    user = User(username=f"other_collab_{uuid4().hex[:10]}", display_name="其他供应商",
                password_hash=hash_password(demo_password), status="ACTIVE")
    db_session.add(user)
    db_session.flush()
    db_session.add_all([UserRole(user_id=user.id, role_id=role_id),
                       SupplierPortalAccount(user_id=user.id, supplier_id=other_supplier.id, status="ACTIVE")])
    db_session.flush()
    other = login(client, user.username, demo_password)
    path = f"/api/v1/supplier-portal/reconciliations/{s['rec_id']}"
    listed = client.get("/api/v1/supplier-portal/reconciliations", headers=other,
                        params={"keyword": s["order"].po_no})
    assert listed.status_code == 200 and listed.json()["total"] == 0
    assert client.get(path + "/messages", headers=other).status_code == 404
    order_path = f"/api/v1/supplier-portal/orders/{s['order'].id}"
    assert client.get(order_path, headers=other).status_code == 404
    assert client.put(order_path + "/delivery-date", headers=other,
                      json={"expected_date": "2026-11-01"}).status_code == 404
    assert client.post("/api/v1/supplier-portal/shipments", headers=other,
                       json={"po_id": s["order"].id, "items": [{"po_item_id": s["lines"][0].id, "planned_quantity": "1"}]}).status_code == 404
    for action, data in [("messages", {"message": "越权留言"}), ("confirm", {}), ("dispute", {"reason": "越权争议"})]:
        assert client.post(path + "/" + action, headers=other, json=data).status_code == 404


@pytest.mark.parametrize("status", ["CLOSED", "CANCELLED"])
def test_closed_reconciliation_cannot_be_changed(client, db_session, collaboration, status):
    s = collaboration
    rec = db_session.get(FinanceReconciliation, s["rec_id"])
    rec.status = status
    db_session.flush()
    path = f"/api/v1/supplier-portal/reconciliations/{s['rec_id']}"
    for action, data in [("messages", {"message": "结束后留言"}), ("confirm", {}), ("dispute", {"reason": "结束后争议"})]:
        assert client.post(path + "/" + action, headers=s["portal"], json=data).status_code == 400


@pytest.mark.parametrize("supplier_side", [True, False])
def test_blank_reconciliation_message_is_rejected(client, collaboration, supplier_side):
    s = collaboration
    if supplier_side:
        path = f"/api/v1/supplier-portal/reconciliations/{s['rec_id']}/messages"
        headers = s["portal"]
    else:
        path = f"/api/v1/finance/reconciliations/{s['rec_id']}/supplier-messages"
        headers = s["headers"]
    response = client.post(path, headers=headers, json={"message": " \n\t "})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("resource", ["rfqs", "orders", "delivery-updates", "shipments", "quality-documents", "reconciliations"])
def test_supplier_list_pagination_contract(client, collaboration, resource):
    path = f"/api/v1/supplier-portal/{resource}"
    headers = collaboration["portal"]
    response = client.get(path, headers=headers, params={"page_size": 100, "keyword": "NO-MATCH-" + uuid4().hex})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
    assert response.json()["page_size"] == 100
    assert client.get(path, headers=headers, params={"page_size": 200}).status_code == 422
