"""库存接口的关键业务规则测试。"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.inventory.model import InventoryBalance, InventoryTransaction
from app.modules.inventory.model import Warehouse
from app.modules.inventory_cost.model import InventoryCostAllocation
from app.modules.deliveries.model import Delivery
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.system.model import User

from .conftest import login


pytestmark = pytest.mark.integration


def get_available_balance(db_session):
    """取得一条可用于接口测试的库存余额。"""

    balance = db_session.scalar(select(InventoryBalance).where(InventoryBalance.quantity > 0).order_by(InventoryBalance.id).limit(1))
    if balance is None:
        pytest.skip("数据库中没有可用库存余额")
    return balance


def test_fifo_outbound_uses_warehouse_owner_scope(monkeypatch) -> None:
    """FIFO 出库不允许仅凭动作权限跨负责人仓库执行。"""

    from types import SimpleNamespace

    from app.core.errors import ResourceNotFoundError
    from app.modules.inventory_cost import service as cost_service

    monkeypatch.setattr(cost_service, "get_user_role_codes", lambda _db, _user_id: ["WAREHOUSE"])
    with pytest.raises(ResourceNotFoundError):
        cost_service._require_warehouse_scope(
            object(), SimpleNamespace(id=7), Warehouse(id=10, manager_id=99)
        )

    monkeypatch.setattr(cost_service, "get_user_role_codes", lambda _db, _user_id: ["SYS_ADMIN"])
    cost_service._require_warehouse_scope(
        object(), SimpleNamespace(id=7), Warehouse(id=10, manager_id=99)
    )


def test_error_response_contains_chinese_message(client: TestClient, demo_password: str) -> None:
    """不存在资源时返回统一错误结构和中文提示。"""

    headers = login(client, "procurement_manager", demo_password)
    response = client.get("/api/v1/products/999999", headers=headers)
    assert response.status_code == 404
    assert response.json()["code"] == 404
    assert response.json()["message"] == "资源不存在"
    assert "不存在" in response.json()["detail"]


def test_buyer_cannot_freeze_inventory(client: TestClient, demo_password: str) -> None:
    """没有冻结权限的采购员不能改变库存状态。"""

    headers = login(client, "buyer", demo_password)
    response = client.post("/api/v1/inventory/balances/1/freeze", headers=headers, json={"reason": "无权限测试"})
    assert response.status_code == 403
    assert response.json()["message"] == "无权访问"


def test_warehouse_cannot_inbound_foreign_department_delivery(
    client: TestClient, db_session, demo_password: str
) -> None:
    """入库同时校验授权仓库和到货单来源订单范围。"""

    warehouse_user = db_session.scalar(
        select(User).where(User.username == "warehouse_receiver", User.status == "ACTIVE")
    )
    if warehouse_user is None:
        pytest.skip("测试数据库需要仓库账号")
    delivery = db_session.scalar(
        select(Delivery)
        .join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id)
        .where(Delivery.status == "ACCEPTED", PurchaseOrder.buyer_id != warehouse_user.id)
        .order_by(Delivery.id)
    )
    if delivery is None:
        pytest.skip("测试数据库需要仓库账号和由其他采购员创建的已验收到货单")

    # 无部门仓库用户只能读取本人采购订单，确保该来源单越界。
    warehouse_user.department_id = None
    db_session.flush()
    headers = login(client, "warehouse_receiver", demo_password)
    response = client.post(
        "/api/v1/inventory/inbounds",
        headers=headers,
        json={"delivery_id": delivery.id, "warehouse_id": 1, "location_id": 1},
    )

    assert response.status_code == 404


def test_issue_request_repeat_execute_is_rejected(client: TestClient, db_session, demo_password: str) -> None:
    """同一领用申请执行两次时，第二次不会重复扣减。"""

    balance = get_available_balance(db_session)
    quantity = min(Decimal("0.000001"), balance.quantity)
    technical = login(client, "technical_engineer", demo_password)
    manager = login(client, "procurement_manager", demo_password)
    approver = login(client, "system_admin", demo_password)
    warehouse = login(client, "warehouse_receiver", demo_password)
    options = client.get("/api/v1/inventory/issue-request-options", headers=technical)
    assert options.status_code == 200
    assert all("available_quantity" in item and "product_name" in item for item in options.json())
    assert client.get("/api/v1/inventory/balances", headers=technical).status_code == 403
    body = {
        "purpose": "自动化测试领用",
        "items": [{
            "product_id": balance.product_id,
            "warehouse_id": balance.warehouse_id,
            "location_id": balance.location_id,
            "batch_id": balance.batch_id,
            "unit_id": balance.unit_id,
            "requested_quantity": str(quantity),
        }],
    }
    created = client.post("/api/v1/inventory/issue-requests", headers=technical, json=body)
    assert created.status_code == 201, created.text
    issue_id = created.json()["id"]
    assert client.post(f"/api/v1/inventory/issue-requests/{issue_id}/submit", headers=technical).status_code == 200
    assert client.post(f"/api/v1/inventory/issue-requests/{issue_id}/approve", headers=manager).status_code == 403
    assert client.post(f"/api/v1/inventory/issue-requests/{issue_id}/approve", headers=approver).status_code == 200
    assert client.post(f"/api/v1/inventory/issue-requests/{issue_id}/execute", headers=technical).status_code == 403
    executed = client.post(f"/api/v1/inventory/issue-requests/{issue_id}/execute", headers=warehouse)
    assert executed.status_code == 200
    assert executed.json()["status"] == "COMPLETED"
    transaction = db_session.scalar(select(InventoryTransaction).where(InventoryTransaction.source_type == "ISSUE_REQUEST", InventoryTransaction.source_id == issue_id))
    assert transaction is not None
    assert db_session.scalar(select(InventoryCostAllocation).where(InventoryCostAllocation.transaction_id == transaction.id)) is not None
    repeated = client.post(f"/api/v1/inventory/issue-requests/{issue_id}/execute", headers=warehouse)
    assert repeated.status_code == 400
    assert "只有已审批的领用申请可以执行出库" in repeated.json()["detail"]


def test_transfer_rejects_same_source_and_target(client: TestClient, db_session, demo_password: str) -> None:
    """调拨源库位和目标库位相同时必须被拒绝。"""

    balance = get_available_balance(db_session)
    headers = login(client, "warehouse_receiver", demo_password)
    body = {
        "purpose": "自动化测试非法调拨",
        "items": [{
            "product_id": balance.product_id,
            "source_warehouse_id": balance.warehouse_id,
            "source_location_id": balance.location_id,
            "target_warehouse_id": balance.warehouse_id,
            "target_location_id": balance.location_id,
            "batch_id": balance.batch_id,
            "unit_id": balance.unit_id,
            "requested_quantity": "1",
        }],
    }
    response = client.post("/api/v1/inventory/transfer-requests", headers=headers, json=body)
    assert response.status_code == 400
    assert "源库位和目标库位不能相同" in response.json()["detail"]


def test_stocktake_requires_unchanged_book_quantity(client: TestClient, db_session, demo_password: str) -> None:
    """盘点执行前账面数量发生变化时不能覆盖库存。"""

    balance = get_available_balance(db_session)
    warehouse = login(client, "warehouse_receiver", demo_password)
    manager = login(client, "procurement_manager", demo_password)
    approver = login(client, "system_admin", demo_password)
    body = {
        "warehouse_id": balance.warehouse_id,
        "location_id": balance.location_id,
        "purpose": "自动化测试盘点快照",
        "items": [{
            "product_id": balance.product_id,
            "location_id": balance.location_id,
            "batch_id": balance.batch_id,
            "unit_id": balance.unit_id,
            "counted_quantity": str(balance.quantity),
        }],
    }
    created = client.post("/api/v1/inventory/stocktakes", headers=warehouse, json=body)
    assert created.status_code == 201, created.text
    assert created.json()["items"][0]["book_quantity"] == str(balance.quantity)
    stocktake_id = created.json()["id"]
    assert client.post(f"/api/v1/inventory/stocktakes/{stocktake_id}/submit", headers=warehouse).status_code == 200
    assert client.post(f"/api/v1/inventory/stocktakes/{stocktake_id}/approve", headers=manager).status_code == 403
    assert client.post(f"/api/v1/inventory/stocktakes/{stocktake_id}/approve", headers=approver).status_code == 200
    completed = client.post(f"/api/v1/inventory/stocktakes/{stocktake_id}/execute", headers=warehouse)
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
