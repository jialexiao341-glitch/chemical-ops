from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.modules.ai.model import AIOperationSuggestion
from app.modules.jobs import service
from app.modules.operation_exceptions.model import OperationException
from app.modules.rfqs.model import RFQ, SupplierQuote
from app.modules.suppliers.model import Supplier
from app.modules.system.model import User


def test_expired_latest_quotes_generate_one_actionable_suggestion(db_session):
    db = db_session
    actor = db.scalar(select(User).where(User.username == 'system_admin'))
    supplier = db.scalar(select(Supplier).limit(1))
    token = uuid4().hex[:12]
    active = RFQ(rfq_no=f'T-{token}', requester_id=actor.id, status='SENT')
    closed = RFQ(rfq_no=f'C-{token}', requester_id=actor.id, status='CLOSED')
    db.add_all([active, closed]); db.flush()
    yesterday = date.today() - timedelta(days=1)
    quotes = [
        SupplierQuote(quote_no=f'A-{token}', rfq_id=active.id, supplier_id=supplier.id, quote_version=1, quote_date=yesterday, valid_until=yesterday, status='SUBMITTED'),
        SupplierQuote(quote_no=f'B-{token}', rfq_id=closed.id, supplier_id=supplier.id, quote_version=1, quote_date=yesterday, valid_until=yesterday, status='SUBMITTED'),
    ]
    db.add_all(quotes); db.flush()
    service.scan_expired_quotes(db, actor)
    exception = db.scalar(select(OperationException).where(OperationException.source_type == 'SUPPLIER_QUOTE', OperationException.source_id == quotes[0].id))
    assert exception is not None
    suggestion = db.scalar(select(AIOperationSuggestion).where(AIOperationSuggestion.exception_id == exception.id))
    assert suggestion and quotes[0].quote_no in suggestion.content and active.rfq_no in suggestion.content and supplier.supplier_name in suggestion.content
    assert db.scalar(select(OperationException).where(OperationException.source_type == 'SUPPLIER_QUOTE', OperationException.source_id == quotes[1].id)) is None
    service.scan_expired_quotes(db, actor)
    assert len(db.scalars(select(OperationException).where(OperationException.source_type == 'SUPPLIER_QUOTE', OperationException.source_id == quotes[0].id)).all()) == 1
    from app.modules.ai import proactive
    from app.modules.operation_exceptions.model import OperationTask
    suggestion = proactive.transition_suggestion(db, actor, suggestion.id, 'HANDED_OFF')
    assert suggestion.status == 'HANDED_OFF'
    task = db.get(OperationTask, suggestion.task_id)
    assert task and task.exception_id == exception.id and task.assignee_id == actor.id
    exception.status = 'CLOSED'; db.flush()
    service.scan_expired_quotes(db, actor)
    assert len(db.scalars(select(OperationException).where(OperationException.source_type == 'SUPPLIER_QUOTE', OperationException.source_id == quotes[0].id)).all()) == 1


def test_scan_ignores_superseded_current_and_missing_expiry(db_session):
    db = db_session
    actor = db.scalar(select(User).where(User.username == 'system_admin'))
    supplier = db.scalar(select(Supplier).limit(1))
    token = uuid4().hex[:10]
    rfqs = [RFQ(rfq_no=f'Q{i}-{token}', requester_id=actor.id, status='RESPONDING') for i in range(3)]
    db.add_all(rfqs); db.flush()
    quotes = [
        SupplierQuote(quote_no=f'QO{i}-{token}', rfq_id=rfq.id, supplier_id=supplier.id,
                      quote_version=1, quote_date=date.today(), valid_until=expiry, status='SUBMITTED')
        for i, (rfq, expiry) in enumerate(zip(rfqs, [date.today() - timedelta(days=1), date.today(), None]))
    ]
    db.add_all(quotes); db.flush()
    db.add(SupplierQuote(quote_no=f'NEW-{token}', rfq_id=rfqs[0].id, supplier_id=supplier.id,
                         quote_version=2, quote_date=date.today(), valid_until=date.today() + timedelta(days=1), status='SUBMITTED'))
    db.flush()
    service.scan_expired_quotes(db, actor)
    assert not db.scalars(select(OperationException).where(
        OperationException.source_type == 'SUPPLIER_QUOTE',
        OperationException.source_id.in_([quote.id for quote in quotes]),
    )).all()


def test_quote_exception_requires_current_rfq_scope(db_session, monkeypatch):
    from app.modules.operation_exceptions import service as exception_service
    db = db_session
    actor = db.scalar(select(User).where(User.username == 'system_admin'))
    supplier = db.scalar(select(Supplier).limit(1))
    token = uuid4().hex[:10]
    rfq = RFQ(rfq_no=f'P-{token}', requester_id=actor.id, status='SENT')
    db.add(rfq); db.flush()
    quote = SupplierQuote(quote_no=f'PQ-{token}', rfq_id=rfq.id, supplier_id=supplier.id,
                          quote_version=1, quote_date=date.today(), valid_until=date.today()-timedelta(days=1), status='SUBMITTED')
    db.add(quote); db.flush()
    exc = OperationException(exception_no=f'PE-{token}', exception_type='QUOTE_EXPIRED',
                             source_type='SUPPLIER_QUOTE', source_id=quote.id,
                             owner_id=actor.id, severity='MEDIUM', description='报价过期', status='OPEN')
    db.add(exc); db.flush()
    monkeypatch.setattr(exception_service, 'get_user_role_codes', lambda *args: [])
    monkeypatch.setattr(exception_service, 'get_user_permission_codes', lambda *args: ['procurement.rfqs.read'])
    assert exception_service._has_exception_scope(db, actor, exc)
    monkeypatch.setattr(exception_service, 'get_user_permission_codes', lambda *args: [])
    assert not exception_service._has_exception_scope(db, actor, exc)
    monkeypatch.setattr(exception_service, 'get_user_permission_codes', lambda *args: ['procurement.rfqs.read'])
    from types import SimpleNamespace
    assert not exception_service._has_exception_scope(db, SimpleNamespace(id=-1, department_id=None), exc)
