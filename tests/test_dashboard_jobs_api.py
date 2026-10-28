"""Dashboard 和逾期扫描接口测试。"""

import pytest
from fastapi.testclient import TestClient

from .conftest import login


pytestmark = pytest.mark.integration


def test_dashboard_overview_returns_core_metrics(client: TestClient, demo_password: str) -> None:
    """管理层账号可以查询规范的 Dashboard 指标。"""

    headers = login(client, "management_viewer", demo_password)
    response = client.get("/api/v1/dashboard/overview", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"purchase_orders_total", "purchase_orders_in_progress", "deliveries_overdue", "inventory_quantity", "inventory_units", "inventory_available", "open_exceptions", "confirmed_reconciliations", "paid_amount", "expiry_alerts"}
    assert body["inventory_available"] is True
    assert isinstance(body["inventory_units"], list)


def test_buyer_cannot_trigger_overdue_scan(client: TestClient, demo_password: str) -> None:
    """普通采购员不能触发后台逾期扫描任务。"""

    headers = login(client, "buyer", demo_password)
    response = client.post("/api/v1/jobs/overdue-scan", headers=headers)
    assert response.status_code == 403
    assert response.json()["message"] == "无权访问"


def test_dashboard_report_returns_sql_aggregates(client: TestClient, demo_password: str) -> None:
    """统计报表返回订单状态和供应商聚合结果。"""

    headers = login(client, "management_viewer", demo_password)
    response = client.get("/api/v1/dashboard/report?date_from=2020-01-01&date_to=2030-12-31", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date_from"] == "2020-01-01"
    assert body["date_to"] == "2030-12-31"
    assert isinstance(body["order_trend"], list)
    assert body["order_trend"]
    assert all({"date", "order_count", "order_amount"}.issubset(row) for row in body["order_trend"])
    assert isinstance(body["order_statuses"], list)
    assert isinstance(body["supplier_performance"], list)
    assert isinstance(body["inventory_costs"], list)
    assert isinstance(body["pending_tasks"], list)
    assert isinstance(body["inventory_alerts"], list)


def test_dashboard_report_rejects_invalid_date_range(client: TestClient, demo_password: str) -> None:
    """统计开始日期晚于结束日期时返回中文业务错误。"""

    headers = login(client, "management_viewer", demo_password)
    response = client.get("/api/v1/dashboard/report?date_from=2030-01-02&date_to=2030-01-01", headers=headers)
    assert response.status_code == 400
    assert "开始日期不能晚于结束日期" in response.json()["detail"]
