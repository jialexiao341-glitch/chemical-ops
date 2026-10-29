"""询价定标和报价提交必须共享锁并按最新状态判断。"""

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import mysql

from app.core.errors import BusinessValidationError
from app.modules.rfqs import service
from app.modules.supplier_portal import service as portal


def test_quote_submission_rechecks_locked_status():
    stale = SimpleNamespace(id=1, status='RESPONDING')
    closed = SimpleNamespace(id=1, status='CLOSED')
    calls = []
    db = SimpleNamespace(scalar=lambda statement: calls.append(statement) or closed)
    with pytest.raises(BusinessValidationError, match='不接受供应商报价'):
        service.create_quote_for_supplier(db, SimpleNamespace(id=7), stale, 1, object())
    assert 'FOR UPDATE' in str(calls[0].compile(dialect=mysql.dialect()))
    assert calls[0].get_execution_options()['populate_existing'] is True


def test_portal_locks_before_deadline_and_status_checks(monkeypatch):
    monkeypatch.setattr(portal, '_supplier_id', lambda *args: 5)
    seen = []
    def invited(db, supplier_id, rfq_id, *, for_update=False):
        seen.append(for_update)
        return SimpleNamespace(status='CLOSED'), object()
    monkeypatch.setattr(portal, '_invited_rfq', invited)
    with pytest.raises(BusinessValidationError, match='已关闭'):
        portal.submit_rfq_quote(object(), object(), 1, object())
    assert seen == [True]
