"""采购申请审批接口测试。"""

import pytest
from fastapi.testclient import TestClient

from .conftest import login


pytestmark = pytest.mark.integration


def test_legacy_submitted_request_can_be_approved(client: TestClient, demo_password: str) -> None:
    """兼容数据库中 SUBMITTED 状态的历史采购申请审批。"""

    manager = login(client, "procurement_manager", demo_password)
    listed = client.get(
        "/api/v1/purchase-requests?status=SUBMITTED&page=1&page_size=100",
        headers=manager,
    )
    assert listed.status_code == 200, listed.text
    submitted = listed.json()["items"]
    assert submitted, "测试数据库应包含至少一条 SUBMITTED 采购申请"

    response = client.post(
        f"/api/v1/purchase-requests/{submitted[0]['id']}/approve",
        headers=manager,
        json={"opinion": "审批通过"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "APPROVED"
