"""供应商门户订单与询价权限、数据范围及状态测试。"""

import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import select
from datetime import datetime, timedelta
from uuid import uuid4

from app.core.security import hash_password
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem
from app.modules.purchase_requests.model import Unit
from app.modules.rfqs.model import RFQ, RFQItem, RFQSupplier, SupplierQuote
from app.modules.supplier_portal.model import SupplierDeliveryUpdate, SupplierPortalAccount
from app.modules.products.model import Product
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
    listed_order = next(item for item in listed.json()["items"] if item["id"] == order.id)
    assert {"approvals", "events", "buyer_id", "department_id"}.isdisjoint(listed_order)

    detail = client.get(f"/api/v1/supplier-portal/orders/{order.id}", headers=portal)
    assert detail.status_code == 200, detail.text
    assert {"approvals", "events", "buyer_id", "department_id"}.isdisjoint(detail.json())

    confirmed = client.post(f"/api/v1/supplier-portal/orders/{order.id}/confirm", headers=portal)
    assert confirmed.status_code == 200, confirmed.text
    assert {"approvals", "events", "buyer_id", "department_id"}.isdisjoint(confirmed.json())
    repeated = client.post(f"/api/v1/supplier-portal/orders/{order.id}/confirm", headers=portal)
    assert repeated.status_code == 400
    assert "已经完成供应商确认" in repeated.json()["detail"]

    rejected_order = PurchaseOrder(po_no=f"TEST-PORTAL-REJECT-{suffix}", supplier_id=supplier_id,
        buyer_id=buyer_id, order_amount=0, currency_code="CNY", status="ORDERED")
    db_session.add(rejected_order)
    db_session.flush()
    rejected = client.post(
        f"/api/v1/supplier-portal/orders/{rejected_order.id}/reject",
        headers=portal,
        json={"reason": "交期无法满足"},
    )
    assert rejected.status_code == 200, rejected.text
    assert {"approvals", "events", "buyer_id", "department_id"}.isdisjoint(rejected.json())
    event = db_session.scalar(
        select(PurchaseOrderEvent).where(
            PurchaseOrderEvent.po_id == rejected_order.id,
            PurchaseOrderEvent.event_type == "SUPPLIER_REJECTED",
        )
    )
    assert event is not None and event.event_note == "交期无法满足"


def test_internal_buyer_cannot_use_supplier_portal(client: TestClient, db_session, demo_password: str) -> None:
    """内部采购员没有供应商门户权限。"""

    role_id = db_session.scalar(select(Role.id).where(Role.role_code == "BUYER"))
    assert role_id is not None
    suffix = uuid4().hex[:10]
    buyer_user = User(username=f"buyer_portal_test_{suffix}", password_hash=hash_password(demo_password),
        display_name="测试采购员", status="ACTIVE")
    db_session.add(buyer_user)
    db_session.flush()
    db_session.add(UserRole(user_id=buyer_user.id, role_id=role_id))
    db_session.flush()
    buyer = login(client, buyer_user.username, demo_password)
    response = client.get("/api/v1/supplier-portal/orders", headers=buyer)
    assert response.status_code == 403
    assert response.json()["message"] == "无权访问"


def test_internal_admin_without_supplier_binding_cannot_use_supplier_portal(client: TestClient, demo_password: str) -> None:
    """系统管理员没有供应商门户绑定时也不能冒充供应商访问门户。"""

    admin = login(client, "system_admin", demo_password)
    response = client.get("/api/v1/supplier-portal/orders", headers=admin)
    assert response.status_code == 403
    assert response.json()["message"] == "无权访问"


def test_supplier_eta_and_shipment_notice_are_scoped_and_quantity_checked(client: TestClient, db_session, demo_password: str) -> None:
    """供应商可维护本方交期并提交发货通知，服务端校验未到货余量。"""

    supplier_id = db_session.scalar(select(Supplier.id).where(Supplier.status == "ACTIVE").limit(1))
    buyer_id = db_session.scalar(select(User.id).where(User.username == "buyer"))
    role_id = db_session.scalar(select(Role.id).where(Role.role_code == "SUPPLIER_PORTAL"))
    unit = db_session.scalar(select(Unit).where(Unit.status == "ACTIVE").limit(1))
    product = db_session.scalar(select(Product).where(Product.status == "ACTIVE").limit(1))
    assert supplier_id is not None and buyer_id is not None and role_id is not None and unit is not None and product is not None

    suffix = uuid4().hex[:10]
    user = User(username=f"fulfillment_portal_{suffix}", password_hash=hash_password(demo_password),
        display_name="供应商履约测试", status="ACTIVE")
    db_session.add(user)
    db_session.flush()
    db_session.add_all([
        UserRole(user_id=user.id, role_id=role_id),
        SupplierPortalAccount(user_id=user.id, supplier_id=supplier_id, status="ACTIVE"),
    ])
    order = PurchaseOrder(po_no=f"TEST-FULFILL-{suffix}", supplier_id=supplier_id,
        buyer_id=buyer_id, order_amount=100, currency_code="CNY", status="ORDERED")
    db_session.add(order)
    db_session.flush()
    item = PurchaseOrderItem(po_id=order.id, line_no=1, product_id=product.id,
        product_name_snapshot=product.product_name, order_quantity=10, unit_id=unit.id,
        unit_price=10, planned_arrival_date=datetime.now().date() + timedelta(days=14))
    db_session.add(item)
    db_session.flush()

    portal = login(client, user.username, demo_password)
    active = client.get("/api/v1/supplier-portal/orders?status=ACTIVE", headers=portal)
    assert active.status_code == 200, active.text
    assert order.id in {row["id"] for row in active.json()["items"]}

    expected_date = (datetime.now() + timedelta(days=20)).date().isoformat()
    updated = client.put(f"/api/v1/supplier-portal/orders/{order.id}/delivery-date", headers=portal,
        json={"expected_date": expected_date, "note": "车辆排期调整"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["expected_date"] == expected_date
    db_session.refresh(order)
    db_session.refresh(item)
    assert str(order.expected_arrival_date) == expected_date
    assert str(item.planned_arrival_date) == expected_date
    assert db_session.scalar(select(SupplierDeliveryUpdate.id).where(SupplierDeliveryUpdate.po_id == order.id)) is not None

    payload = {"po_id": order.id, "shipment_date": datetime.now().date().isoformat(),
        "expected_arrival_date": expected_date, "logistics_company": "测试物流", "tracking_no": suffix,
        "items": [{"po_item_id": item.id, "planned_quantity": "4", "batch_no": "B-TEST"}]}
    created = client.post("/api/v1/supplier-portal/shipments", headers=portal, json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "IN_TRANSIT"
    listed = client.get("/api/v1/supplier-portal/shipments", headers=portal)
    assert listed.status_code == 200, listed.text
    assert any(row["id"] == created.json()["id"] for row in listed.json()["items"])

    excessive = {**payload, "tracking_no": f"{suffix}-2", "items": [{"po_item_id": item.id, "planned_quantity": "7"}]}
    rejected = client.post("/api/v1/supplier-portal/shipments", headers=portal, json=excessive)
    assert rejected.status_code == 400
    assert "剩余可发数量不足" in rejected.json()["detail"]


@pytest.mark.parametrize("storage_backend", ["local", "minio"])
def test_supplier_quality_document_upload_and_download_are_binding_scoped(client: TestClient, db_session, demo_password: str, monkeypatch, tmp_path, request, storage_backend) -> None:
    """供应商能提交并下载本方订单质量文件，未绑定供应商账号不能借文件编号访问。"""

    from app.modules.files import service as file_service
    from app.modules.system.file_model import SysFile
    import os

    if storage_backend == "minio":
        if os.environ.get("REAL_MINIO_ACCEPTANCE") != "1":
            pytest.skip("真实 MinIO 验收需显式设置 REAL_MINIO_ACCEPTANCE=1")
        assert file_service._storage_backend() == "minio"
    else:
        monkeypatch.setattr(file_service, "_storage_backend", lambda: "local")
        monkeypatch.setattr(file_service, "storage_root", lambda: tmp_path)
    supplier_id = db_session.scalar(select(Supplier.id).where(Supplier.status == "ACTIVE").limit(1))
    buyer_id = db_session.scalar(select(User.id).where(User.username == "buyer"))
    role_id = db_session.scalar(select(Role.id).where(Role.role_code == "SUPPLIER_PORTAL"))
    assert supplier_id is not None and buyer_id is not None and role_id is not None
    suffix = uuid4().hex[:10]
    user = User(username=f"quality_portal_{suffix}", password_hash=hash_password(demo_password),
        display_name="供应商质量资料测试", status="ACTIVE")
    db_session.add(user)
    db_session.flush()
    db_session.add_all([
        UserRole(user_id=user.id, role_id=role_id),
        SupplierPortalAccount(user_id=user.id, supplier_id=supplier_id, status="ACTIVE"),
    ])
    order = PurchaseOrder(po_no=f"TEST-QUALITY-{suffix}", supplier_id=supplier_id,
        buyer_id=buyer_id, order_amount=0, currency_code="CNY", status="ORDERED")
    db_session.add(order)
    db_session.flush()

    portal = login(client, user.username, demo_password)
    submitted = client.post("/api/v1/supplier-portal/quality-documents", headers=portal,
        data={"po_id": str(order.id), "document_type": "COA", "note": "批次质量证明"},
        files={"file": ("coa.txt", b"COA: batch verified", "text/plain")})
    assert submitted.status_code == 201, submitted.text
    document_id = submitted.json()["id"]
    if storage_backend == "minio":
        stored = db_session.get(SysFile, submitted.json()["file_id"])
        object_key = stored.object_key
        request.addfinalizer(lambda: file_service._delete_object(object_key))
        metadata = file_service._minio_client().stat_object(file_service._minio_bucket_for_key(object_key), object_key)
        assert metadata.size == len(b"COA: batch verified")
    listed = client.get("/api/v1/supplier-portal/quality-documents", headers=portal)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == document_id for item in listed.json()["items"])

    downloaded = client.get(f"/api/v1/supplier-portal/quality-documents/{document_id}/download", headers=portal)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == b"COA: batch verified"

    admin = login(client, "system_admin", demo_password)
    forbidden = client.get(f"/api/v1/supplier-portal/quality-documents/{document_id}/download", headers=admin)
    assert forbidden.status_code == 403


def test_supplier_portal_rfq_scope_quote_submission_and_revision(client: TestClient, db_session, demo_password: str) -> None:
    """供应商仅能读取受邀询价，提交的报价绑定登录账号供应商并可留版本。"""

    supplier_id = db_session.scalar(select(Supplier.id).where(Supplier.status == "ACTIVE").limit(1))
    buyer_id = db_session.scalar(select(User.id).where(User.username == "buyer"))
    role_id = db_session.scalar(select(Role.id).where(Role.role_code == "SUPPLIER_PORTAL"))
    unit_id = db_session.scalar(select(Unit.id).where(Unit.status == "ACTIVE").limit(1))
    assert supplier_id is not None and buyer_id is not None and role_id is not None and unit_id is not None

    suffix = uuid4().hex[:10]
    user = User(username=f"rfq_portal_{suffix}", password_hash=hash_password(demo_password),
        display_name="询价供应商", status="ACTIVE")
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role_id))
    db_session.add(SupplierPortalAccount(user_id=user.id, supplier_id=supplier_id, status="ACTIVE"))

    rfq = RFQ(rfq_no=f"TEST-RFQ-PORTAL-{suffix}", requester_id=buyer_id,
        status="SENT", quote_deadline=datetime.now() + timedelta(days=3))
    db_session.add(rfq)
    db_session.flush()
    item = RFQItem(rfq_id=rfq.id, line_no=1, requested_name="测试乙醇",
        specification="分析纯", quantity=10, unit_id=unit_id)
    db_session.add(item)
    db_session.add(RFQSupplier(rfq_id=rfq.id, supplier_id=supplier_id, invitation_channel="MANUAL"))
    db_session.flush()

    portal = login(client, user.username, demo_password)
    listed = client.get("/api/v1/supplier-portal/rfqs", headers=portal)
    assert listed.status_code == 200, listed.text
    listed_payload = listed.json()
    listed_ids = [row["id"] for row in listed_payload["items"]]
    assert rfq.id in listed_ids
    assert {"requester_id", "source_request_id", "suppliers", "quotes"}.isdisjoint(listed.json()["items"][0])

    detail = client.get(f"/api/v1/supplier-portal/rfqs/{rfq.id}", headers=portal)
    assert detail.status_code == 200, detail.text
    assert detail.json()["latest_quote"] is None
    assert {"requester_id", "source_request_id", "suppliers", "quotes", "comparisons"}.isdisjoint(detail.json())

    payload = {
        "currency_code": "CNY",
        "items": [{
            "rfq_item_id": item.id,
            "quoted_quantity": "10",
            "unit_id": unit_id,
            "unit_price": "5.20",
            "tax_rate": "13",
            "lead_days": 8,
        }],
    }
    first = client.post(f"/api/v1/supplier-portal/rfqs/{rfq.id}/quotes", headers=portal, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["response_status"] == "RESPONDED"
    assert first.json()["latest_quote"]["quote_version"] == 1
    assert {"supplier_id", "received_by", "source_file_id"}.isdisjoint(first.json()["latest_quote"])

    revised = client.post(
        f"/api/v1/supplier-portal/rfqs/{rfq.id}/quotes",
        headers=portal,
        json={**payload, "supplier_id": supplier_id, "items": [{**payload["items"][0], "unit_price": "4.95"}]},
    )
    assert revised.status_code == 422

    payload["items"][0]["unit_price"] = "4.95"
    revised = client.post(f"/api/v1/supplier-portal/rfqs/{rfq.id}/quotes", headers=portal, json=payload)
    assert revised.status_code == 200, revised.text
    assert revised.json()["latest_quote"]["quote_version"] == 2
    assert Decimal(revised.json()["latest_quote"]["items"][0]["unit_price"]) == Decimal("4.95")
    saved_quotes = list(db_session.scalars(select(SupplierQuote).where(SupplierQuote.rfq_id == rfq.id)))
    assert len(saved_quotes) == 2 and {quote.supplier_id for quote in saved_quotes} == {supplier_id}

    closed = RFQ(rfq_no=f"TEST-RFQ-CLOSED-{suffix}", requester_id=buyer_id, status="CLOSED")
    db_session.add(closed)
    db_session.flush()
    db_session.add(RFQSupplier(rfq_id=closed.id, supplier_id=supplier_id))
    db_session.flush()
    closed_response = client.post(
        f"/api/v1/supplier-portal/rfqs/{closed.id}/quotes", headers=portal, json=payload
    )
    assert closed_response.status_code == 400

    expired = RFQ(
        rfq_no=f"TEST-RFQ-EXPIRED-{suffix}",
        requester_id=buyer_id,
        status="SENT",
        quote_deadline=datetime.now() - timedelta(days=1),
    )
    db_session.add(expired)
    db_session.flush()
    db_session.add(RFQSupplier(rfq_id=expired.id, supplier_id=supplier_id))
    db_session.flush()
    expired_response = client.post(
        f"/api/v1/supplier-portal/rfqs/{expired.id}/quotes", headers=portal, json=payload
    )
    assert expired_response.status_code == 400
    visible_before_hidden = client.get("/api/v1/supplier-portal/rfqs", headers=portal)
    assert visible_before_hidden.status_code == 200, visible_before_hidden.text

    hidden = RFQ(rfq_no=f"TEST-RFQ-OTHER-{suffix}", requester_id=buyer_id, status="SENT")
    db_session.add(hidden)
    db_session.flush()
    hidden_detail = client.get(f"/api/v1/supplier-portal/rfqs/{hidden.id}", headers=portal)
    assert hidden_detail.status_code == 404
    assert hidden.id not in listed_ids
    refreshed = client.get("/api/v1/supplier-portal/rfqs", headers=portal)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["total"] == visible_before_hidden.json()["total"]
    assert hidden.id not in {row["id"] for row in refreshed.json()["items"]}
