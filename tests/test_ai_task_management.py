"""本人任务分页、授权导出与版本化草稿修改。"""
import csv
import io
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.errors import AuthorizationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.ai import agent_runtime, purchase_draft_confirmations as confirmations
from app.modules.ai.model import AIAgentTask, AIPurchaseDraftConfirmation
from app.modules.ai.lifecycle import cleanup_expired_ai_records
from app.modules.task_queue.model import TaskExecution
from app.modules.ai.schema import AIPurchaseDraftPatch
from app.modules.purchase_requests.model import Unit
from app.modules.system.model import User


def test_task_list_is_owner_scoped_and_paged(db_session, monkeypatch):
    # 独立身份避免把开发库中已有 FAILED 任务计入固定分页预期。
    user, foreign = [User(username=f'task-page-{uuid4().hex[:12]}', display_name='任务分页测试',
                          password_hash='unused-test-account') for _ in range(2)]
    db_session.add_all([user, foreign])
    db_session.flush()
    monkeypatch.setattr(agent_runtime, '_check_trace_access', lambda *_: [])
    for owner, count in ((user, 3), (foreign, 1)):
        for _ in range(count):
            db_session.add(AIAgentTask(id=uuid4().hex, user_id=owner.id, status='FAILED', revision=1,
                payload={'messages': ['test'], 'trace': []}, reply='done', created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
    db_session.flush()
    page = agent_runtime.list_tasks(db_session, user, page=1, page_size=2, status='FAILED')
    assert page.total == 3 and len(page.items) == 2
    assert all(db_session.get(AIAgentTask, row.id).user_id == user.id for row in page.items)
    assert len(agent_runtime.list_tasks(db_session, user, page=2, page_size=2, status='FAILED').items) == 1


def test_export_rechecks_scope_and_escapes_formulas(db_session, monkeypatch):
    user = db_session.scalar(select(User).where(User.username == 'system_admin'))
    task = AIAgentTask(id=uuid4().hex, user_id=user.id, status='SUCCEEDED', revision=1,
        payload={'messages': [], 'trace': [{'step': 1, 'action': 'call_tool', 'tool': 'catalog.search_products',
            'status': 'FAILED', 'arguments': {'keyword': '试剂'}, 'result': '=HYPERLINK("https://example.invalid")'}]},
        reply='', created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db_session.add(task); db_session.flush()
    monkeypatch.setattr(agent_runtime, '_check_trace_access', lambda *_: [])
    content = agent_runtime.export_task_csv(db_session, user, task.id)
    rows = list(csv.reader(io.StringIO(content.lstrip('\ufeff'))))
    assert rows[1][-1].startswith("'=")
    monkeypatch.setattr(agent_runtime, '_check_trace_access', lambda *_: (_ for _ in ()).throw(AuthorizationError('revoked')))
    with pytest.raises(AuthorizationError):
        agent_runtime.export_task_csv(db_session, user, task.id)
    with pytest.raises(ResourceNotFoundError):
        agent_runtime.export_task_csv(db_session, db_session.scalar(select(User).where(User.username == 'buyer')), task.id)


def test_patch_draft_refreshes_hash_and_requires_new_confirmation(db_session):
    user = db_session.scalar(select(User).where(User.username == 'system_admin'))
    unit = db_session.scalar(select(Unit).where(Unit.status == 'ACTIVE'))
    payload = {'department_id': user.department_id, 'purpose': '旧用途', 'priority': 'NORMAL',
        'currency_code': 'CNY', 'items': [{'requested_name': '试剂', 'quantity': '2', 'unit_id': unit.id}]}
    confirmation = AIPurchaseDraftConfirmation(confirmation_id=uuid4().hex, user_id=user.id, preview_version=1,
        request_hash=confirmations._hash(payload), draft_payload=payload,
        object_versions={'actor_department_id': user.department_id, 'products': {},
                         'units': {str(unit.id): {'unit_name': unit.unit_name, 'dimension': unit.dimension}}},
        evidence=[], status='PENDING', expires_at=datetime.utcnow()+timedelta(minutes=5))
    db_session.add(confirmation); db_session.flush()
    updated = confirmations.patch_purchase_draft(db_session, user, AIPurchaseDraftPatch(
        confirmation_id=confirmation.confirmation_id, preview_version=1, changes={'purpose': '新用途'}))
    assert updated.preview_version == 2 and updated.requires_user_confirmation
    assert confirmation.draft_payload['purpose'] == '新用途'
    assert confirmation.request_hash == confirmations._hash(confirmation.draft_payload)
    with pytest.raises(DuplicateResourceError):
        confirmations.patch_purchase_draft(db_session, user, AIPurchaseDraftPatch(
            confirmation_id=confirmation.confirmation_id, preview_version=1, changes={'purpose': '过期编辑'}))
    with pytest.raises(Exception, match='不允许'):
        confirmations.patch_purchase_draft(db_session, user, AIPurchaseDraftPatch(
            confirmation_id=confirmation.confirmation_id, preview_version=2,
            changes={'department_id': 999, 'purpose': '越权'}))


def test_retention_marks_expired_previews_and_purges_only_old_terminal_tasks(db_session):
    now = datetime(2026, 10, 21)
    user = db_session.scalar(select(User).where(User.username == 'system_admin'))
    old_id, live_id = uuid4().hex, uuid4().hex
    old_task = AIAgentTask(id=old_id, user_id=user.id, status='SUCCEEDED', revision=2,
        payload={'trace': [{'private': 'expired'}]}, reply='expired', created_at=now-timedelta(days=40),
        updated_at=now-timedelta(days=40))
    live_task = AIAgentTask(id=live_id, user_id=user.id, status='RUNNING', revision=1,
        payload={'trace': []}, reply='', created_at=now-timedelta(days=40), updated_at=now-timedelta(days=40))
    preview = AIPurchaseDraftConfirmation(confirmation_id=uuid4().hex, user_id=user.id, preview_version=1,
        request_hash='a'*64, draft_payload={}, object_versions={}, evidence=[], status='PENDING',
        expires_at=now-timedelta(seconds=1))
    execution = TaskExecution(id=uuid4().hex, task_type='agent.run', business_id=old_id, actor_id=user.id,
        run_generation=1, business_revision=2, payload={'secret': 'expired'}, checkpoint={'secret': 'expired'},
        status='SUCCEEDED', fencing_token=1, created_at=now-timedelta(days=40), updated_at=now-timedelta(days=40))
    db_session.add_all([old_task, live_task, preview, execution]); db_session.flush()
    result = cleanup_expired_ai_records(db_session, now=now)
    assert result == {'expired_confirmations': 1, 'purged_tasks': 1}
    assert db_session.get(AIAgentTask, old_id) is None
    assert db_session.get(AIAgentTask, live_id) is not None
    assert db_session.get(TaskExecution, execution.id) is None
    assert db_session.get(AIPurchaseDraftConfirmation, preview.id).status == 'EXPIRED'
