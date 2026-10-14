"""管理员运行监控 API 的数据裁剪与权限测试。"""

import pytest

from app.core.errors import AuthorizationError
from app.modules.monitoring import controller
from app.modules.system.model import User


def _admin() -> User:
    return User(
        id=7,
        username="monitor_admin",
        password_hash="unused",
        display_name="监控管理员",
        status="ACTIVE",
    )


def test_monitoring_overview_maps_alerts_targets_and_rules():
    result = controller._build_monitoring_overview(
        alerts_data={"alerts": [
            {"labels": {"alertname": "QueueFailed", "severity": "critical"},
             "annotations": {"summary": "失败任务持续存在"}, "state": "firing", "activeAt": "2026-10-14T02:00:00Z"},
            {"labels": {"alertname": "QueuePending"}, "annotations": {}, "state": "pending"},
            {"labels": {"alertname": "Inactive"}, "annotations": {}, "state": "inactive"},
        ]},
        targets_data={"activeTargets": [
            {"labels": {"job": "chemicalops-api", "instance": "localhost:8888"}, "health": "up", "lastScrape": "2026-10-14T02:00:00Z", "lastError": ""},
            {"labels": {"job": "database", "instance": "localhost:9104"}, "health": "down", "lastError": "connection refused"},
        ]},
        rules_data={"groups": [{"rules": [
            {"type": "alerting", "name": "QueueFailed", "state": "firing", "health": "ok"},
            {"type": "recording", "name": "api:requests:rate5m", "state": "inactive", "health": "ok"},
        ]}]},
    )

    assert result.firing_alerts == 1
    assert result.pending_alerts == 1
    assert result.healthy_targets == 1
    assert result.target_count == 2
    assert result.rule_count == 1
    assert [alert.name for alert in result.alerts] == ["QueueFailed", "QueuePending"]
    assert result.targets[1].health == "down"
    assert result.alerts[0].id


def test_monitoring_overview_rejects_non_admin(monkeypatch):
    monkeypatch.setattr(controller.crud, "get_user_role_codes", lambda db, user_id: ["PROCUREMENT"])
    with pytest.raises(AuthorizationError):
        controller._require_admin(object(), _admin())


@pytest.mark.parametrize("username,expected", [("system_admin", 200), ("buyer", 403), ("warehouse_receiver", 403)])
def test_monitoring_authenticated_http_boundary(client, demo_password, monkeypatch, username, expected):
    """真实登录和数据库 RBAC，仅 Prometheus 网络响应使用替身。"""
    from tests.conftest import login

    calls = []

    async def data(http, base_url, path):
        calls.append(path)
        return {"alerts": [], "activeTargets": [], "groups": []}

    monkeypatch.setattr(controller, "_prometheus_data", data)
    headers = login(client, username, demo_password)
    response = client.get("/api/v1/system/monitoring/overview", headers=headers)
    assert response.status_code == expected
    if expected == 200:
        assert sorted(calls) == ["alerts", "rules", "targets"]
        assert response.json()["rule_count"] == 0
    else:
        assert calls == []  # 普通用户被拒绝后不得访问监控服务。


def test_monitoring_anonymous_http_boundary(client, monkeypatch):
    async def unexpected(*args):
        pytest.fail("未登录请求不得访问 Prometheus")

    monkeypatch.setattr(controller, "_prometheus_data", unexpected)
    assert client.get("/api/v1/system/monitoring/overview").status_code == 401
