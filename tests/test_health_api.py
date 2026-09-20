"""服务状态接口测试。"""

from fastapi.testclient import TestClient


def test_health_exposes_data_environment(client: TestClient) -> None:
    """前端需要知道当前连接的是数据库及其运行环境。"""

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data_source"] == "database"
    assert payload["data_mode"] in {"demo", "production"}
    assert payload["environment"]
    assert response.headers["x-request-id"]
    assert response.headers["x-trace-id"]


def test_health_preserves_incoming_trace_headers(client: TestClient) -> None:
    """网关提供的链路 ID 应贯穿后端响应，方便前端错误关联日志。"""

    response = client.get("/health", headers={"X-Request-ID": "req-test-123", "X-Trace-ID": "trace-test-456"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-test-123"
    assert response.headers["x-trace-id"] == "trace-test-456"


def test_metrics_endpoint_exposes_api_counter(client: TestClient) -> None:
    """指标端点至少包含 HTTP 请求计数。"""

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "chemicalops_api_requests_count" in response.text
