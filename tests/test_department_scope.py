"""部门范围授权的安全边界。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select


def test_agent_statistics_respect_department_grants(db_session):
    import asyncio
    from sqlalchemy import func
    from app.modules.ai import text2sql
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant

    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    department = db_session.scalar(select(PurchaseOrder.department_id).where(
        PurchaseOrder.department_id.is_not(None)).limit(1))
    assert user is not None and department is not None
    db_session.add(UserDepartmentScope(user_id=user.id))
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=user.id, department_id=department))
    db_session.flush()
    result = asyncio.run(text2sql.run_text2sql(db_session, user,
        text2sql.Text2SQLRequest(question='统计采购订单数量'),
        planned_query=text2sql.QueryPlan(dataset='purchase_orders', metric='count'), intent_verified=True))
    expected = db_session.scalar(select(func.count()).select_from(PurchaseOrder).where(
        PurchaseOrder.department_id == department))
    assert result.rows == [{'metric_value': expected}]


@pytest.mark.parametrize('dataset', ('purchase_orders', 'purchase_requests', 'deliveries', 'quality_acceptances',
    'supplier_quotes', 'exceptions', 'finance_invoices', 'finance_payments'))
def test_agent_dataset_guards_accept_server_department_filters(db_session, dataset):
    from app.modules.ai import text2sql
    from app.modules.ai.catalog import CATALOG
    from app.modules.system.model import User

    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    plan = text2sql.QueryPlan(dataset=dataset, metric='count')
    statement = text2sql.build_statement(plan, db_session, user)
    text2sql._validate_scoped_statement(statement, db_session, CATALOG[dataset].tables, literal_binds=False)


@pytest.mark.parametrize('dataset', ('approved_requests_without_rfq', 'weekly_order_risks',
    'accepted_orders_finance_gaps', 'supplier_quote_delivery_profile'))
def test_agent_association_guards_accept_server_department_filters(db_session, dataset):
    from app.modules.ai import text2sql
    from app.modules.ai.catalog import CATALOG
    from app.modules.system.model import User

    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    plan = text2sql.QueryPlan(dataset=dataset, metric='records')
    statement = text2sql.build_statement(plan, db_session, user)
    text2sql._validate_scoped_statement(statement, db_session, CATALOG[dataset].tables, literal_binds=False)


def test_explicit_department_scope_is_an_upper_bound_and_admin_bypasses(db_session):
    from app.modules.system.model import UserDepartmentScope, UserDepartmentGrant
    from app.modules.system.data_scope import department_scope_condition
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.system.model import User

    user = db_session.scalar(select(User).where(User.username == 'buyer'))
    assert user is not None
    department_ids = list(db_session.scalars(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None)).distinct().limit(2)))
    assert len(department_ids) == 2
    db_session.add(UserDepartmentScope(user_id=user.id))
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=user.id, department_id=department_ids[0]))
    db_session.flush()
    visible = set(db_session.scalars(select(PurchaseOrder.department_id).where(department_scope_condition(user, {'BUYER'}, PurchaseOrder.department_id))).all())
    assert visible <= {department_ids[0]}
    all_departments = set(db_session.scalars(select(PurchaseOrder.department_id).where(department_scope_condition(user, {'SYS_ADMIN', 'BUYER'}, PurchaseOrder.department_id))).all())
    assert department_ids[1] in all_departments


def test_department_cap_applies_to_manager_orders_and_finance(db_session):
    from app.core.errors import ResourceNotFoundError
    from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.purchase_orders import service as orders
    from app.modules.finance import service as finance
    from app.modules.finance.model import FinanceInvoice
    import pytest

    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    assert manager is not None
    departments = list(db_session.scalars(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None)).distinct().limit(2)))
    assert len(departments) == 2
    db_session.add(UserDepartmentScope(user_id=manager.id))
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=manager.id, department_id=departments[0]))
    db_session.flush()
    hidden = db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.department_id == departments[1]).limit(1))
    with pytest.raises(ResourceNotFoundError):
        orders.read_order(db_session, manager, hidden.id)
    with pytest.raises(ResourceNotFoundError):
        orders.get_order(db_session, manager, hidden.id)
    visible = list(db_session.scalars(select(PurchaseOrder.department_id).where(orders.order_read_condition(manager, {'PROCUREMENT_MANAGER'}))).all())
    assert set(visible) <= {departments[0]}
    hidden_finance = list(db_session.scalars(select(FinanceInvoice.id).where(FinanceInvoice.po_id == hidden.id, finance._scope_condition(db_session, manager, FinanceInvoice))).all())
    assert hidden_finance == []


def test_replenishment_cap_blocks_other_department_for_manager(db_session):
    from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant
    from app.modules.replenishments import service
    from app.modules.replenishments.model import ReplenishmentRequest
    from app.modules.purchase_orders.model import PurchaseOrder
    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    row = db_session.scalar(select(ReplenishmentRequest).where(ReplenishmentRequest.source_po_id.is_not(None)).limit(1))
    if manager is None or row is None:
        import pytest
        pytest.skip('缺少关联订单的补货样本')
    order = db_session.get(PurchaseOrder, row.source_po_id)
    other_dept = db_session.scalar(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None), PurchaseOrder.department_id != order.department_id).limit(1))
    if other_dept is None:
        import pytest
        pytest.skip('缺少其他部门样本')
    db_session.add(UserDepartmentScope(user_id=manager.id))
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=manager.id, department_id=other_dept))
    db_session.flush()
    from app.core.errors import ResourceNotFoundError
    import pytest
    with pytest.raises(ResourceNotFoundError):
        service.get_replenishment(db_session, manager, row.id)


def test_return_cap_blocks_other_department_for_manager(db_session):
    from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant
    from app.modules.inventory_returns import service
    from app.modules.inventory_returns.model import InventoryReturnRequest
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.core.errors import ResourceNotFoundError
    import pytest
    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    row = db_session.scalar(select(InventoryReturnRequest).where(InventoryReturnRequest.po_id.is_not(None)).limit(1))
    if manager is None or row is None:
        pytest.skip('缺少关联订单的退货样本')
    order = db_session.get(PurchaseOrder, row.po_id)
    other = db_session.scalar(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None), PurchaseOrder.department_id != order.department_id).limit(1))
    if other is None:
        pytest.skip('缺少其他部门样本')
    db_session.add(UserDepartmentScope(user_id=manager.id))
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=manager.id, department_id=other))
    db_session.flush()
    with pytest.raises(ResourceNotFoundError):
        service.get_return(db_session, manager, row.id)


def test_exception_owner_cannot_bypass_department_cap(db_session):
    import pytest
    from app.core.errors import ResourceNotFoundError
    from app.modules.operation_exceptions.model import OperationException
    from app.modules.operation_exceptions import service
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant
    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    row = db_session.scalar(select(OperationException).where(OperationException.po_id.is_not(None)).limit(1))
    if manager is None or row is None:
        pytest.skip('缺少订单异常样本')
    order = db_session.get(PurchaseOrder, row.po_id)
    other = db_session.scalar(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None), PurchaseOrder.department_id != order.department_id).limit(1))
    if other is None:
        pytest.skip('缺少其他部门样本')
    row.owner_id = manager.id
    db_session.add(UserDepartmentScope(user_id=manager.id))
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=manager.id, department_id=other))
    db_session.flush()
    with pytest.raises(ResourceNotFoundError):
        service.get_exception(db_session, manager, row.id)


def test_exception_source_cannot_bypass_department_cap_without_link_columns(db_session):
    import pytest
    from app.core.errors import ResourceNotFoundError
    from app.modules.deliveries.model import Delivery
    from app.modules.operation_exceptions.model import OperationException
    from app.modules.operation_exceptions import service
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.quality_acceptances.model import QualityAcceptance
    from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant

    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    source = db_session.scalar(select(QualityAcceptance).join(Delivery).join(PurchaseOrder).where(
        PurchaseOrder.department_id.is_not(None)).limit(1))
    if manager is None or source is None:
        pytest.skip('缺少质量验收样本')
    order = db_session.get(PurchaseOrder, db_session.get(Delivery, source.delivery_id).po_id)
    other = db_session.scalar(select(PurchaseOrder.department_id).where(
        PurchaseOrder.department_id.is_not(None), PurchaseOrder.department_id != order.department_id).limit(1))
    if other is None:
        pytest.skip('缺少其他部门样本')
    row = OperationException(exception_no='TEST-SCOPE-SOURCE', exception_type='OTHER',
        source_type='QUALITY_ACCEPTANCE', source_id=source.id, owner_id=manager.id,
        responsible_department_id=other, description='范围测试')
    db_session.add_all([row, UserDepartmentScope(user_id=manager.id)])
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=manager.id, department_id=other))
    db_session.flush()
    with pytest.raises(ResourceNotFoundError):
        service.get_exception(db_session, manager, row.id)


def test_scoped_user_gets_department_dashboard_without_global_inventory(client, db_session, demo_password):
    from tests.conftest import login
    from sqlalchemy import func
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant
    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    assert user is not None
    headers = login(client, 'procurement_manager', demo_password)
    db_session.add(UserDepartmentScope(user_id=user.id))
    db_session.flush()
    department_id = db_session.scalar(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None)).limit(1))
    db_session.add(UserDepartmentGrant(user_id=user.id, department_id=department_id))
    db_session.flush()
    expected = db_session.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.department_id == department_id))
    response = client.get('/api/v1/dashboard/overview', headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['purchase_orders_total'] == expected
    assert response.json()['inventory_quantity'] is None
    assert response.json()['expiry_alerts'] is None
    report = client.get('/api/v1/dashboard/report', headers=headers)
    assert report.status_code == 200, report.text
    assert report.json()['inventory_available'] is False
    assert report.json()['inventory_alerts'] == [] and report.json()['inventory_costs'] == []
    assert sum(item['order_count'] for item in report.json()['order_statuses']) == expected
    assert sum(item['order_count'] for item in report.json()['supplier_performance']) == expected


def test_global_briefing_notification_excludes_scoped_recipients(db_session):
    from app.modules.notifications.service import notify_users
    from app.modules.system.model import User, UserDepartmentScope
    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    assert manager is not None
    db_session.add(UserDepartmentScope(user_id=manager.id))
    db_session.flush()
    rows = notify_users(db_session, recipient_ids=[manager.id], exclude_scoped=True,
                        notification_type='AI_BRIEFING', title='测试', content='全局金额')
    assert manager.id not in {row.recipient_id for row in rows}


def test_exception_task_creation_cannot_bypass_department_cap(db_session):
    import pytest
    from app.core.errors import ResourceNotFoundError
    from app.modules.operation_exceptions.model import OperationException
    from app.modules.operation_exceptions import service
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant
    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    row = db_session.scalar(select(OperationException).where(OperationException.po_id.is_not(None)).limit(1))
    if manager is None or row is None:
        pytest.skip('缺少订单异常样本')
    order = db_session.get(PurchaseOrder, row.po_id)
    other = db_session.scalar(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None), PurchaseOrder.department_id != order.department_id).limit(1))
    if other is None:
        pytest.skip('缺少其他部门样本')
    row.owner_id = manager.id
    db_session.add(UserDepartmentScope(user_id=manager.id))
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=manager.id, department_id=other))
    db_session.flush()
    with pytest.raises(ResourceNotFoundError):
        service.get_exception_for_task_creation(db_session, manager, row.id)


def test_department_scope_redacts_old_notification_content(client, db_session, demo_password):
    from tests.conftest import login
    from app.modules.notifications.model import Notification
    from app.modules.system.model import User, UserDepartmentScope
    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    headers = login(client, 'procurement_manager', demo_password)
    notice = Notification(recipient_id=manager.id, notification_type='AI_BRIEFING', title='跨部门敏感标题', content='跨部门敏感金额', is_read=0)
    db_session.add(notice)
    db_session.add(UserDepartmentScope(user_id=manager.id))
    db_session.flush()
    response = client.get('/api/v1/notifications', headers=headers, params={'page_size': 100})
    assert response.status_code == 200, response.text
    item = next(item for item in response.json()['items'] if item['id'] == notice.id)
    assert '跨部门敏感' not in item['title'] and '跨部门敏感' not in item['content']
    assert item['related_id'] is None
    marked = client.patch(f'/api/v1/notifications/{notice.id}/read', headers=headers)
    assert marked.status_code == 200, marked.text
    assert '跨部门敏感' not in marked.text


def test_exception_task_details_cannot_bypass_department_cap(db_session):
    import pytest
    from app.core.errors import ResourceNotFoundError
    from app.modules.operation_exceptions.model import OperationException, OperationTask
    from app.modules.operation_exceptions import service
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant
    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    row = db_session.scalar(select(OperationException).where(OperationException.po_id.is_not(None)).limit(1))
    if manager is None or row is None:
        pytest.skip('缺少订单异常样本')
    order = db_session.get(PurchaseOrder, row.po_id)
    other = db_session.scalar(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None), PurchaseOrder.department_id != order.department_id).limit(1))
    if other is None:
        pytest.skip('缺少其他部门样本')
    row.owner_id = manager.id
    task = OperationTask(exception_id=row.id, title='测试范围', assignee_id=manager.id)
    db_session.add(task)
    db_session.add(UserDepartmentScope(user_id=manager.id))
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=manager.id, department_id=other))
    db_session.flush()
    with pytest.raises(ResourceNotFoundError):
        service.get_task(db_session, manager, task.id)
    with pytest.raises(ResourceNotFoundError):
        service.list_tasks(db_session, manager, row.id, status=None, page=1, page_size=20)


def test_scope_change_hides_previously_created_ai_conversation(client, db_session, demo_password):
    from tests.conftest import login
    from app.modules.ai.model import AIConversation, AIMessage
    from app.modules.system.model import User, UserDepartmentScope
    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    headers = login(client, 'procurement_manager', demo_password)
    conversation = AIConversation(user_id=manager.id, title='旧范围敏感标题', business_scene='GENERAL', permission_snapshot={}, status='ACTIVE')
    db_session.add(conversation)
    db_session.flush()
    db_session.add(AIMessage(conversation_id=conversation.id, message_role='ASSISTANT', content='旧范围敏感金额'))
    db_session.add(UserDepartmentScope(user_id=manager.id))
    db_session.flush()
    listing = client.get('/api/v1/ai/conversations', headers=headers)
    assert listing.status_code == 200, listing.text
    assert '旧范围敏感' not in listing.text
    messages = client.get(f'/api/v1/ai/conversations/{conversation.id}/messages', headers=headers)
    assert messages.status_code in (400, 403, 404), messages.text


def test_new_scoped_conversation_invalidated_when_departments_change(db_session):
    import pytest
    from app.core.errors import BusinessValidationError
    from app.modules.ai import conversation_store
    from app.modules.ai.model import AIConversation
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant
    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    departments = list(db_session.scalars(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None)).distinct().limit(2)))
    assert user is not None and len(departments) == 2
    db_session.add(UserDepartmentScope(user_id=user.id))
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=user.id, department_id=departments[0]))
    db_session.flush()
    conversation = AIConversation(user_id=user.id, title='授权内会话', business_scene='GENERAL', permission_snapshot=conversation_store.permission_snapshot(db_session, user), status='ACTIVE')
    db_session.add(conversation)
    db_session.flush()
    assert conversation_store.get_owned_conversation(db_session, user, conversation.id).id == conversation.id
    db_session.add(UserDepartmentGrant(user_id=user.id, department_id=departments[1]))
    db_session.flush()
    with pytest.raises(BusinessValidationError):
        conversation_store.get_owned_conversation(db_session, user, conversation.id)


def test_scoped_user_cannot_read_or_export_old_agent_task(db_session):
    import pytest
    from datetime import datetime
    from app.core.errors import ResourceNotFoundError
    from app.modules.ai import agent_runtime
    from app.modules.ai.model import AIAgentTask
    from app.modules.system.model import User, UserDepartmentScope
    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    task = AIAgentTask(id='scope-history-test-001', user_id=user.id, status='SUCCEEDED', revision=0,
        payload={'messages': ['旧敏感信息'], 'trace': []}, reply='旧敏感结果', created_at=datetime.now(), updated_at=datetime.now())
    db_session.add(task)
    db_session.add(UserDepartmentScope(user_id=user.id))
    db_session.flush()
    with pytest.raises(ResourceNotFoundError):
        agent_runtime.get_task(db_session, user, task.id)
    with pytest.raises(ResourceNotFoundError):
        agent_runtime.export_task_csv(db_session, user, task.id)
    page = agent_runtime.list_tasks(db_session, user, page=1, page_size=100)
    matching = [row for row in page.items if row.id == task.id]
    assert matching and '旧敏感' not in matching[0].reply


def test_scoped_briefing_snapshot_uses_department_data(db_session):
    from app.modules.ai import briefing
    from app.modules.dashboard.service import get_department_overview
    from app.modules.system.model import User, UserDepartmentScope
    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    db_session.add(UserDepartmentScope(user_id=user.id))
    db_session.flush()
    snapshot = briefing.build_snapshot(db_session, user=user)
    assert snapshot['overview']['purchase_orders_total'] == get_department_overview(db_session, user)['purchase_orders_total'] == 0
    assert snapshot['overview']['inventory_quantity'] is None


def test_old_action_proposal_is_unavailable_after_department_scope_change(db_session):
    import pytest
    from app.core.errors import ResourceNotFoundError
    from app.modules.ai import action_proposals
    from app.modules.system.model import User, UserDepartmentScope
    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    db_session.add(UserDepartmentScope(user_id=user.id))
    db_session.flush()
    with pytest.raises(ResourceNotFoundError):
        action_proposals._require_proposal_department_scope(db_session, user, SimpleNamespace(department_scope_snapshot=None))


def test_admin_can_set_department_scope_and_user_cannot_modify(client, db_session, demo_password):
    from tests.conftest import login
    from app.modules.system.model import User, Department
    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    department = db_session.scalar(select(Department).where(Department.status == 'ACTIVE').limit(1))
    assert user and department
    admin = login(client, 'system_admin', demo_password)
    manager = login(client, 'procurement_manager', demo_password)
    url = f'/api/v1/system/users/{user.id}/department-scope'
    denied = client.put(url, headers=manager, json={'enabled': True, 'department_ids': [department.id]})
    assert denied.status_code == 403, denied.text
    version = user.token_version
    changed = client.put(url, headers=admin, json={'enabled': True, 'department_ids': [department.id]})
    assert changed.status_code == 200, changed.text
    assert changed.json() == {'enabled': True, 'department_ids': [department.id]}
    db_session.refresh(user)
    assert user.token_version == version + 1
    assert client.get(url, headers=admin).json() == changed.json()
    reset = client.put(url, headers=admin, json={'enabled': False, 'department_ids': []})
    assert reset.status_code == 200 and reset.json()['enabled'] is False


def test_finance_multirole_department_cap_is_not_widened(db_session):
    from app.core.errors import ResourceNotFoundError
    from app.modules.finance import service as finance
    from app.modules.finance.model import FinanceInvoice
    from app.modules.purchase_orders import service as orders
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.system.model import Role, User, UserRole, UserDepartmentScope, UserDepartmentGrant
    import pytest
    user = db_session.scalar(select(User).where(User.username == 'finance_manager'))
    buyer = db_session.scalar(select(Role).where(Role.role_code == 'BUYER'))
    departments = list(db_session.scalars(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None)).distinct().limit(2)))
    assert user and buyer and len(departments) == 2
    if db_session.get(UserRole, (user.id, buyer.id)) is None:
        db_session.add(UserRole(user_id=user.id, role_id=buyer.id))
    db_session.add(UserDepartmentScope(user_id=user.id))
    db_session.flush()
    db_session.add(UserDepartmentGrant(user_id=user.id, department_id=departments[0]))
    db_session.flush()
    hidden = db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.department_id == departments[1]).limit(1))
    with pytest.raises(ResourceNotFoundError):
        orders.read_order(db_session, user, hidden.id)
    with pytest.raises(ResourceNotFoundError):
        finance._require_finance_scope(db_session, user, hidden.id)
    assert not db_session.scalars(select(FinanceInvoice.id).where(FinanceInvoice.po_id == hidden.id, finance._scope_condition(db_session, user, FinanceInvoice))).all()


def test_scoped_manager_does_not_bypass_other_warehouse_owner(db_session):
    import pytest
    from app.modules.inventory import service
    from app.modules.inventory.model import Warehouse
    from app.modules.system.model import User, UserDepartmentScope
    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    other = db_session.scalar(select(User).where(User.username == 'buyer'))
    warehouse = db_session.scalar(select(Warehouse).where(Warehouse.status == 'ACTIVE').limit(1))
    assert manager and other and warehouse
    warehouse.manager_id = other.id
    db_session.add(UserDepartmentScope(user_id=manager.id))
    db_session.flush()
    assert not service._can_access_warehouse(db_session, manager, warehouse.id)
    assert warehouse.id not in service.accessible_warehouse_ids(db_session, manager)


def test_configured_manager_http_cannot_read_or_export_other_department(client, db_session, demo_password):
    from tests.conftest import login
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.system.model import User, Role, Permission, RolePermission
    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    departments = list(db_session.scalars(select(PurchaseOrder.department_id).where(PurchaseOrder.department_id.is_not(None)).distinct().limit(2)))
    assert manager and len(departments) == 2
    role = db_session.scalar(select(Role).where(Role.role_code == 'PROCUREMENT_MANAGER'))
    permission = db_session.scalar(select(Permission).where(Permission.permission_code == 'procurement.orders.export'))
    assert role and permission
    if db_session.get(RolePermission, (role.id, permission.id)) is None:
        db_session.add(RolePermission(role_id=role.id, permission_id=permission.id))
        db_session.flush()
    hidden = db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.department_id == departments[1]).limit(1))
    admin = login(client, 'system_admin', demo_password)
    configured = client.put(f'/api/v1/system/users/{manager.id}/department-scope', headers=admin, json={'enabled': True, 'department_ids': [departments[0]]})
    assert configured.status_code == 200, configured.text
    manager_headers = login(client, 'procurement_manager', demo_password)
    assert client.get(f'/api/v1/purchase-orders/{hidden.id}', headers=manager_headers).status_code == 404
    denied_export = client.post('/api/v1/batch/procurement.orders/export', headers=manager_headers, json={'ids': [hidden.id]})
    assert denied_export.status_code == 404, denied_export.text
    assert client.get(f'/api/v1/purchase-orders/{hidden.id}', headers=admin).status_code == 200


def test_scope_rejects_admin_and_supplier_accounts(client, db_session, demo_password):
    from tests.conftest import login
    from app.modules.system.model import User
    headers = login(client, 'system_admin', demo_password)
    admin = db_session.scalar(select(User).where(User.username == 'system_admin'))
    supplier = db_session.scalar(select(User).where(User.username == 'supplier_portal'))
    assert admin is not None
    result = client.put(f'/api/v1/system/users/{admin.id}/department-scope', headers=headers, json={'enabled': True, 'department_ids': []})
    assert result.status_code == 400, result.text
    if supplier is not None:
        result = client.put(f'/api/v1/system/users/{supplier.id}/department-scope', headers=headers, json={'enabled': True, 'department_ids': []})
        assert result.status_code == 400, result.text
