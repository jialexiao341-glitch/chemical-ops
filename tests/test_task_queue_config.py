"""Database queues are the default; in-process execution is an explicit fallback."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.production import production_config_errors


def settings(**values):
    return Settings(_env_file=None, **values)


def test_default_enables_database_queues_without_a_broker():
    config = settings()
    assert config.task_queue_enabled
    assert config.technical_document_execution_mode == config.agent_execution_mode == "database"


def test_transport_logs_redact_clear_and_encoded_credentials():
    import logging
    from app.modules.task_queue.logging import SecretFilter
    config = settings(mysql_password="test secret/@", jwt_secret_key="sql-password")
    record = logging.LogRecord("transport", logging.WARNING, __file__, 1,
        "connection test secret/@ test%20secret%2F%40 test+secret%2F%40 sql-password", (), None)
    assert SecretFilter(config).filter(record)
    assert "test" not in record.getMessage() and "sql-password" not in record.getMessage()


@pytest.mark.parametrize("mode", ["technical_document_execution_mode", "agent_execution_mode"])
def test_each_queue_can_fall_back_independently(mode):
    config = settings(**{mode: "in_process"})
    assert config.task_queue_enabled
    other = "agent_execution_mode" if mode.startswith("technical") else "technical_document_execution_mode"
    assert getattr(config, other) == "database"


@pytest.mark.parametrize("values", [
    {"agent_execution_mode": "unknown"},
    {"agent_execution_mode": "rabbitmq"},
    {"task_heartbeat_seconds": 30, "task_lease_seconds": 60},
    {"task_max_attempts": 0},
    {"task_poll_interval_seconds": 0},
])
def test_invalid_config_fails_without_exposing_secret(values):
    with pytest.raises(ValidationError):
        settings(**values)


def test_database_queue_needs_no_transport_credentials_in_production():
    config = settings(app_env="production", agent_execution_mode="database")
    assert not any("RABBITMQ" in error for error in production_config_errors(config))
