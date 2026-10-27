"""悬浮助手：授权事实驱动的真实模型流式输出。"""
import asyncio
import json
from types import SimpleNamespace
from app.modules.ai import context_stream


def test_stream_uses_authorized_facts_and_preserves_evidence(monkeypatch):
    captured = {}
    async def fake_stream(data, settings, **kwargs):
        captured['messages'] = data.messages
        captured.update(kwargs)
        yield '第一段'
        yield '第二段'
    monkeypatch.setattr(context_stream, 'stream_chat', fake_stream)
    snapshot = {'answer': '已授权事实', 'context': {'title': '订单'}, 'citations': [{'type': 'trace'}]}
    async def collect():
        return [event async for event in context_stream.stream_answer(SimpleNamespace(id=7), '问题', snapshot, ['上一轮询问付款情况'])]
    events = asyncio.run(collect())
    assert len([e for e in events if 'event: delta' in e]) == 2
    assert '已授权事实' in captured['attachment_context'][0]
    assert [message.content for message in captured['messages']] == ['上一轮询问付款情况', '问题']
    done = json.loads(events[-1].split('data: ', 1)[1])
    assert done['answer'] == '第一段第二段' and done['context'] == snapshot['context']
    assert done['citations'] == snapshot['citations']


def test_stream_error_does_not_claim_done(monkeypatch):
    async def broken(*args, **kwargs):
        yield '部分'
        raise RuntimeError('private error')
    monkeypatch.setattr(context_stream, 'stream_chat', broken)
    async def collect():
        return [event async for event in context_stream.stream_answer(SimpleNamespace(id=7), '问题', {'answer': '事实', 'context': {}, 'citations': []})]
    events = asyncio.run(collect())
    assert 'event: error' in events[-1] and 'private error' not in events[-1]
    assert not any('event: done' in e for e in events)


def test_stream_endpoint_authorizes_and_returns_incremental_evidence(client, db_session, demo_password, monkeypatch):
    from uuid import uuid4
    from sqlalchemy import select
    from app.modules.system.model import User
    from app.modules.system import crud as system_crud
    from app.modules.suppliers.model import Supplier
    from app.modules.purchase_orders.model import PurchaseOrder
    from tests.conftest import login
    buyer = db_session.scalar(select(User).where(User.username == 'buyer'))
    headers = login(client, 'buyer', demo_password)
    tag = uuid4().hex[:10]
    supplier = Supplier(supplier_code='SSE'+tag, supplier_name='流式测试供应商')
    db_session.add(supplier); db_session.flush()
    order = PurchaseOrder(po_no='SSE'+tag, supplier_id=supplier.id, buyer_id=buyer.id,
        department_id=buyer.department_id, status='DRAFT', order_amount=0, currency_code='CNY')
    db_session.add(order); db_session.flush()
    captured = []
    async def fake_stream(data, settings, **kwargs):
        captured.append(kwargs['attachment_context'][0])
        yield '第一段'
        yield '第二段'
    monkeypatch.setattr(context_stream, 'stream_chat', fake_stream)
    url = '/api/v1/ai/context/stream'
    body = {'question': '请解释当前订单', 'context': {'object_type': 'purchase_order', 'object_id': order.id}}
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 200 and response.headers['content-type'].startswith('text/event-stream')
    assert response.text.count('event: delta') == 2 and 'event: done' in response.text
    assert order.po_no in captured[0] and '第一段' in response.text
    original = system_crud.get_user_permission_codes
    monkeypatch.setattr(system_crud, 'get_user_permission_codes', lambda db, uid: [p for p in original(db, uid) if p != 'procurement.orders.read'])
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 403
    assert len(captured) == 1


def test_floating_conversation_is_separate_from_workspace(db_session, demo_password, client):
    from sqlalchemy import select
    from app.core.errors import BusinessValidationError
    from app.modules.ai import conversation_store
    from app.modules.ai.schema import AIChatRequest, AIChatMessage
    from app.modules.system.model import User
    from tests.conftest import login
    import pytest
    login(client, 'buyer', demo_password)
    user = db_session.scalar(select(User).where(User.username == 'buyer'))
    data = AIChatRequest(messages=[AIChatMessage(role='user', content='浮窗隔离验收')], conversation_scene='FLOAT')
    conversation = conversation_store.ensure_conversation(db_session, user, data)
    db_session.flush()
    assert conversation.business_scene == 'FLOAT'
    assert conversation.id not in [item.id for item in conversation_store.list_conversations(db_session, user)[0]]
    with pytest.raises(BusinessValidationError):
        conversation_store.ensure_conversation(db_session, user, AIChatRequest(messages=data.messages, conversation_id=conversation.id))
