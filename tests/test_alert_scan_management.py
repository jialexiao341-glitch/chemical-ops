from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.core.config import Settings
from app.core.db import get_db
from app.modules.jobs import controller, service
from app.modules.system import crud


def test_alert_scheduler_defaults_enabled():
    assert Settings(_env_file=None).business_alerts_scheduler_enabled is True


def test_manual_scan_records_success_and_failure(monkeypatch):
    db = SimpleNamespace(rollback=Mock(), get=Mock())
    user = SimpleNamespace(id=1)
    run = SimpleNamespace(id=9)
    db.get.return_value = run
    monkeypatch.setattr(service, 'start_scheduled_run', Mock(return_value=run))
    update = Mock()
    monkeypatch.setattr(service, 'update_scheduled_run', update)
    monkeypatch.setattr(service, 'scan_active_alerts', lambda *_: {'quote_expiry_created_count': 2})
    assert service.run_manual_alert_scan(db, user) == {'quote_expiry_created_count': 2}
    assert update.call_args.kwargs['result'] == {'quote_expiry_created_count': 2}
    def fail(*_):
        raise ValueError('sensitive information')
    monkeypatch.setattr(service, 'scan_active_alerts', fail)
    with pytest.raises(ValueError):
        service.run_manual_alert_scan(db, user)
    assert db.rollback.called and update.call_args.kwargs['error_type'] == 'ValueError'


def test_alert_management_api_requires_permissions(client, monkeypatch):
    from app.main import app
    user = SimpleNamespace(id=1)
    permissions = {'operations.exceptions.read'}
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(crud, 'get_user_role_codes', lambda *_: [])
    monkeypatch.setattr(crud, 'get_user_permission_codes', lambda *_: list(permissions))
    monkeypatch.setattr(service, 'latest_alert_run', lambda db: None)
    monkeypatch.setattr(service, 'run_manual_alert_scan', lambda db, user: {'quote_expiry_created_count': 1})
    try:
        status = client.get('/api/v1/jobs/alert-scan/status')
        assert status.status_code == 200
        assert client.post('/api/v1/jobs/alert-scan').status_code == 403
        permissions.add('operations.exceptions.write')
        assert client.post('/api/v1/jobs/alert-scan').json()['quote_expiry_created_count'] == 1
        permissions.clear()
        assert client.get('/api/v1/jobs/alert-scan/status').status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_manual_scan_persists_latest_run(db_session, monkeypatch):
    from sqlalchemy import select
    from app.modules.system.model import User
    user = db_session.scalar(select(User).where(User.username == 'system_admin'))
    monkeypatch.setattr(service, 'scan_active_alerts', lambda *_: {'quote_expiry_created_count': 2})
    service.run_manual_alert_scan(db_session, user)
    run = service.latest_alert_run(db_session)
    assert run.status == 'SUCCEEDED' and run.attempt_count == 1
    assert run.result_json == {'quote_expiry_created_count': 2}
