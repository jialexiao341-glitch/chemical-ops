"""显式仓库授权不得被公共仓库、申请人或其他角色绕过。"""

from types import SimpleNamespace
import pytest
from sqlalchemy import select


def test_configured_warehouse_scope_limits_access_and_admin_bypasses(db_session):
    from app.modules.inventory.model import Warehouse
    from app.modules.inventory import service
    from app.modules.system.model import User, UserWarehouseScope, UserWarehouseGrant

    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    warehouses = list(db_session.scalars(select(Warehouse).where(Warehouse.status == 'ACTIVE').limit(2)))
    assert user is not None and len(warehouses) == 2
    if db_session.get(UserWarehouseScope, user.id) is None:
        db_session.add(UserWarehouseScope(user_id=user.id))
    db_session.flush()
    db_session.add(UserWarehouseGrant(user_id=user.id, warehouse_id=warehouses[0].id))
    db_session.flush()
    assert service.accessible_warehouse_ids(db_session, user) == {warehouses[0].id}
    assert service._can_access_warehouse(db_session, user, warehouses[0].id)
    assert not service._can_access_warehouse(db_session, user, warehouses[1].id)
    from app.core.errors import ResourceNotFoundError
    with pytest.raises(ResourceNotFoundError):
        service._validate_transfer_warehouse_scope(db_session, user, [SimpleNamespace(
            source_warehouse_id=warehouses[0].id, target_warehouse_id=warehouses[1].id)])
    db_session.delete(db_session.get(UserWarehouseGrant, (user.id, warehouses[0].id)))
    db_session.flush()
    assert service.accessible_warehouse_ids(db_session, user) == set()
    admin = db_session.scalar(select(User).where(User.username == 'system_admin'))
    assert service.accessible_warehouse_ids(db_session, admin) is None


def test_only_admin_can_configure_warehouse_scope(client, db_session, demo_password):
    from tests.conftest import login
    from app.modules.inventory.model import Warehouse
    from app.modules.system.model import User

    admin = login(client, 'system_admin', demo_password)
    manager = login(client, 'procurement_manager', demo_password)
    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    warehouse = db_session.scalar(select(Warehouse).where(Warehouse.status == 'ACTIVE'))
    assert user and warehouse
    url = f'/api/v1/system/users/{user.id}/warehouse-scope'
    assert client.put(url, headers=manager, json={'enabled': True, 'warehouse_ids': [warehouse.id]}).status_code == 403
    response = client.put(url, headers=admin, json={'enabled': True, 'warehouse_ids': [warehouse.id]})
    assert response.status_code == 200, response.text
    assert response.json() == {'enabled': True, 'warehouse_ids': [warehouse.id]}
    assert client.get(url, headers=admin).json() == response.json()
    assert client.put(url, headers=admin, json={'enabled': True, 'warehouse_ids': []}).json() == {'enabled': True, 'warehouse_ids': []}
    assert client.put(url, headers=admin, json={'enabled': False, 'warehouse_ids': []}).status_code == 400
    assert client.get(url, headers=admin).json() == {'enabled': True, 'warehouse_ids': []}


def test_unconfigured_user_has_no_implicit_warehouse_access(db_session, monkeypatch):
    from app.modules.inventory.model import Warehouse
    from app.modules.inventory import service
    from app.modules.system.model import UserWarehouseScope
    user = SimpleNamespace(id=-12345)
    monkeypatch.setattr(service, 'get_user_role_codes', lambda *_: ['PROCUREMENT_MANAGER'])
    assert db_session.get(UserWarehouseScope, user.id) is None
    assert service.accessible_warehouse_ids(db_session, user) == set()
    warehouse = db_session.scalar(select(Warehouse).where(Warehouse.manager_id.is_(None), Warehouse.status == 'ACTIVE'))
    if warehouse:
        assert not service._can_access_warehouse(db_session, user, warehouse.id)


def test_disabled_warehouse_is_removed_from_scope_snapshot(db_session):
    from app.modules.inventory.model import Warehouse
    from app.modules.system.data_scope import warehouse_scope_snapshot
    from app.modules.system.model import User, UserWarehouseScope, UserWarehouseGrant

    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    warehouse = db_session.scalar(select(Warehouse).where(Warehouse.status == 'ACTIVE').limit(1))
    assert user and warehouse
    if db_session.get(UserWarehouseScope, user.id) is None:
        db_session.add(UserWarehouseScope(user_id=user.id))
        db_session.flush()
    if db_session.get(UserWarehouseGrant, (user.id, warehouse.id)) is None:
        db_session.add(UserWarehouseGrant(user_id=user.id, warehouse_id=warehouse.id))
    db_session.flush()
    assert warehouse.id in warehouse_scope_snapshot(db_session, user)
    warehouse.status = 'INACTIVE'
    db_session.flush()
    assert warehouse.id not in warehouse_scope_snapshot(db_session, user)


def test_warehouse_scope_change_invalidates_old_agent_task_and_proposal(monkeypatch):
    from app.core.errors import ResourceNotFoundError
    from app.modules.ai import agent_runtime, action_proposals
    from app.modules.system import data_scope

    monkeypatch.setattr(data_scope, 'department_scope_snapshot', lambda *_: None)
    monkeypatch.setattr(data_scope, 'warehouse_scope_snapshot', lambda *_: [2])
    user = SimpleNamespace(id=7)
    task = SimpleNamespace(payload={'warehouse_scope': [1]})
    proposal = SimpleNamespace(department_scope_snapshot=None, warehouse_scope_snapshot=[1])
    with pytest.raises(ResourceNotFoundError):
        agent_runtime._require_task_department_scope(None, user, task)
    with pytest.raises(ResourceNotFoundError):
        action_proposals._require_proposal_department_scope(None, user, proposal)
    state = SimpleNamespace(warehouse_scope=[1])
    with pytest.raises(agent_runtime.TaskInterrupted):
        agent_runtime._persist(None, user, state)


def test_warehouse_scope_change_invalidates_old_conversation(monkeypatch):
    from app.core.errors import BusinessValidationError
    from app.modules.ai import conversation_store
    from app.modules.system import data_scope

    monkeypatch.setattr(data_scope, 'department_scope_snapshot', lambda *_: None)
    monkeypatch.setattr(data_scope, 'warehouse_scope_snapshot', lambda *_: [2])
    conversation = SimpleNamespace(permission_snapshot={'warehouse_scope': [1]})
    db = SimpleNamespace(scalar=lambda *_: conversation)
    with pytest.raises(BusinessValidationError, match='仓库授权已变化'):
        conversation_store.get_owned_conversation(db, SimpleNamespace(id=7), 1)


def test_exception_owner_cannot_bypass_empty_warehouse_scope(db_session):
    from app.modules.inventory.model import InventoryBalance
    from app.modules.operation_exceptions.model import OperationException
    from app.modules.operation_exceptions import service
    from app.modules.system.model import User, UserWarehouseScope

    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    balance = db_session.scalar(select(InventoryBalance).limit(1))
    assert user is not None and balance is not None
    if db_session.get(UserWarehouseScope, user.id) is None:
        db_session.add(UserWarehouseScope(user_id=user.id))
    row = OperationException(exception_no='TEST-WH-SCOPE', exception_type='OTHER',
        source_type='INVENTORY_BATCH', source_id=balance.batch_id, owner_id=user.id, description='范围测试')
    db_session.add(row)
    db_session.flush()
    condition = service._exception_record_scope_condition(db_session, user)
    assert db_session.scalar(select(OperationException.id).where(OperationException.id == row.id, condition)) is None


def test_agent_association_sql_accepts_warehouse_scoped_exception_filter(db_session):
    from app.modules.ai import text2sql
    from app.modules.ai.catalog import CATALOG
    from app.modules.system.model import User, UserWarehouseScope

    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    if db_session.get(UserWarehouseScope, user.id) is None:
        db_session.add(UserWarehouseScope(user_id=user.id))
    db_session.flush()
    for dataset, metric in [('exceptions', 'count'), ('supplier_quote_delivery_profile', 'records')]:
        plan = text2sql.QueryPlan(dataset=dataset, metric=metric)
        statement = text2sql.build_statement(plan, db_session, user)
        text2sql._validate_scoped_statement(statement, db_session, CATALOG[dataset].tables, literal_binds=False)


@pytest.mark.parametrize('kind', ['issue', 'transfer', 'stocktake'])
def test_manager_can_read_other_users_record_only_with_warehouse_access(monkeypatch, kind):
    from app.core.errors import ResourceNotFoundError
    from app.modules.inventory import service

    manager = SimpleNamespace(id=7)
    monkeypatch.setattr(service, 'get_user_role_codes', lambda *_: ['PROCUREMENT_MANAGER'])
    monkeypatch.setattr(service, '_can_access_all_warehouses', lambda *_: False)
    monkeypatch.setattr(service, '_must_check_warehouse', lambda *_: True)
    allowed = {1, 2}
    def check(_db, _user, warehouse_id):
        if warehouse_id not in allowed:
            raise ResourceNotFoundError('仓库不存在')
    monkeypatch.setattr(service, '_require_warehouse_scope', check)
    item = SimpleNamespace(warehouse_id=1, source_warehouse_id=1, target_warehouse_id=2)
    record = SimpleNamespace(applicant_id=8, items=[item], warehouse_id=1)
    monkeypatch.setattr(service, f'_require_{kind}', lambda *_args, **_kwargs: record)
    getter = getattr(service, f'_get_{kind}_for_user')
    assert getter(None, manager, 10) is record
    allowed.remove(2 if kind == 'transfer' else 1)
    with pytest.raises(ResourceNotFoundError):
        getter(None, manager, 10)


@pytest.mark.parametrize('kind', ['issue', 'transfer', 'stocktake'])
def test_manager_list_keeps_authorized_warehouse_filter(monkeypatch, kind):
    from app.modules.inventory import service
    manager = SimpleNamespace(id=7)
    monkeypatch.setattr(service, 'get_user_role_codes', lambda *_: ['PROCUREMENT_MANAGER'])
    monkeypatch.setattr(service, '_can_access_all_warehouses', lambda *_: False)
    monkeypatch.setattr(service, 'accessible_warehouse_ids', lambda *_: {1, 2})
    captured = {}
    monkeypatch.setattr(service.crud, f'list_{kind}_requests', lambda _db, **kw: captured.update(kw) or ([], 0))
    getattr(service, f'list_{kind}_requests')(None, manager, status=None, page=1, page_size=20)
    assert captured['applicant_id'] is None
    assert captured['warehouse_ids'] == {1, 2}


def test_supplier_internal_mixed_role_is_warehouse_restricted(monkeypatch):
    from app.modules.system import data_scope
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(data_scope, 'get_user_role_codes', lambda *_: ['SUPPLIER_PORTAL', 'WAREHOUSE'])
    assert data_scope.is_warehouse_restricted(None, user)
    monkeypatch.setattr(data_scope, 'get_user_role_codes', lambda *_: ['SUPPLIER_PORTAL'])
    assert not data_scope.is_warehouse_restricted(None, user)
    monkeypatch.setattr(data_scope, 'get_user_role_codes', lambda *_: ['SUPPLIER_PORTAL', 'WAREHOUSE', 'SYS_ADMIN'])
    assert not data_scope.is_warehouse_restricted(None, user)


def test_stocktake_execute_requires_independent_permission(client, db_session, demo_password, monkeypatch):
    from tests.conftest import login
    from app.modules.system import crud

    headers = login(client, 'warehouse_receiver', demo_password)
    permissions = ['warehouse.inventory.stocktake.write']
    monkeypatch.setattr(crud, 'get_user_permission_codes', lambda *_: permissions)
    url = '/api/v1/inventory/stocktakes/999999999/execute'
    assert client.post(url, headers=headers).status_code == 403
    permissions[:] = ['warehouse.inventory.stocktake.execute']
    assert client.post(url, headers=headers).status_code == 404


def test_manager_approves_other_issue_only_with_permission_and_scope(client, db_session, demo_password, monkeypatch):
    from uuid import uuid4
    from app.modules.inventory.model import InventoryBalance, InventoryIssueItem, InventoryIssueRequest
    from app.modules.system import crud
    from app.modules.system.model import User, UserWarehouseGrant
    from tests.conftest import login, grant_test_warehouse

    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    applicant = db_session.scalar(select(User).where(User.username == 'buyer'))
    balance = db_session.scalar(select(InventoryBalance).where(InventoryBalance.quantity > 0).limit(1))
    assert manager and applicant and balance
    grant = db_session.get(UserWarehouseGrant, (manager.id, balance.warehouse_id))
    if grant:
        db_session.delete(grant)
        db_session.flush()
    issue = InventoryIssueRequest(issue_no=f'TEST-MGR-{uuid4().hex[:12]}', applicant_id=applicant.id,
                                  purpose='权限测试', status='SUBMITTED')
    issue.items = [InventoryIssueItem(line_no=1, product_id=balance.product_id, warehouse_id=balance.warehouse_id,
        location_id=balance.location_id, batch_id=balance.batch_id, unit_id=balance.unit_id, requested_quantity=1)]
    db_session.add(issue)
    db_session.flush()
    headers = login(client, 'procurement_manager', demo_password)
    permissions = []
    monkeypatch.setattr(crud, 'get_user_permission_codes', lambda *_: permissions)
    url = f'/api/v1/inventory/issue-requests/{issue.id}/approve'
    assert client.post(url, headers=headers).status_code == 403
    permissions.append('warehouse.inventory.issue.approve')
    assert client.post(url, headers=headers).status_code == 404
    grant_test_warehouse(db_session, manager.id, balance.warehouse_id)
    response = client.post(url, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'APPROVED'
    own = InventoryIssueRequest(issue_no=f'TEST-OWN-{uuid4().hex[:12]}', applicant_id=manager.id,
                                purpose='职责分离测试', status='SUBMITTED')
    own.items = [InventoryIssueItem(line_no=1, product_id=balance.product_id, warehouse_id=balance.warehouse_id,
        location_id=balance.location_id, batch_id=balance.batch_id, unit_id=balance.unit_id, requested_quantity=1)]
    db_session.add(own)
    db_session.flush()
    blocked = client.post(f'/api/v1/inventory/issue-requests/{own.id}/approve', headers=headers)
    assert blocked.status_code == 400
    assert '本人' in blocked.json()['detail']


def test_admin_can_configure_mixed_supplier_internal_account(client, db_session, demo_password):
    from app.modules.inventory.model import Warehouse
    from app.modules.system.model import Role, User, UserRole
    from tests.conftest import login

    headers = login(client, 'system_admin', demo_password)
    user = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    supplier = db_session.scalar(select(User).where(User.username == 'supplier_portal'))
    portal_role = db_session.scalar(select(Role).where(Role.role_code == 'SUPPLIER_PORTAL'))
    warehouse = db_session.scalar(select(Warehouse).where(Warehouse.status == 'ACTIVE'))
    assert user and supplier and portal_role and warehouse
    if db_session.get(UserRole, (user.id, portal_role.id)) is None:
        db_session.add(UserRole(user_id=user.id, role_id=portal_role.id))
        db_session.flush()
    payload = {'enabled': True, 'warehouse_ids': [warehouse.id]}
    mixed = client.put(f'/api/v1/system/users/{user.id}/warehouse-scope', headers=headers, json=payload)
    assert mixed.status_code == 200, mixed.text
    assert mixed.json() == payload
    from app.modules.inventory.service import accessible_warehouse_ids
    from app.modules.system.data_scope import is_warehouse_restricted
    assert is_warehouse_restricted(db_session, user)
    assert accessible_warehouse_ids(db_session, user) == {warehouse.id}
    pure = client.put(f'/api/v1/system/users/{supplier.id}/warehouse-scope', headers=headers, json=payload)
    assert pure.status_code == 400


def test_pure_supplier_cannot_reuse_old_internal_warehouse_grant(db_session):
    from app.modules.inventory.model import Warehouse
    from app.modules.inventory import service
    from app.modules.system.model import User
    from tests.conftest import grant_test_warehouse

    supplier = db_session.scalar(select(User).where(User.username == 'supplier_portal'))
    warehouse = db_session.scalar(select(Warehouse).where(Warehouse.status == 'ACTIVE'))
    assert supplier and warehouse
    grant_test_warehouse(db_session, supplier.id, warehouse.id)
    assert service.accessible_warehouse_ids(db_session, supplier) == set()
    assert not service._can_access_warehouse(db_session, supplier, warehouse.id)


def test_global_notification_excludes_mixed_supplier_internal_user(db_session):
    from app.modules.notifications.service import notify_users
    from app.modules.system.model import Role, User, UserRole

    manager = db_session.scalar(select(User).where(User.username == 'procurement_manager'))
    supplier = db_session.scalar(select(User).where(User.username == 'supplier_portal'))
    admin = db_session.scalar(select(User).where(User.username == 'system_admin'))
    role = db_session.scalar(select(Role).where(Role.role_code == 'SUPPLIER_PORTAL'))
    assert manager and supplier and admin and role
    if db_session.get(UserRole, (manager.id, role.id)) is None:
        db_session.add(UserRole(user_id=manager.id, role_id=role.id))
        db_session.flush()
    notices = notify_users(db_session, recipient_ids=[manager.id, supplier.id, admin.id], role_codes=[],
        notification_type='AI_BRIEFING', title='汇总', content='测试', exclude_scoped=True)
    assert {item.recipient_id for item in notices} == {supplier.id, admin.id}
