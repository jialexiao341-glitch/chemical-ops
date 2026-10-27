from types import SimpleNamespace
from sqlalchemy import select
from app.modules.ai.model import AIOperationSuggestion
from app.modules.finance.model import FinanceInvoice, FinanceInvoiceMatch, FinanceReconciliation
from app.modules.jobs import service
from app.modules.operation_exceptions.model import OperationException
from app.modules.system.model import User


def test_submitted_invoice_with_stale_match_generates_deduplicated_suggestion(db_session):
    db = db_session
    actor = db.scalar(select(User).where(User.username == 'system_admin'))
    row = db.execute(select(FinanceInvoice, FinanceInvoiceMatch, FinanceReconciliation)
        .join(FinanceReconciliation, FinanceReconciliation.id == FinanceInvoice.reconciliation_id)
        .join(FinanceInvoiceMatch, FinanceInvoiceMatch.invoice_id == FinanceInvoice.id)
        .where(FinanceInvoice.status == 'SUBMITTED', FinanceReconciliation.items_version > 0)
        .order_by(FinanceInvoice.id, FinanceInvoiceMatch.version_no.desc())).first()
    assert row is not None
    invoice, match, rec = row
    match.source_hash = 'stale-test'
    db.flush()
    service.scan_invoice_differences(db, actor)
    exception = db.scalar(select(OperationException).where(
        OperationException.source_type == 'FINANCE_INVOICE_MATCH', OperationException.source_id == match.id))
    assert exception is not None and invoice.invoice_no in exception.description and rec.reconciliation_no in exception.description
    suggestion = db.scalar(select(AIOperationSuggestion).where(AIOperationSuggestion.exception_id == exception.id))
    assert suggestion and suggestion.status == 'OPEN'
    service.scan_invoice_differences(db, actor)
    assert len(db.scalars(select(OperationException).where(OperationException.source_type == 'FINANCE_INVOICE_MATCH', OperationException.source_id == match.id)).all()) == 1


def test_invoice_exception_requires_current_finance_read_scope(db_session, monkeypatch):
    from app.modules.operation_exceptions import service as exceptions
    db = db_session
    invoice = db.scalar(select(FinanceInvoice).where(FinanceInvoice.status == 'SUBMITTED'))
    match = db.scalar(select(FinanceInvoiceMatch).where(FinanceInvoiceMatch.invoice_id == invoice.id).order_by(FinanceInvoiceMatch.version_no.desc()))
    actor = SimpleNamespace(id=invoice.submitted_by, department_id=None)
    exception = OperationException(exception_no='TEST-INVOICE-SCOPE', exception_type='INVOICE_DIFFERENCE', source_type='FINANCE_INVOICE_MATCH', source_id=match.id, owner_id=actor.id, severity='MEDIUM', description='差异', status='OPEN')
    db.add(exception); db.flush()
    monkeypatch.setattr(exceptions, 'get_user_role_codes', lambda *_: ['FINANCE_MANAGER'])
    monkeypatch.setattr(exceptions, 'get_user_permission_codes', lambda *_: ['finance.invoices.read', 'finance.reconciliations.read'])
    assert exceptions._has_exception_scope(db, actor, exception)
    monkeypatch.setattr(exceptions, 'get_user_permission_codes', lambda *_: ['finance.invoices.read'])
    assert not exceptions._has_exception_scope(db, actor, exception)


def test_draft_invoice_is_not_reported_while_matching_is_in_progress(db_session):
    db = db_session
    actor = db.scalar(select(User).where(User.username == 'system_admin'))
    row = db.execute(select(FinanceInvoice, FinanceInvoiceMatch)
        .join(FinanceInvoiceMatch, FinanceInvoiceMatch.invoice_id == FinanceInvoice.id)
        .where(FinanceInvoice.status == 'SUBMITTED')
        .order_by(FinanceInvoice.id, FinanceInvoiceMatch.version_no.desc())).first()
    invoice, match = row
    before = len(db.scalars(select(OperationException).where(
        OperationException.source_type == 'FINANCE_INVOICE_MATCH', OperationException.source_id == match.id)).all())
    invoice.status = 'DRAFT'
    match.source_hash = 'stale-test'
    db.flush()
    service.scan_invoice_differences(db, actor)
    after = len(db.scalars(select(OperationException).where(
        OperationException.source_type == 'FINANCE_INVOICE_MATCH', OperationException.source_id == match.id)).all())
    assert after == before
