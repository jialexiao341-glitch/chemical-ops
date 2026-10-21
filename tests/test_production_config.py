"""生产配置启动门禁的快速校验测试。"""

import pytest

from app.core.config import Settings
from app.core import production


def _valid_production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "debug": False,
        "jwt_secret_key": "secure-production-key-0123456789-abcdef",
        "mysql_host": "mysql.internal",
        "mysql_database": "chemicalops",
        "mysql_user": "chemicalops_app",
        "mysql_password": "non-placeholder-db-password",
        "file_storage_backend": "local",
        "file_scan_enabled": True,
        "file_scan_command": "clamdscan",
        "idempotency_required": True,
        "redis_enabled": True,
        "redis_rate_limit_enabled": True,
        "minio_secure": True,
        "metrics_access_token": "test-metrics-token-0123456789-abcdef",
        "agent_enabled": False,
        "agent_allow_write_tools": False,
        "demo_default_password": "",
        "admin_password": "strong-admin-password-2026",
        "cors_origins": "https://ops.example.com",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_config_accepts_valid_runtime_settings(monkeypatch) -> None:
    monkeypatch.setattr(production.shutil, "which", lambda _: "/usr/bin/clamdscan")

    assert production.production_config_errors(_valid_production_settings()) == []


def test_production_config_rejects_insecure_runtime_settings(monkeypatch) -> None:
    monkeypatch.setattr(production.shutil, "which", lambda _: None)
    settings = _valid_production_settings(
        debug=True,
        jwt_secret_key="CHANGE_ME",
        mysql_password="password",
        file_scan_command="missing-scanner",
        idempotency_required=False,
        agent_allow_write_tools=True,
        demo_default_password="demo-password",
        cors_origins="*",
    )

    errors = production.production_config_errors(settings)

    assert "DEBUG 必须为 false" in errors
    assert any("JWT_SECRET_KEY" in error for error in errors)
    assert any("MYSQL_PASSWORD" in error for error in errors)
    assert any("扫描程序" in error for error in errors)
    assert any("IDEMPOTENCY_REQUIRED" in error for error in errors)
    assert any("AI 直接写工具" in error for error in errors)
    assert any("DEMO_DEFAULT_PASSWORD" in error for error in errors)
    assert any("CORS_ORIGINS" in error for error in errors)
    assert all("secure-production-key" not in error for error in errors)


@pytest.mark.parametrize("environment", ["development", "test", "ci"])
def test_production_config_does_not_restrict_non_production(environment: str) -> None:
    settings = Settings(app_env=environment, debug=True, jwt_secret_key="CHANGE_ME")

    assert production.production_config_errors(settings) == []


@pytest.mark.parametrize("overrides,field", [
    ({"redis_enabled": False, "redis_rate_limit_enabled": False}, "REDIS_ENABLED"),
    ({"redis_rate_limit_enabled": False}, "REDIS_RATE_LIMIT_ENABLED"),
    ({"file_storage_backend": "minio", "minio_secure": False}, "MINIO_SECURE"),
    ({"metrics_access_token": ""}, "METRICS_ACCESS_TOKEN"),
])
def test_production_requires_shared_limits_tls_and_metrics_credential(monkeypatch, overrides, field):
    monkeypatch.setattr(production.shutil, "which", lambda _: "/usr/bin/clamdscan")
    assert any(field in message for message in production.production_config_errors(_valid_production_settings(**overrides)))
