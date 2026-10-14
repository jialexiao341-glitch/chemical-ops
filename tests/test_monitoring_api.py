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
