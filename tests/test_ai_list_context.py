"""采购订单列表上下文按当前权限和筛选条件重新读取。"""
from types import SimpleNamespace
from datetime import date
import pytest
from pydantic import ValidationError
from app.core.errors import AuthorizationError
from app.modules.ai import context
from app.modules.ai.schema import AIListContextAskRequest


def test_rejects_unregistered_filter_and_invalid_status():
    with pytest.raises(ValidationError):
        AIListContextAskRequest.model_validate({'question': '汇总', 'filters': {'buyer_id': 3}})
    with pytest.raises(ValidationError):
        AIListContextAskRequest.model_validate({'question': '汇总', 'filters': {'status': 'bogus'}})


def test_order_list_requires_permission(monkeypatch):
    monkeypatch.setattr(context, 'get_user_permission_codes', lambda *args: [])
    monkeypatch.setattr(context, 'get_user_role_codes', lambda *args: [])
    with pytest.raises(AuthorizationError):
        context.ask_order_list(None, SimpleNamespace(id=7), AIListContextAskRequest(question='汇总'))


def test_order_list_uses_scoped_service_and_reports_truncation(monkeypatch):
    from app.modules.purchase_orders import service
    monkeypatch.setattr(context, 'get_user_permission_codes', lambda *args: ['procurement.orders.read'])
    monkeypatch.setattr(context, 'get_user_role_codes', lambda *args: [])
    calls = []
    def get_list(db, user, **kwargs):
        calls.append(kwargs)
        return [SimpleNamespace(id=1, po_no='PO-1', status='APPROVING', expected_arrival_date=date(2026, 1, 1))], 102
    monkeypatch.setattr(service, 'list_orders', get_list)
    result = context.ask_order_list(None, SimpleNamespace(id=7), AIListContextAskRequest(question='哪些风险', filters={'status': 'APPROVING'}))
    assert calls == [{'keyword': None, 'status': 'APPROVING', 'page': 1, 'page_size': 100}]
    assert '102' in result['answer'] and '截断' in result['answer']
    assert result['context']['source_records'][0]['record_id'] == 1
    assert '风险' in result['answer']


def test_http_order_list_scope_filters_and_permission_revocation(client, db_session, demo_password, monkeypatch):
    from uuid import uuid4
    from decimal import Decimal
    from sqlalchemy import select
    from app.modules.system.model import Department, User
    from app.modules.system import crud as system_crud
    from app.modules.suppliers.model import Supplier
    from app.modules.purchase_orders.model import PurchaseOrder
    from tests.conftest import login
    actor = login(client, 'buyer', demo_password)
    buyer = db_session.scalar(select(User).where(User.username == 'buyer'))
    admin = db_session.scalar(select(User).where(User.username == 'system_admin'))
    tag = uuid4().hex[:10]
    department = Department(department_code='CTX'+tag, department_name='隔离部门')
    supplier = Supplier(supplier_code='CTX'+tag, supplier_name='上下文测试供应商')
    db_session.add_all([department, supplier]); db_session.flush()
    visible = PurchaseOrder(po_no='CTX'+tag+'A', supplier_id=supplier.id, buyer_id=buyer.id,
        department_id=buyer.department_id, status='APPROVING', order_amount=Decimal('0'), currency_code='CNY')
    hidden = PurchaseOrder(po_no='CTX'+tag+'B', supplier_id=supplier.id, buyer_id=admin.id,
        department_id=department.id, status='APPROVING', order_amount=Decimal('0'), currency_code='CNY')
    db_session.add_all([visible, hidden]); db_session.flush()
    url = '/api/v1/ai/context/purchase-orders'
    response = client.post(url, headers=actor, json={'question': '这些订单有什么风险', 'filters': {'keyword': 'CTX'+tag, 'status': 'APPROVING'}})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [source['record_id'] for source in payload['context']['source_records']] == [visible.id]
    assert hidden.po_no not in payload['answer']
    response = client.post(url, headers=actor, json={'question': '查询', 'filters': {'buyer_id': admin.id}})
    assert response.status_code == 422
    original = system_crud.get_user_permission_codes
    monkeypatch.setattr(system_crud, 'get_user_permission_codes', lambda db, user_id: [p for p in original(db, user_id) if p != 'procurement.orders.read'])
    response = client.post(url, headers=actor, json={'question': '查询'})
    assert response.status_code == 403
