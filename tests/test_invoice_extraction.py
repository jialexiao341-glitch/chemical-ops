from decimal import Decimal
from types import SimpleNamespace
from app.modules.finance import invoice_extraction


def test_candidates_require_field_specific_evidence_and_preserve_invoice_number():
    text = '[第 1 页]\n发票号码：00001234\n开票日期：2026年10月20日\n不含税金额：100.00\n税额：13.00\n价税合计：113.00'
    extracted = invoice_extraction._ExtractedInvoice(
        invoice_number='00001234', invoice_date='2026-10-20', amount_excl_tax='100.00',
        tax_amount='99.00', amount_incl_tax='113.00',
        evidence={'invoice_number':'发票号码：00001234', 'invoice_date':'开票日期：2026年10月20日',
                  'amount_excl_tax':'不含税金额：100.00', 'tax_amount':'税额：13.00',
                  'amount_incl_tax':'价税合计：113.00'})
    values, evidence, dropped = invoice_extraction.verify_candidates(extracted, text)
    assert values['invoice_number'] == '00001234' and values['invoice_date'] == '2026-10-20'
    assert Decimal(values['amount_excl_tax']) == Decimal('100') and values['tax_amount'] is None
    assert 'tax_amount' in dropped and all(item.source_location == '第 1 页' for item in evidence)


def test_unsupported_unlocated_and_invalid_values_are_not_accepted():
    extracted = invoice_extraction._ExtractedInvoice(invoice_number='123', amount_incl_tax='-9',
        evidence={'invoice_number':'不存在 123', 'amount_incl_tax':'-9'})
    values, evidence, dropped = invoice_extraction.verify_candidates(extracted, '价税合计：-9')
    assert values['invoice_number'] is None and values['amount_incl_tax'] is None
    assert evidence == [] and set(dropped) == {'invoice_number', 'amount_incl_tax'}


def test_invoice_number_must_match_complete_token():
    extracted = invoice_extraction._ExtractedInvoice(invoice_number='123', evidence={'invoice_number': '发票号码：1234'})
    values, evidence, dropped = invoice_extraction.verify_candidates(extracted, '发票号码：1234')
    assert values['invoice_number'] is None and not evidence and dropped == ['invoice_number']


def test_parse_preview_and_confirmed_invoice_link_use_real_services(client, db_session, monkeypatch):
    import json
    from uuid import uuid4
    from sqlalchemy import func, select
    from app.core.auth import get_current_user
    from app.core.rate_limit import limit_document
    from app.main import app
    from app.modules.files import service as files
    from app.modules.finance import service as finance
    from app.modules.finance.model import FinanceInvoice, FinanceReconciliation
    from app.modules.finance.schema import InvoiceCreate
    from app.modules.system.file_model import SysFile, SysFileAttachment
    from app.modules.system.model import User
    from app.core.errors import BusinessValidationError, DuplicateResourceError
    import pytest
    db = db_session
    actor = db.scalar(select(User).where(User.username == 'system_admin'))
    total = select(func.coalesce(func.sum(FinanceInvoice.amount_incl_tax), 0)).where(
        FinanceInvoice.reconciliation_id == FinanceReconciliation.id,
        FinanceInvoice.status.in_(['DRAFT', 'SUBMITTED', 'VERIFIED'])).scalar_subquery()
    rec = db.scalar(select(FinanceReconciliation).where(FinanceReconciliation.status == 'CONFIRMED',
        FinanceReconciliation.total_amount - total >= 226).limit(1))
    assert rec is not None
    number = 'T' + uuid4().hex[:15]
    text = f'发票号码：{number}\n开票日期：2026-10-20\n不含税金额：100.00\n税额：13.00\n价税合计：113.00'
    output = {'invoice_number': number, 'invoice_date': '2026-10-20', 'amount_excl_tax': '100.00',
        'tax_amount': '13.00', 'amount_incl_tax': '113.00',
        'evidence': {'invoice_number': f'发票号码：{number}', 'invoice_date': '开票日期：2026-10-20',
            'amount_excl_tax': '不含税金额：100.00', 'tax_amount': '税额：13.00', 'amount_incl_tax': '价税合计：113.00'}}
    async def fake_chat(*args, **kwargs):
        assert len(args[0].messages[0].content) <= 20000
        return SimpleNamespace(answer=json.dumps(output, ensure_ascii=False), message=SimpleNamespace(content=''))
    monkeypatch.setattr(invoice_extraction, 'chat', fake_chat)
    monkeypatch.setattr(files, 'scan_content', lambda content: SimpleNamespace(status='CLEAN'))
    monkeypatch.setattr(files, '_put_object', lambda *args: None)
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[limit_document] = lambda: None
    before = db.scalar(select(func.count()).select_from(FinanceInvoice))
    try:
        preview = client.post(f'/api/v1/finance/reconciliations/{rec.id}/invoices/parse-file',
                              files={'file': ('invoice.txt', text.encode('utf-8'), 'text/plain')})
        assert preview.status_code == 200, preview.text
        candidate = preview.json()
        assert candidate['invoice_number'] == number and len(candidate['evidence']) == 5
        long_preview = client.post(f'/api/v1/finance/reconciliations/{rec.id}/invoices/parse-file',
            files={'file': ('long.txt', (text + 'x' * 21000).encode('utf-8'), 'text/plain')})
        assert long_preview.status_code == 200 and any('20000' in warning for warning in long_preview.json()['warnings'])
        assert db.scalar(select(func.count()).select_from(FinanceInvoice)) == before
        payload = InvoiceCreate(reconciliation_id=rec.id, invoice_number=number,
            invoice_date='2026-10-20', amount_excl_tax='100', tax_amount='13', amount_incl_tax='113',
            source_file_id=candidate['file_id'])
        invoice = finance.create_invoice(db, actor, payload)
        assert invoice.status == 'DRAFT' and invoice.source_file_id == candidate['file_id']
        attachment = db.scalar(select(SysFileAttachment).where(SysFileAttachment.file_id == candidate['file_id']))
        assert attachment.resource_type == 'FINANCE_INVOICE' and attachment.resource_id == invoice.id
        assert db.get(SysFile, candidate['file_id']).uploader_id == actor.id
        manager = db.scalar(select(User).where(User.username == 'finance_manager'))
        assert files.get_file(db, manager, candidate['file_id']).id == candidate['file_id']
        buyer = db.scalar(select(User).where(User.username == 'buyer'))
        from app.core.errors import ResourceNotFoundError
        with pytest.raises(ResourceNotFoundError):
            files.get_file(db, buyer, candidate['file_id'])
        with pytest.raises(DuplicateResourceError):
            finance.create_invoice(db, actor, payload)
        payload.invoice_number = number + 'X'
        with pytest.raises(BusinessValidationError):
            finance.create_invoice(db, actor, payload)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(limit_document, None)


def test_invoice_amount_rejects_scientific_and_excess_precision():
    extracted = invoice_extraction._ExtractedInvoice(amount_excl_tax='1e2', tax_amount='0.0000001',
        evidence={'amount_excl_tax':'100', 'tax_amount':'0.0000001'})
    values, evidence, dropped = invoice_extraction.verify_candidates(extracted, '不含税：100 税额：0.0000001')
    assert values['amount_excl_tax'] is None and values['tax_amount'] is None
    assert not evidence and set(dropped) == {'amount_excl_tax', 'tax_amount'}


def test_invalid_file_and_revoked_permission_never_upload(client, db_session, monkeypatch):
    from sqlalchemy import select
    from app.core.auth import get_current_user
    from app.core.rate_limit import limit_document
    from app.main import app
    from app.modules.files import service as files
    from app.modules.finance.model import FinanceReconciliation
    from app.modules.system.model import User
    from unittest.mock import Mock
    db = db_session
    actor = db.scalar(select(User).where(User.username == 'system_admin'))
    buyer = db.scalar(select(User).where(User.username == 'buyer'))
    rec = db.scalar(select(FinanceReconciliation).where(FinanceReconciliation.status == 'CONFIRMED').limit(1))
    upload = Mock()
    monkeypatch.setattr(files, 'upload_file', upload)
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[limit_document] = lambda: None
    try:
        response = client.post(f'/api/v1/finance/reconciliations/{rec.id}/invoices/parse-file',
            files={'file': ('fake.pdf', b'not a pdf', 'application/pdf')})
        assert response.status_code == 400 and not upload.called
        app.dependency_overrides[get_current_user] = lambda: buyer
        response = client.post(f'/api/v1/finance/reconciliations/{rec.id}/invoices/parse-file',
            files={'file': ('invoice.txt', b'invoice', 'text/plain')})
        assert response.status_code == 403 and not upload.called
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(limit_document, None)


def test_write_permission_rechecked_after_model_call(client, db_session, monkeypatch):
    import json
    from unittest.mock import Mock
    from sqlalchemy import select
    from app.core.auth import get_current_user
    from app.core.rate_limit import limit_document
    from app.main import app
    from app.modules.files import service as files
    from app.modules.finance.model import FinanceReconciliation
    from app.modules.system.model import User
    actor = db_session.scalar(select(User).where(User.username == 'system_admin'))
    rec = db_session.scalar(select(FinanceReconciliation).where(FinanceReconciliation.status == 'CONFIRMED').limit(1))
    async def fake_chat(*args, **kwargs):
        return SimpleNamespace(answer=json.dumps({'invoice_number':'1234', 'evidence':{'invoice_number':'发票号码：1234'}}, ensure_ascii=False), message=SimpleNamespace(content=''))
    monkeypatch.setattr(invoice_extraction, 'chat', fake_chat)
    monkeypatch.setattr(invoice_extraction, 'get_user_role_codes', lambda *_: [])
    monkeypatch.setattr(invoice_extraction, 'get_user_permission_codes', lambda *_: ['finance.reconciliations.read'])
    monkeypatch.setattr(files, 'scan_content', lambda content: SimpleNamespace(status='CLEAN'))
    upload = Mock()
    monkeypatch.setattr(files, 'upload_file', upload)
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[limit_document] = lambda: None
    try:
        response = client.post(f'/api/v1/finance/reconciliations/{rec.id}/invoices/parse-file',
            files={'file': ('invoice.txt', '发票号码：1234'.encode(), 'text/plain')})
        assert response.status_code == 403 and not upload.called
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(limit_document, None)


def test_other_users_upload_cannot_be_used_as_invoice_source(db_session):
    from uuid import uuid4
    from sqlalchemy import select, func
    from app.core.errors import BusinessValidationError
    from app.modules.finance import service
    from app.modules.finance.model import FinanceInvoice, FinanceReconciliation
    from app.modules.finance.schema import InvoiceCreate
    from app.modules.system.file_model import SysFile
    from app.modules.system.model import User
    import pytest
    db = db_session
    actor = db.scalar(select(User).where(User.username == 'system_admin'))
    other = db.scalar(select(User).where(User.username == 'buyer'))
    total = select(func.coalesce(func.sum(FinanceInvoice.amount_incl_tax), 0)).where(
        FinanceInvoice.reconciliation_id == FinanceReconciliation.id,
        FinanceInvoice.status.in_(['DRAFT', 'SUBMITTED', 'VERIFIED'])).scalar_subquery()
    rec = db.scalar(select(FinanceReconciliation).where(FinanceReconciliation.status == 'CONFIRMED',
        FinanceReconciliation.total_amount - total >= 1).limit(1))
    source = SysFile(file_name='invoice.txt', object_key='test/' + uuid4().hex, mime_type='text/plain',
        file_size_bytes=1, sha256_hash='a'*64, file_category='FINANCE_INVOICE', access_level='INTERNAL', uploader_id=other.id)
    db.add(source); db.flush()
    payload = InvoiceCreate(reconciliation_id=rec.id, invoice_number='T' + uuid4().hex[:12],
        invoice_date='2026-10-20', amount_excl_tax='1', tax_amount='0', amount_incl_tax='1', source_file_id=source.id)
    with pytest.raises(BusinessValidationError):
        service.create_invoice(db, actor, payload)
