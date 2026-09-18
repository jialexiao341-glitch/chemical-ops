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
