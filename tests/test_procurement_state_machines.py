"""采购、到货、质量和运营异常的端到端状态机测试。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

from app.modules.products.model import Product
from app.modules.purchase_requests.model import Unit
from app.modules.suppliers.model import Supplier
from app.modules.rfqs.model import SupplierQuote
from app.core.security import hash_password
from app.modules.system.model import User
from .conftest import login


pytestmark = pytest.mark.integration


def test_rfq_to_purchase_order_to_quality_acceptance(
    client: TestClient, db_session, demo_password: str
) -> None:
    """验证询价、比价定标、采购审批、收货和质量验收的完整转换。"""

    manager = login(client, "procurement_manager", demo_password)
    warehouse = login(client, "warehouse_receiver", demo_password)
    quality = login(client, "quality_inspector", demo_password)
    supplier = db_session.scalar(select(Supplier).where(Supplier.status == "ACTIVE").order_by(Supplier.id))
    product = db_session.scalar(select(Product).where(Product.status == "ACTIVE").order_by(Product.id))
    if supplier is None or product is None:
        pytest.skip("测试数据库需要至少一个启用的供应商和产品")
    unit = db_session.get(Unit, product.unit_id)
    assert unit is not None and unit.status == "ACTIVE", "启用产品应引用启用计量单位"

    request_response = client.post(
        "/api/v1/purchase-requests",
        headers=manager,
        json={
            "purpose": "采购到货状态机集成测试",
            "items": [
                {
                    "product_id": product.id,
                    "requested_name": product.product_name,
                    "quantity": "2",
                    "unit_id": unit.id,
                }
            ],
        },
    )
    assert request_response.status_code == 201, request_response.text
    purchase_request = request_response.json()
    request_id = purchase_request["id"]
    request_item_id = purchase_request["items"][0]["id"]
    submitted_request = client.post(f"/api/v1/purchase-requests/{request_id}/submit", headers=manager)
    assert submitted_request.status_code == 200, submitted_request.text
    assert submitted_request.json()["status"] in {"SUBMITTED", "APPROVING"}
    approved_request = client.post(
        f"/api/v1/purchase-requests/{request_id}/approve",
        headers=manager,
        json={"opinion": "测试采购申请通过"},
    )
    assert approved_request.status_code == 200, approved_request.text
    assert approved_request.json()["status"] == "APPROVED"

    rfq_response = client.post(
        "/api/v1/rfqs",
        headers=manager,
        json={
            "source_request_id": request_id,
            "items": [
                {
                    "source_request_item_id": request_item_id,
                    "product_id": product.id,
                    "requested_name": product.product_name,
                    "quantity": "2",
                    "unit_id": unit.id,
                }
            ],
            "supplier_ids": [supplier.id],
        },
    )
    assert rfq_response.status_code == 201, rfq_response.text
    rfq = rfq_response.json()
    assert rfq["status"] == "DRAFT"
    rfq_id = rfq["id"]
    rfq_item_id = rfq["items"][0]["id"]

    sent = client.post(f"/api/v1/rfqs/{rfq_id}/send", headers=manager)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "SENT"
    assert client.post(f"/api/v1/rfqs/{rfq_id}/send", headers=manager).status_code == 400

    quoted = client.post(
        f"/api/v1/rfqs/{rfq_id}/quotes",
        headers=manager,
        json={
            "supplier_id": supplier.id,
            "quote_date": date.today().isoformat(),
            "items": [
                {
                    "rfq_item_id": rfq_item_id,
                    "quoted_quantity": "2",
                    "unit_id": unit.id,
                    "unit_price": "12.50",
                }
            ],
        },
    )
    assert quoted.status_code == 200, quoted.text
    quote_id = db_session.scalar(select(SupplierQuote.id).where(SupplierQuote.rfq_id == rfq_id, SupplierQuote.supplier_id == supplier.id).order_by(SupplierQuote.id.desc()))
    assert quote_id is not None
    assert quoted.json()["status"] == "RESPONDING"
    # All API calls share one rollback-only test session; refresh relationships
    # that a prior request loaded before the quote existed.
    db_session.expire_all()

    compared = client.post(f"/api/v1/rfqs/{rfq_id}/comparison", headers=manager)
    assert compared.status_code == 200, compared.text
    comparison_id = compared.json()["id"]
    selected = client.post(
        f"/api/v1/rfqs/{rfq_id}/select-quote",
        headers=manager,
        json={"comparison_id": comparison_id, "quote_id": quote_id, "selection_reason": "唯一有效报价"},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["status"] == "CLOSED"

    created_order = client.post(
        "/api/v1/purchase-orders",
        headers=manager,
        json={"comparison_id": comparison_id, "quote_id": quote_id},
    )
    assert created_order.status_code == 201, created_order.text
    order = created_order.json()
    order_id = order["id"]
    assert order["status"] == "DRAFT"
    order_item = order["items"][0]

    submitted = client.post(f"/api/v1/purchase-orders/{order_id}/submit", headers=manager)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "APPROVING"
    approved = client.post(
        f"/api/v1/purchase-orders/{order_id}/approve",
        headers=manager,
        json={"opinion": "状态机测试审批"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    placed = client.post(f"/api/v1/purchase-orders/{order_id}/place", headers=manager)
    assert placed.status_code == 200, placed.text
    assert placed.json()["status"] == "ORDERED"

    registered = client.post(
        "/api/v1/deliveries",
        headers=warehouse,
        json={"po_id": order_id, "items": [{"po_item_id": order_item["id"], "planned_quantity": str(order_item["order_quantity"])}]},
    )
    assert registered.status_code == 201, registered.text
    delivery = registered.json()
    assert delivery["status"] == "IN_TRANSIT"
    delivery_item_id = delivery["items"][0]["id"]
    over_received = client.post(
        f"/api/v1/deliveries/{delivery['id']}/receive",
        headers=warehouse,
        json={
            "items": [
                {
                    "delivery_item_id": delivery_item_id,
                    "actual_quantity": str(Decimal(order_item["order_quantity"]) + Decimal("1")),
                    "short_quantity": "0",
                }
            ]
        },
    )
    assert over_received.status_code == 400
    unchanged_delivery = client.get(f"/api/v1/deliveries/{delivery['id']}", headers=warehouse)
    assert unchanged_delivery.status_code == 200
    assert unchanged_delivery.json()["status"] == "IN_TRANSIT"
    assert Decimal(unchanged_delivery.json()["items"][0]["actual_quantity"]) == 0
    received = client.post(
        f"/api/v1/deliveries/{delivery['id']}/receive",
        headers=warehouse,
        json={"items": [{"delivery_item_id": delivery_item_id, "actual_quantity": str(order_item["order_quantity"]), "short_quantity": "0"}]},
    )
    assert received.status_code == 200, received.text
    assert received.json()["status"] == "RECEIVED"
    assert client.post(
        f"/api/v1/deliveries/{delivery['id']}/receive",
        headers=warehouse,
        json={"items": [{"delivery_item_id": delivery_item_id, "actual_quantity": str(order_item["order_quantity"]), "short_quantity": "0"}]},
    ).status_code == 400

    acceptance_response = client.post(
        "/api/v1/quality-acceptances", headers=quality, json={"delivery_id": delivery["id"]}
    )
    assert acceptance_response.status_code == 201, acceptance_response.text
    acceptance = acceptance_response.json()
    assert acceptance["result"] == "PENDING"
    assert client.post(
        "/api/v1/quality-acceptances", headers=quality, json={"delivery_id": delivery["id"]}
    ).status_code == 400
    passed = client.post(
        f"/api/v1/quality-acceptances/{acceptance['id']}/result",
        headers=quality,
        json={"result": "PASSED", "certificate_complete": True, "conclusion": "符合要求"},
    )
    assert passed.status_code == 200, passed.text
    assert passed.json()["result"] == "PASSED"
    final_delivery = client.get(f"/api/v1/deliveries/{delivery['id']}", headers=warehouse)
    assert final_delivery.status_code == 200, final_delivery.text
    assert final_delivery.json()["status"] == "ACCEPTED"
    assert client.post(
        f"/api/v1/quality-acceptances/{acceptance['id']}/result",
        headers=quality,
        json={"result": "FAILED", "conclusion": "重复提交应被拒绝"},
    ).status_code == 400


def test_operation_exception_task_and_close_state_machine(
    client: TestClient, db_session, demo_password: str
) -> None:
    """验证异常、处理任务、处理记录和关闭说明的状态约束。"""

    admin_user = db_session.scalar(select(User).where(User.username == "system_admin"))
    manager_user = db_session.scalar(select(User).where(User.username == "procurement_manager"))
    assert admin_user is not None and manager_user is not None
    # 仅在当前回滚事务中设置测试口令，不修改本地演示账号。
    admin_user.password_hash = hash_password(demo_password)
    manager_user.password_hash = hash_password(demo_password)
    db_session.flush()
    manager = login(client, "procurement_manager", demo_password)
    admin = login(client, "system_admin", demo_password)
    created = client.post(
        "/api/v1/operation-exceptions",
        headers=manager,
        json={
            "exception_type": "OTHER",
            "source_type": "OTHER",
            "source_id": 987654321,
            "severity": "MEDIUM",
            "description": "状态机集成测试异常",
        },
    )
    assert created.status_code == 201, created.text
    exception = created.json()
    exception_id = exception["id"]
    assert exception["status"] == "OPEN"

    missing_note = client.patch(
        f"/api/v1/operation-exceptions/{exception_id}", headers=manager, json={"status": "CLOSED"}
    )
    assert missing_note.status_code == 400
    after_missing_note = client.get(f"/api/v1/operation-exceptions/{exception_id}", headers=manager)
    assert after_missing_note.status_code == 200
    assert after_missing_note.json()["status"] == "OPEN"

    task_response = client.post(
        f"/api/v1/operation-exceptions/{exception_id}/tasks",
        headers=manager,
        json={"title": "调查并处理测试异常", "priority": "HIGH"},
    )
    assert task_response.status_code == 201, task_response.text
    task = task_response.json()
    task_id = task["id"]
    assert task["status"] == "OPEN"
    processing = client.get(f"/api/v1/operation-exceptions/{exception_id}", headers=manager)
    assert processing.status_code == 200
    assert processing.json()["status"] == "PROCESSING"

    started = client.patch(
        f"/api/v1/operation-exceptions/{exception_id}/tasks/{task_id}",
        headers=manager,
        json={"status": "PROCESSING"},
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "PROCESSING"
    no_completion_note = client.patch(
        f"/api/v1/operation-exceptions/{exception_id}/tasks/{task_id}",
        headers=manager,
        json={"status": "COMPLETED"},
    )
    assert no_completion_note.status_code == 400
    task_list = client.get(f"/api/v1/operation-exceptions/{exception_id}/tasks", headers=manager)
    assert task_list.status_code == 200
    assert next(item for item in task_list.json()["items"] if item["id"] == task_id)["status"] == "PROCESSING"
    comment = client.post(
        f"/api/v1/operation-exceptions/{exception_id}/tasks/{task_id}/comments",
        headers=manager,
        json={"content": "已核实，未发现持续性影响"},
    )
    assert comment.status_code == 201, comment.text
    completed = client.patch(
        f"/api/v1/operation-exceptions/{exception_id}/tasks/{task_id}",
        headers=manager,
        json={"status": "COMPLETED", "completion_note": "已处理并复核"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "COMPLETED"

    closed = client.patch(
        f"/api/v1/operation-exceptions/{exception_id}",
        headers=manager,
        json={"status": "RESOLVED"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "RESOLVED"
    closed = client.patch(
        f"/api/v1/operation-exceptions/{exception_id}",
        headers=manager,
        json={"status": "CLOSED", "closing_note": "处置完成并归档"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"
    assert client.patch(
        f"/api/v1/operation-exceptions/{exception_id}", headers=manager, json={"status": "PROCESSING"}
    ).status_code == 400
    assert client.patch(
        f"/api/v1/operation-exceptions/{exception_id}", headers=admin, json={"status": "PROCESSING"}
    ).status_code == 400
    after_invalid_transitions = client.get(
        f"/api/v1/operation-exceptions/{exception_id}", headers=admin
    )
    assert after_invalid_transitions.status_code == 200
    assert after_invalid_transitions.json()["status"] == "CLOSED"


def test_role_permissions_separate_procurement_warehouse_quality_and_admin(
    client: TestClient, db_session, demo_password: str
) -> None:
    """确认只读财务角色不能写业务，仓库和质量角色权限边界明确。"""

    for username in (
        "finance_viewer", "warehouse_receiver", "quality_inspector",
        "procurement_manager", "system_admin",
    ):
        user = db_session.scalar(select(User).where(User.username == username))
        assert user is not None
        user.password_hash = hash_password(demo_password)
    db_session.flush()

    viewer = login(client, "finance_viewer", demo_password)
    warehouse = login(client, "warehouse_receiver", demo_password)
    quality = login(client, "quality_inspector", demo_password)
    manager = login(client, "procurement_manager", demo_password)

    assert client.get("/api/v1/rfqs", headers=viewer).status_code == 403
    assert client.post(
        "/api/v1/rfqs",
        headers=viewer,
        json={"items": [{"requested_name": "权限测试", "quantity": "1", "unit_id": 1}], "supplier_ids": [1]},
    ).status_code == 403
    assert client.get("/api/v1/operation-exceptions", headers=viewer).status_code == 200
    assert client.post(
        "/api/v1/operation-exceptions",
        headers=viewer,
        json={"exception_type": "OTHER", "source_type": "OTHER", "source_id": 987654322, "description": "禁止写入"},
    ).status_code == 403
    assert client.post(
        "/api/v1/quality-acceptances", headers=warehouse, json={"delivery_id": 987654321}
    ).status_code == 403
    assert client.post(
        "/api/v1/deliveries", headers=quality, json={"po_id": 987654321, "items": [{"po_item_id": 1, "planned_quantity": "1"}]}
    ).status_code == 403
    assert client.get("/api/v1/system/users", headers=manager).status_code == 403
    assert client.get("/api/v1/system/users", headers=login(client, "system_admin", demo_password)).status_code == 200


def test_buyer_can_read_but_cannot_update_product_master_data(
    client: TestClient, db_session, demo_password: str
) -> None:
    """采购员保留采购所需的产品读取权限，但不能修改产品主数据。"""

    product = db_session.scalar(select(Product).where(Product.status == "ACTIVE").order_by(Product.id))
    buyer_user = db_session.scalar(select(User).where(User.username == "buyer"))
    if product is None or buyer_user is None:
        pytest.skip("测试数据库需要采购员账号和至少一个启用的产品")
    # 登录只使用当前测试事务中的临时口令；测试结束后事务回滚，不改动演示账号口令。
    buyer_user.password_hash = hash_password(demo_password)
    db_session.flush()
    buyer = login(client, "buyer", demo_password)

    assert client.get("/api/v1/products", headers=buyer).status_code == 200
    assert client.get("/api/v1/suppliers", headers=buyer).status_code == 200
    denied = client.patch(
        f"/api/v1/products/{product.id}",
        headers=buyer,
        json={"model": "无权限修改"},
    )
    assert denied.status_code == 403
    assert client.patch(
        "/api/v1/suppliers/1",
        headers=buyer,
        json={"supplier_name": "无权限修改"},
    ).status_code == 403
    assert client.post(
        "/api/v1/purchase-orders/1/approve",
        headers=buyer,
        json={"opinion": "越权审批检查"},
    ).status_code == 403
    comparison = client.post("/api/v1/rfqs/1/comparison", headers=buyer)
    assert comparison.status_code != 403
    assert client.post(
        "/api/v1/rfqs/1/select-quote",
        headers=buyer,
        json={"comparison_id": 1, "quote_id": 1, "selection_reason": "越权定标测试"},
    ).status_code == 403
    assert client.post(
        "/api/v1/rfqs/1/select-quote",
        headers=buyer,
        json={"comparison_id": 1, "quote_id": 1, "selection_reason": "越权定标检查"},
    ).status_code == 403
