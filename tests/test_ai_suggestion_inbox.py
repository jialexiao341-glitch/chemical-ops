"""运营建议状态转换与幂等行为。"""
from types import SimpleNamespace
import pytest
from app.core.errors import BusinessValidationError
from app.modules.ai import proactive


def test_terminal_suggestion_cannot_be_changed(monkeypatch):
    suggestion = SimpleNamespace(status='IGNORED')
    monkeypatch.setattr(proactive, 'get_suggestion', lambda *args, **kwargs: suggestion)
    with pytest.raises(BusinessValidationError):
        proactive.transition_suggestion(SimpleNamespace(), SimpleNamespace(id=1), 1, 'CLOSED')


def test_invalid_transition_rejected():
    with pytest.raises(BusinessValidationError):
        proactive.transition_suggestion(SimpleNamespace(), SimpleNamespace(id=1), 1, 'INVALID')

@pytest.fixture
def suggestion_db(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from app.modules.operation_exceptions import service as exception_service
    from app.modules.system import audit
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE operation_exceptions (id INTEGER PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE ai_operation_suggestions (id INTEGER PRIMARY KEY, exception_id INTEGER UNIQUE NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, instruction TEXT NOT NULL, status TEXT NOT NULL, handled_by INTEGER, handled_at DATETIME, task_id INTEGER, created_at DATETIME NOT NULL)')
        connection.exec_driver_sql('INSERT INTO operation_exceptions VALUES (1), (2)')
    monkeypatch.setattr(exception_service, '_exception_record_scope_condition', lambda db, user: __import__('app.modules.operation_exceptions.model', fromlist=['OperationException']).OperationException.id == user.visible_exception)
    monkeypatch.setattr(audit, 'add_audit_log', lambda *args, **kwargs: None)
    monkeypatch.setattr(exception_service, 'get_exception_for_task_creation', lambda *args, **kwargs: None)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_deduplication_and_scope(suggestion_db, monkeypatch):
    from app.modules.ai.model import AIOperationSuggestion
    from sqlalchemy import func, select
    from app.core.errors import ResourceNotFoundError
    exception = SimpleNamespace(id=1, exception_type='LOW_STOCK', exception_no='EX-1', description='低库存', owner_id=None)
    notifications = []
    monkeypatch.setattr(proactive, 'notify_users', lambda *args, **kwargs: notifications.append(kwargs) or [])
    proactive.publish_exception_suggestion(suggestion_db, exception)
    proactive.publish_exception_suggestion(suggestion_db, exception)
    assert suggestion_db.scalar(select(func.count()).select_from(AIOperationSuggestion)) == 1
    assert len(notifications) == 1
    visible = SimpleNamespace(id=1, visible_exception=1)
    hidden = SimpleNamespace(id=2, visible_exception=2)
    assert proactive.list_suggestions(suggestion_db, visible, status=None, page=1, page_size=20)[1] == 1
    assert proactive.list_suggestions(suggestion_db, hidden, status=None, page=1, page_size=20)[1] == 0
    with pytest.raises(ResourceNotFoundError):
        proactive.get_suggestion(suggestion_db, hidden, 1)
    with pytest.raises(ResourceNotFoundError):
        proactive.transition_suggestion(suggestion_db, hidden, 1, 'IGNORED')


def test_handoff_creates_one_task_and_cannot_repeat(suggestion_db, monkeypatch):
    from app.modules.ai.model import AIOperationSuggestion
    from app.modules.operation_exceptions import service as exception_service
    item = AIOperationSuggestion(exception_id=1, title='运营建议', content='内容', instruction='核查异常 EX-1', status='OPEN')
    suggestion_db.add(item); suggestion_db.commit()
    calls = []
    def create_task(db, user, exception_id, data, *, commit):
        calls.append((exception_id, data.assignee_id, commit))
        return SimpleNamespace(id=42)
    monkeypatch.setattr(exception_service, 'create_task', create_task)
    user = SimpleNamespace(id=7, visible_exception=1)
    result = proactive.transition_suggestion(suggestion_db, user, item.id, 'HANDED_OFF')
    assert result.status == 'HANDED_OFF' and result.task_id == 42
    assert calls == [(1, 7, False)]
    with pytest.raises(BusinessValidationError):
        proactive.transition_suggestion(suggestion_db, user, item.id, 'HANDED_OFF')
    assert len(calls) == 1


@pytest.mark.parametrize('status', ['IGNORED', 'CLOSED'])
def test_ignore_and_close_change_only_suggestion(suggestion_db, status):
    from app.modules.ai.model import AIOperationSuggestion
    item = AIOperationSuggestion(exception_id=1, title='建议', content='内容', instruction='指令', status='OPEN')
    suggestion_db.add(item); suggestion_db.commit()
    result = proactive.transition_suggestion(suggestion_db, SimpleNamespace(id=7, visible_exception=1), item.id, status)
    assert result.status == status and result.task_id is None and result.handled_by == 7


def test_api_requires_both_read_and_write_and_uses_scope(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.auth import get_current_user
    from app.core.db import get_db
    from app.core.rate_limit import limit_ai
    from app.modules.system import crud
    from app.core.errors import ResourceNotFoundError
    user = SimpleNamespace(id=1)
    permissions = {'ai.workspace.read', 'operations.exceptions.read'}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[limit_ai] = lambda: None
    monkeypatch.setattr(crud, 'get_user_role_codes', lambda *args: [])
    monkeypatch.setattr(crud, 'get_user_permission_codes', lambda *args: list(permissions))
    monkeypatch.setattr(proactive, 'get_suggestion', lambda *args, **kwargs: (_ for _ in ()).throw(ResourceNotFoundError('不存在')))
    try:
        client = TestClient(app)
        assert client.get('/api/v1/ai/operation-suggestions/5').status_code == 404
        assert client.post('/api/v1/ai/operation-suggestions/5/ignore').status_code == 403
        permissions.add('operations.exceptions.write')
        assert client.post('/api/v1/ai/operation-suggestions/5/ignore').status_code == 404
        permissions.remove('operations.exceptions.read')
        assert client.post('/api/v1/ai/operation-suggestions/5/ignore').status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_mysql_api_suggestion_lifecycle(client, db_session, demo_password):
    from uuid import uuid4
    from sqlalchemy import select, func
    from app.modules.ai.model import AIOperationSuggestion
    from app.modules.operation_exceptions.model import OperationException, OperationTask
    from tests.conftest import login
    actor = login(client, 'system_admin', demo_password)
    token = uuid4().hex[:12]
    exceptions = [OperationException(exception_no=f'TEST-{token}-{i}', exception_type='LOW_STOCK',
                    source_type='PRODUCT', source_id=900000 + i, severity='HIGH',
                    description='验收低库存', status='OPEN') for i in range(2)]
    db_session.add_all(exceptions); db_session.flush()
    for exception in exceptions:
        proactive.publish_exception_suggestion(db_session, exception)
        proactive.publish_exception_suggestion(db_session, exception)
    suggestions = list(db_session.scalars(select(AIOperationSuggestion).where(AIOperationSuggestion.exception_id.in_([e.id for e in exceptions])).order_by(AIOperationSuggestion.id)).all())
    assert len(suggestions) == 2
    detail = client.get(f'/api/v1/ai/operation-suggestions/{suggestions[0].id}', headers=actor)
    assert detail.status_code == 200 and detail.json()['exception_no'] == exceptions[0].exception_no
    response = client.post(f'/api/v1/ai/operation-suggestions/{suggestions[0].id}/handoff', headers=actor)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'HANDED_OFF' and response.json()['task_id']
    assert db_session.scalar(select(func.count()).select_from(OperationTask).where(OperationTask.exception_id == exceptions[0].id)) == 1
    assert client.post(f'/api/v1/ai/operation-suggestions/{suggestions[0].id}/handoff', headers=actor).status_code == 400
    response = client.post(f'/api/v1/ai/operation-suggestions/{suggestions[1].id}/ignore', headers=actor)
    assert response.status_code == 200 and response.json()['status'] == 'IGNORED'
    listing = client.get('/api/v1/ai/operation-suggestions', params={'status': 'IGNORED'}, headers=actor)
    assert listing.status_code == 200 and suggestions[1].id in [x['id'] for x in listing.json()['items']]


def test_notification_response_hides_legacy_suggestion_content():
    from datetime import datetime
    from app.modules.notifications.controller import _safe_notification
    notification = SimpleNamespace(id=1, recipient_id=7, notification_type='OPERATION_SUGGESTION',
        title='运营建议：客户名称', content='异常 EX-SECRET', related_type='OPERATION_EXCEPTION',
        related_id=123, is_read=0, read_at=None, created_at=datetime.now())
    result = _safe_notification(notification)
    assert 'EX-SECRET' not in result.content and '客户名称' not in result.title
    assert result.related_id is None


def test_assignee_only_cannot_handle_shared_suggestion(suggestion_db, monkeypatch):
    from app.core.errors import ResourceNotFoundError
    from app.modules.ai.model import AIOperationSuggestion
    from app.modules.operation_exceptions import service as exception_service
    item = AIOperationSuggestion(exception_id=1, title='建议', content='内容', instruction='指令', status='OPEN')
    suggestion_db.add(item); suggestion_db.commit()
    def deny(*args, **kwargs):
        raise ResourceNotFoundError('无办理范围')
    monkeypatch.setattr(exception_service, 'get_exception_for_task_creation', deny)
    with pytest.raises(ResourceNotFoundError):
        proactive.transition_suggestion(suggestion_db, SimpleNamespace(id=7, visible_exception=1), item.id, 'CLOSED')
    assert item.status == 'OPEN'


def test_scan_reconciles_missing_active_suggestions(db_session, monkeypatch):
    from uuid import uuid4
    from sqlalchemy import select, func
    from app.modules.ai.model import AIOperationSuggestion
    from app.modules.jobs import service
    from app.modules.operation_exceptions.model import OperationException
    exception = OperationException(exception_no=f'TEST-{uuid4().hex[:12]}', exception_type='LOW_STOCK',
        source_type='PRODUCT', source_id=987654, severity='HIGH', description='补偿验收', status='OPEN')
    db_session.add(exception); db_session.flush()
    monkeypatch.setattr(service, 'scan_overdue_deliveries', lambda *a, **k: {'scanned_count': 0, 'created_count': 0})
    monkeypatch.setattr(service, 'scan_expiring_inventory', lambda *a, **k: {'scanned_count': 0, 'created_count': 0})
    monkeypatch.setattr(service, 'scan_pending_quality_acceptances', lambda *a, **k: {'scanned_count': 0, 'created_count': 0})
    monkeypatch.setattr(service, 'scan_low_inventory', lambda *a, **k: {'scanned_count': 0, 'created_count': 0, 'recovered_count': 0, 'skipped_unit_mismatch_count': 0})
    # 只测试本条记录，避免本地开发库中已有异常影响样本。
    from app.modules.ai import proactive
    monkeypatch.setattr(proactive, 'notify_users', lambda *a, **k: [])
    service.scan_active_alerts(db_session, SimpleNamespace(id=1))
    service.scan_active_alerts(db_session, SimpleNamespace(id=1))
    assert db_session.scalar(select(func.count()).select_from(AIOperationSuggestion).where(AIOperationSuggestion.exception_id == exception.id)) == 1
