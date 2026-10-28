from types import SimpleNamespace

from app.core.errors import ResourceNotFoundError
from app.modules.ai import document_center
import pytest


def test_reference_preserves_only_saved_evidence():
    row = SimpleNamespace(file_id=4, result_json={"checks": [
        {"item_name": "纯度", "source_quote": "纯度 99%", "source_location": None},
        {"item_name": "水分", "source_quote": None, "source_location": None},
    ]})
    references = document_center.review_references(row, "报告.pdf", 8)
    assert references[0] == {"file_id": 4, "file_name": "报告.pdf", "object_type": "quality_acceptance", "object_id": 8, "field": "纯度", "quote": "纯度 99%", "location": None}
    assert references[1]["quote"] is None


def test_pagination_follows_visibility_and_filtering(monkeypatch):
    rows = [
        {"file_id": 3, "object_id": 1, "file_name": "秘密.pdf", "document_no": "Q-1", "type": "quote", "visible": False},
        {"file_id": 2, "object_id": 2, "file_name": "可见.pdf", "document_no": "Q-2", "type": "quote", "visible": True},
        {"file_id": 1, "object_id": 3, "file_name": "报告.pdf", "document_no": "A-1", "type": "quality", "visible": True},
    ]
    monkeypatch.setattr(document_center, "_collect", lambda db, user, **kwargs: rows)
    monkeypatch.setattr(document_center, "_visible", lambda db, user, row: row["visible"])
    db = SimpleNamespace(scalar=lambda query: None)
    result = document_center.list_documents(db, None, kind=None, keyword=None, page=1, page_size=1)
    assert result["total"] == 2
    assert result["items"][0]["document_no"] == "Q-2"
    result = document_center.list_documents(db, None, kind="quote", keyword="秘密", page=1, page_size=20)
    assert result["total"] == 0


def test_review_status_loads_only_for_current_page(monkeypatch):
    rows = [{'type': 'quality', 'file_id': n, 'object_id': n, 'file_name': f'{n}.pdf', 'document_no': str(n)} for n in range(1, 5)]
    monkeypatch.setattr(document_center, '_collect', lambda *args, **kwargs: rows)
    monkeypatch.setattr(document_center, '_visible', lambda *args: True)
    calls = []
    db = SimpleNamespace(scalar=lambda query: calls.append(query))
    result = document_center.list_documents(db, None, kind='quality', keyword=None, page=1, page_size=1)
    assert result['total'] == 4
    assert len(calls) == 1


def test_keyword_filter_skips_unrelated_permission_checks(monkeypatch):
    rows = [
        {'type': 'quality', 'file_id': 1, 'object_id': 1, 'file_name': '无关.pdf', 'document_no': 'A-1'},
        {'type': 'quality', 'file_id': 2, 'object_id': 2, 'file_name': '目标.pdf', 'document_no': 'A-2'},
    ]
    monkeypatch.setattr(document_center, '_collect', lambda *args, **kwargs: rows)
    checked = []
    monkeypatch.setattr(document_center, '_visible', lambda db, user, row: checked.append(row['object_id']) or True)
    db = SimpleNamespace(scalar=lambda query: None)
    result = document_center.list_documents(db, None, kind='quality', keyword='目标', page=1, page_size=20)
    assert checked == [2]
    assert result['total'] == 1 and result['items'][0]['object_id'] == 2


@pytest.mark.parametrize("kind,service", [("quote", "rfqs"), ("quality", "quality"), ("invoice", "finance")])
def test_document_requires_both_file_and_business_access(monkeypatch, kind, service):
    getter = {"quote": "get_rfq", "quality": "get_acceptance", "invoice": "get_invoice"}[kind]
    domain = getattr(document_center, service)
    monkeypatch.setattr(domain, getter, lambda *args: object())
    monkeypatch.setattr(document_center.files, "get_file", lambda *args: object())
    row = {"type": kind, "object_id": 2, "file_id": 3}
    assert document_center._visible(None, None, row)
    def denied(*args):
        raise ResourceNotFoundError()
    monkeypatch.setattr(document_center.files, "get_file", denied)
    assert not document_center._visible(None, None, row)
    monkeypatch.setattr(document_center.files, "get_file", lambda *args: object())
    monkeypatch.setattr(domain, getter, denied)
    assert not document_center._visible(None, None, row)


def test_reference_read_rechecks_access(monkeypatch):
    row = {"type": "invoice", "object_id": 2, "file_id": 3}
    monkeypatch.setattr(document_center, "_collect", lambda *args, **kwargs: [row])
    monkeypatch.setattr(document_center, "_visible", lambda *args: False)
    with pytest.raises(ResourceNotFoundError):
        document_center.references(None, None, "invoice", 2, 3)
    monkeypatch.setattr(document_center, "_visible", lambda *args: True)
    assert document_center.references(None, None, "invoice", 2, 3)["message"] == "未保存解析依据"


def test_missing_source_visible_only_with_business_permission(monkeypatch):
    monkeypatch.setattr(document_center.finance, 'get_invoice', lambda *args: object())
    monkeypatch.setattr(document_center.files, 'get_file', lambda *args: pytest.fail('没有关联文件时不应查询文件'))
    row = {'type': 'invoice', 'object_id': 2, 'file_id': None}
    assert document_center._visible(None, None, row)
    def denied(*args):
        raise ResourceNotFoundError()
    monkeypatch.setattr(document_center.finance, 'get_invoice', denied)
    assert not document_center._visible(None, None, row)


def test_quality_references_include_all_review_snapshots(monkeypatch):
    row = {"type": "quality", "object_id": 2, "file_id": 3, "file_name": "报告.pdf"}
    monkeypatch.setattr(document_center, "_collect", lambda *args, **kwargs: [row])
    monkeypatch.setattr(document_center, "_visible", lambda *args: True)
    reviews = [SimpleNamespace(id=9, delivery_item_id=12, status='PENDING', file_id=3,
                               result_json={'checks': [{'item_name': '纯度', 'source_quote': '99%', 'source_location': '第1页'}]}),
               SimpleNamespace(id=8, delivery_item_id=11, status='CONFIRMED', file_id=3,
                               result_json={'checks': [{'item_name': '水分', 'source_quote': '1%', 'source_location': None}]})]
    db = SimpleNamespace(scalars=lambda query: SimpleNamespace(all=lambda: reviews))
    result = document_center.references(db, None, 'quality', 2, 3)
    assert [(x['review_id'], x['delivery_item_id'], x['quote']) for x in result['references']] == [(9, 12, '99%'), (8, 11, '1%')]


def test_document_center_real_database_and_http(client, db_session, demo_password):
    from tests.conftest import login
    headers = login(client, 'system_admin', demo_password)
    response = client.get('/api/v1/ai/documents', headers=headers, params={'page_size': 10})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['total'] >= len(payload['items'])
    for row in payload['items']:
        assert row['type'] in {'quote', 'quality', 'invoice'}
        if row['file_id'] is None:
            assert row['file_name'] == '未关联文件'
            continue
        detail = client.get(f"/api/v1/ai/documents/{row['type']}/{row['object_id']}/{row['file_id']}/references", headers=headers)
        assert detail.status_code == 200, detail.text
        assert 'references' in detail.json()


def test_missing_invoice_source_on_real_api(client, db_session, demo_password):
    from sqlalchemy import select
    from app.modules.finance.model import FinanceInvoice
    from tests.conftest import login
    invoice = db_session.scalar(select(FinanceInvoice).limit(1))
    if invoice is None:
        pytest.skip('测试库没有发票记录')
    invoice.source_file_id = None
    db_session.flush()
    response = client.get('/api/v1/ai/documents', headers=login(client, 'system_admin', demo_password),
                          params={'kind': 'invoice', 'keyword': invoice.invoice_no})
    assert response.status_code == 200, response.text
    item = next(row for row in response.json()['items'] if row['object_id'] == invoice.id)
    assert item['file_id'] is None and item['file_name'] == '未关联文件'


def test_foreign_rfq_hidden_even_when_buyer_uploaded_file(client, db_session, demo_password):
    from uuid import uuid4
    from sqlalchemy import select
    from app.modules.rfqs.model import RFQ, SupplierQuote
    from app.modules.suppliers.model import Supplier
    from app.modules.system.file_model import SysFile
    from app.modules.system.model import User
    from tests.conftest import login
    buyer = db_session.scalar(select(User).where(User.username == 'buyer'))
    admin = db_session.scalar(select(User).where(User.username == 'system_admin'))
    supplier = db_session.scalar(select(Supplier).limit(1))
    assert buyer and admin and supplier
    marker = uuid4().hex
    rfq = RFQ(rfq_no=f'DC-{marker[:20]}', requester_id=admin.id, status='DRAFT')
    db_session.add(rfq)
    db_session.flush()
    quote = SupplierQuote(quote_no=f'DCQ-{marker[:20]}', rfq_id=rfq.id, supplier_id=supplier.id,
                          quote_version=1, status='DRAFT', currency_code='CNY')
    db_session.add(quote)
    db_session.flush()
    file = SysFile(file_name=f'{marker}.txt', object_key=f'test/{marker}', mime_type='text/plain',
                   file_size_bytes=1, sha256_hash='a' * 64, file_category='QUOTE', access_level='PRIVATE', uploader_id=buyer.id)
    db_session.add(file)
    db_session.flush()
    quote.source_file_id = file.id
    db_session.flush()
    endpoint = '/api/v1/ai/documents'
    response = client.get(endpoint, headers=login(client, 'buyer', demo_password), params={'kind': 'quote', 'keyword': marker})
    assert response.status_code == 200, response.text
    assert response.json()['total'] == 0
    response = client.get(f'{endpoint}/quote/{quote.rfq_id}/{file.id}/references', headers=login(client, 'buyer', demo_password))
    assert response.status_code == 404
    response = client.get(endpoint, headers=login(client, 'system_admin', demo_password), params={'kind': 'quote', 'keyword': marker})
    assert response.status_code == 200 and response.json()['total'] == 1


def test_quality_search_matches_attached_filename(client, db_session, demo_password):
    from uuid import uuid4
    from sqlalchemy import select
    from app.modules.quality_acceptances.model import QualityAcceptance
    from app.modules.system.file_model import SysFile, SysFileAttachment
    from app.modules.system.model import User
    from tests.conftest import login
    acceptance = db_session.scalar(select(QualityAcceptance).limit(1))
    admin = db_session.scalar(select(User).where(User.username == 'system_admin'))
    assert acceptance and admin
    marker = uuid4().hex
    source = SysFile(file_name=f'{marker}.txt', object_key=f'test/{marker}', mime_type='text/plain',
                     file_size_bytes=1, sha256_hash='a' * 64, file_category='QUALITY_REPORT', access_level='PRIVATE', uploader_id=admin.id)
    db_session.add(source)
    db_session.flush()
    db_session.add(SysFileAttachment(file_id=source.id, resource_type='QUALITY_ACCEPTANCE', resource_id=acceptance.id, created_by=admin.id))
    db_session.flush()
    response = client.get('/api/v1/ai/documents', headers=login(client, 'system_admin', demo_password),
                          params={'kind': 'quality', 'keyword': marker})
    assert response.status_code == 200, response.text
    assert [(row['object_id'], row['file_id']) for row in response.json()['items']] == [(acceptance.id, source.id)]
