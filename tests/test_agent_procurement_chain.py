"""采购全链路接口验收：真实权限/领域服务/MySQL，外部模型使用固定响应。

业务数据和临时登录口令沿用 conftest 的外部事务，结束后全部回滚；
上传原文写入 pytest 临时目录。此验收不覆盖浏览器或真实模型质量。
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.main import app
from app.modules.ai.model import AIAgentActionProposal
from app.modules.chemicals.model import Chemical
from app.modules.files import service as file_service
from app.modules.system.file_model import SysFile
from app.modules.products.model import Product
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_requests.model import PurchaseRequest, PurchaseRequestItem, Unit
from app.modules.rfqs import quote_extraction
from app.modules.rfqs.model import RFQ, SupplierQuote
from app.modules.suppliers.model import Supplier

from .conftest import login


pytestmark = pytest.mark.integration


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def _preview(client, headers, action, payload):
    return _ok(client.post('/api/v1/ai/action-proposals', headers=headers, json={
        'action_type': action, 'payload': payload, 'idempotency_key': uuid4().hex,
    }))


def _confirm(client, headers, preview):
    body = {key: preview[key] for key in ('confirmation_id', 'preview_version')}
    body['confirm'] = True
    url = f"/api/v1/ai/action-proposals/{body['confirmation_id']}/confirm"
    result = _ok(client.post(url, headers=headers, json=body))
    # HTTP 重试必须重放结果，不重复写业务数据和审批节点。
    assert _ok(client.post(url, headers=headers, json=body)) == result
    return result


@pytest.fixture
def chain_storage():
    root = Path(__file__).resolve().parents[1] / '.pytest-file-storage'
    root.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='procurement-chain-', dir=root) as directory:
        yield Path(directory)


@pytest.fixture
def chain_catalog(db_session):
    tag = uuid4().hex[:12]
    unit = Unit(unit_code=f'CHAIN-{tag}', unit_name='升', dimension='VOLUME')
    chemical = Chemical(chemical_name=f'链路验收化学品{tag}')
    supplier = Supplier(supplier_code=f'CHAIN-{tag}', supplier_name=f'链路验收供应商{tag}')
    db_session.add_all([unit, chemical, supplier])
    db_session.flush()
    products = [Product(product_code=f'CHAIN-{tag}-{i}', product_name=f'链路验收物料{tag}-{i}',
                        chemical_id=chemical.id, unit_id=unit.id) for i in (1, 2)]
    db_session.add_all(products)
    db_session.flush()
    return unit, supplier, products


def test_confirmed_actions_connect_request_rfq_review_award_order_and_submit(
    client, db_session, demo_password, chain_catalog, monkeypatch, chain_storage,
):
    unit, supplier, products = chain_catalog
    buyer = login(client, 'buyer', demo_password)
    manager = login(client, 'procurement_manager', demo_password)
    # 每个 HTTP 请求使用独立 identity map，贴近生产 get_db；commit 仅释放
    # SAVEPOINT，所有请求仍属于 conftest 管理的可回滚外部事务。
    connection = db_session.connection()

    def request_session():
        with Session(bind=connection, autoflush=False, expire_on_commit=False,
                     join_transaction_mode='create_savepoint') as session:
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_db, request_session)
    counts = {model: db_session.scalar(select(func.count()).select_from(model))
              for model in (PurchaseRequest, RFQ, SupplierQuote, PurchaseOrder)}

    # 每种动作均通过真实 HTTP 提案/确认入口，不替换权限或领域处理器。
    preview = _preview(client, buyer, 'purchase_request.create_draft', {
        'purpose': '采购链路接口验收', 'items': [
            {'product_id': product.id, 'requested_name': product.product_name,
             'quantity': '10', 'unit_id': unit.id} for product in products],
    })
    assert db_session.scalar(select(func.count()).select_from(PurchaseRequest)) == counts[PurchaseRequest]
    # 他人无法消费本人提案；不确认不能写入。
    url = f"/api/v1/ai/action-proposals/{preview['confirmation_id']}/confirm"
    body = {'confirmation_id': preview['confirmation_id'], 'preview_version': 1, 'confirm': True}
    assert client.post(url, headers=manager, json=body).status_code == 404
    assert client.post(url, headers=buyer, json={**body, 'confirm': False}).status_code == 422
    request = _confirm(client, buyer, preview)
    assert request['status'] == 'DRAFT' and len(request['items']) == 2
    request = _confirm(client, buyer, _preview(client, buyer, 'purchase_request.submit', {
        'request_no': request['request_no'],
    }))
    assert request['status'] == 'APPROVING'
    rfq_payload = {
        'source_request_id': request['id'], 'supplier_ids': [supplier.id],
        'items': [{'source_request_item_id': item['id'], 'product_id': item['product_id'],
                   'requested_name': item['requested_name'], 'quantity': item['quantity'],
                   'unit_id': item['unit_id']} for item in request['items']],
    }
    # Agent 不能跳过人工审批，也不能审批本人申请。
    rejected = client.post('/api/v1/ai/action-proposals', headers=buyer, json={
        'action_type': 'rfq.create_draft', 'payload': rfq_payload, 'idempotency_key': uuid4().hex,
    })
    assert rejected.status_code == 400, rejected.text
    assert client.post(f"/api/v1/purchase-requests/{request['id']}/approve",
                       headers=buyer, json={}).status_code in {400, 403}
    approved = _ok(client.post(f"/api/v1/purchase-requests/{request['id']}/approve",
                              headers=manager, json={'opinion': '测试角色显式审批'}))
    assert approved['status'] == 'APPROVED'
    preview = _preview(client, buyer, 'rfq.create_draft', rfq_payload)
    assert db_session.scalar(select(func.count()).select_from(RFQ)) == counts[RFQ]
    rfq = _confirm(client, buyer, preview)
    assert rfq['status'] == 'DRAFT'
    rfq = _confirm(client, buyer, _preview(client, buyer, 'rfq.send', {'rfq_id': rfq['id']}))
    assert rfq['status'] == 'SENT'

    # 使用真实 CSV 解析、逐字段证据校验、文件持久化；仅隔离外部模型响应。
    valid_until = (date.today() + timedelta(days=30)).isoformat()
    lines = [f"{item['requested_name']}，数量10升，未税单价{10 + i} CNY/升，税率13%，交期7天，月结{30 + i * 30}天"
             for i, item in enumerate(rfq['items'])]
    content = '\n'.join([f'供应商：{supplier.supplier_name}', '币种：CNY',
                         f'有效期至：{valid_until}', *lines]).encode('utf-8')
    model_result = {
        'supplier_name': supplier.supplier_name, 'currency_code': 'CNY',
        'valid_until': valid_until,
        'evidence': {'supplier_name': f'供应商：{supplier.supplier_name}',
                     'currency_code': '币种：CNY', 'valid_until': f'有效期至：{valid_until}'},
        'items': [{'rfq_item_id': item['id'], 'product_label': item['requested_name'],
                   'quoted_quantity': '10', 'unit_name': '升', 'unit_price': str(10 + i),
                   'tax_rate': '13', 'tax_included': False, 'lead_days': 7,
                   'payment_terms': f'月结{30 + i * 30}天', 'quote': lines[i],
                   'evidence': {'product_label': item['requested_name'], 'quoted_quantity': '数量10升',
                                'unit_name': 'CNY/升', 'unit_price': f'单价{10 + i} CNY/升',
                                'tax_rate': '税率13%', 'tax_included': '未税', 'lead_days': '交期7天',
                                'payment_terms': f'月结{30 + i * 30}天'}}
                  for i, item in enumerate(rfq['items'])],
    }

    async def fixed_chat(*_args, **_kwargs):
        answer = json.dumps(model_result, ensure_ascii=False)
        return SimpleNamespace(answer=answer, message=SimpleNamespace(content=answer))

    settings = get_settings().model_copy(update={
        'file_storage_backend': 'local', 'file_storage_root': str(chain_storage), 'file_scan_enabled': False,
    })
    monkeypatch.setattr(quote_extraction, 'chat', fixed_chat)
    monkeypatch.setattr(file_service, 'get_settings', lambda: settings)
    candidate = _ok(client.post(f"/api/v1/rfqs/{rfq['id']}/quotes/parse-file", headers=buyer,
                               files={'file': ('quote.csv', content, 'text/csv')}))
    assert db_session.scalar(select(func.count()).select_from(SupplierQuote)) == counts[SupplierQuote]
    assert len(candidate['items']) == 2
    assert [item['rfq_item_id'] for item in candidate['items']] == [item['id'] for item in rfq['items']]
    source_file = db_session.get(SysFile, candidate['file_id'])
    assert source_file.file_category == 'SUPPLIER_QUOTE'
    assert (chain_storage / source_file.object_key).read_bytes() == content

    # 模拟用户逐字段复核后主动提交报价；解析接口本身不得录入报价。
    quote_payload = {
        'supplier_id': supplier.id, 'currency_code': candidate['currency_code'],
        'valid_until': candidate['valid_until'], 'source_file_id': candidate['file_id'],
        'items': [{key: item[key] for key in ('rfq_item_id', 'quoted_quantity', 'unit_price',
                   'tax_rate', 'tax_included', 'lead_days', 'payment_terms')} | {'unit_id': unit.id}
                  for item in candidate['items']],
    }
    rfq = _ok(client.post(f"/api/v1/rfqs/{rfq['id']}/quotes", headers=buyer, json=quote_payload))
    quote = rfq['quotes'][0]
    assert quote['source_file_id'] == candidate['file_id']
    comparison = _ok(client.post(f"/api/v1/rfqs/{rfq['id']}/comparison", headers=buyer))
    # 中选由有定标权限的采购负责人操作，采购员不能越权定标。
    denied_award = client.post('/api/v1/ai/action-proposals', headers=buyer, json={
        'action_type': 'rfq.select_quote', 'idempotency_key': uuid4().hex,
        'payload': {'rfq_id': rfq['id'], 'comparison_id': comparison['id'],
                    'quote_id': quote['id'], 'selection_reason': '无定标权限'},
    })
    assert denied_award.status_code == 403
    rfq = _confirm(client, manager, _preview(client, manager, 'rfq.select_quote', {
        'rfq_id': rfq['id'], 'comparison_id': comparison['id'], 'quote_id': quote['id'],
        'selection_reason': '逐项复核报价及总成本后确认中选',
    }))
    assert rfq['status'] == 'CLOSED'
    preview = _preview(client, buyer, 'purchase_order.create_draft', {
        'comparison_id': comparison['id'], 'quote_id': quote['id'], 'delivery_address': '接口验收仓库',
    })
    assert db_session.scalar(select(func.count()).select_from(PurchaseOrder)) == counts[PurchaseOrder]
    order = _confirm(client, buyer, preview)
    assert order['status'] == 'DRAFT'
    assert order['source_request_id'] == request['id']
    assert order['source_quote_id'] == quote['id']
    assert order['source_comparison_id'] == comparison['id']
    assert [item['payment_terms_snapshot'] for item in order['items']] == ['月结30天', '月结60天']
    assert [Decimal(item['order_quantity']) for item in order['items']] == [Decimal('10')] * 2
    assert Decimal(order['order_amount']) == Decimal('237.30')
    order = _confirm(client, buyer, _preview(client, buyer, 'purchase_order.submit', {'po_no': order['po_no']}))
    assert order['status'] == 'APPROVING'
    assert len(order['approvals']) == 1 and order['approvals'][0]['action'] == 'PENDING'
    assert order['order_date'] is None
    assert list(db_session.scalars(select(PurchaseRequestItem.fulfilled_quantity).where(
        PurchaseRequestItem.request_id == request['id']))) == [Decimal('0')] * 2
    for model, before in counts.items():
        assert db_session.scalar(select(func.count()).select_from(model)) == before + 1
    assert db_session.scalar(select(func.count()).select_from(AIAgentActionProposal).where(
        AIAgentActionProposal.confirmation_id == preview['confirmation_id'],
        AIAgentActionProposal.status == 'EXECUTED')) == 1


def test_quote_response_refreshes_loaded_collection_for_each_version(
    client, db_session, demo_password, chain_catalog,
):
    """expire_on_commit=False 下首份和修订报价都必须立即出现在响应中。"""
    unit, supplier, products = chain_catalog
    buyer = login(client, 'buyer', demo_password)
    rfq = _ok(client.post('/api/v1/rfqs', headers=buyer, json={
        'supplier_ids': [supplier.id],
        'items': [{'product_id': products[0].id, 'requested_name': products[0].product_name,
                   'quantity': '10', 'unit_id': unit.id}],
    }), status=201)
    rfq = _ok(client.post(f"/api/v1/rfqs/{rfq['id']}/send", headers=buyer))
    for version in (1, 2):
        rfq = _ok(client.post(f"/api/v1/rfqs/{rfq['id']}/quotes", headers=buyer, json={
            'supplier_id': supplier.id, 'currency_code': 'CNY',
            'items': [{'rfq_item_id': rfq['items'][0]['id'], 'quoted_quantity': '10',
                       'unit_id': unit.id, 'unit_price': str(version), 'tax_rate': '13',
                       'tax_included': False}],
        }))
        assert rfq['status'] == 'RESPONDING'
        assert sorted(quote['quote_version'] for quote in rfq['quotes']) == list(range(1, version + 1))
        saved = list(db_session.scalars(select(SupplierQuote).where(SupplierQuote.rfq_id == rfq['id'])))
        assert {quote['id'] for quote in rfq['quotes']} == {quote.id for quote in saved}
