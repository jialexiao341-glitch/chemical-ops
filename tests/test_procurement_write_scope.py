from types import SimpleNamespace

import pytest

from app.core.errors import ResourceNotFoundError
from app.modules.purchase_requests import service as requests
from app.modules.purchase_orders import service as orders


def test_purchase_request_write_scope_excludes_other_department_member(monkeypatch):
    user = SimpleNamespace(id=1, department_id=5)
    row = SimpleNamespace(id=10, applicant_id=2, department_id=5)
    db = SimpleNamespace(scalar=lambda *_: row.id)
    monkeypatch.setattr(requests, '_require_request', lambda *a, **k: row)
    monkeypatch.setattr(requests, 'get_user_role_codes', lambda *a: ['BUYER'])
    assert requests.get_request(db, user, 10) is row
    with pytest.raises(ResourceNotFoundError):
        requests.get_request_for_write(db, user, 10)
    monkeypatch.setattr(requests, 'get_user_role_codes', lambda *a: ['SYS_ADMIN'])
    assert requests.get_request_for_write(db, user, 10) is row


def test_purchase_order_write_scope_excludes_other_department_member(monkeypatch):
    user = SimpleNamespace(id=1, department_id=5)
    row = SimpleNamespace(id=10, buyer_id=2, department_id=5)
    db = SimpleNamespace(scalar=lambda *_: True)
    monkeypatch.setattr(orders, '_require_order', lambda *a, **k: row)
    monkeypatch.setattr(orders, 'get_user_role_codes', lambda *a: ['BUYER'])
    with pytest.raises(ResourceNotFoundError):
        orders.get_order(db, user, 10)
    monkeypatch.setattr(orders, 'get_user_role_codes', lambda *a: ['SYS_ADMIN'])
    assert orders.get_order(db, user, 10) is row


def test_batch_delete_records_audit_in_same_transaction(monkeypatch):
    from app.modules.batch import controller
    from app.modules.system.audit import AuditLog

    class Session:
        def __init__(self):
            self.added = []
            self.committed = False
        def add(self, item):
            self.added.append(item)
        def commit(self):
            self.committed = True

    db = Session()
    row = SimpleNamespace(id=7, status='ACTIVE')
    monkeypatch.setattr(controller, '_authorize', lambda *args: None)
    monkeypatch.setattr(controller, '_rows', lambda *args, **kwargs: [row])
    monkeypatch.setattr(controller, '_authorize_row_scope', lambda *args, **kwargs: None)
    controller.batch_delete('master.chemicals', controller.Selection(ids=[7]), db, SimpleNamespace(id=3))
    logs = [item for item in db.added if isinstance(item, AuditLog)]
    assert db.committed and len(logs) == 1
    assert (logs[0].actor_id, logs[0].resource_id, logs[0].action_type) == (3, 7, 'DISABLE')


def test_management_can_read_other_users_rfq_without_write_scope(monkeypatch):
    from app.modules.rfqs import service
    from app.core.errors import BusinessValidationError
    user = SimpleNamespace(id=1)
    row = SimpleNamespace(id=10, requester_id=2)
    db = SimpleNamespace(scalar=lambda query: None if 'rfqs.requester_id = ' in str(query) else row.id)
    monkeypatch.setattr(service.crud, 'get_by_id', lambda *a, **k: row)
    monkeypatch.setattr(service, 'get_user_role_codes', lambda *a: ['MANAGEMENT_VIEWER'])
    assert service.get_rfq(db=db, user=user, rfq_id=10) is row
    with pytest.raises(BusinessValidationError):
        service.get_rfq(db=db, user=user, rfq_id=10, for_write=True)



def test_high_risk_actions_have_independent_permissions():
    from app.modules.finance.controller import router as finance_router
    from app.modules.inventory.controller import router as inventory_router
    from app.modules.system.crud import get_user_permission_codes
    from fastapi import HTTPException
    from types import SimpleNamespace

    def permission_for(router, path, monkeypatch):
        route = next(route for route in router.routes if route.path == path)
        dependency = next(dep.call for dep in route.dependant.dependencies if getattr(dep.call, '__name__', '') == 'dependency')
        import app.core.auth as auth
        monkeypatch.setattr(auth.crud, 'get_user_role_codes', lambda *_: [])
        monkeypatch.setattr(auth.crud, 'get_user_permission_codes', lambda *_: [])
        with pytest.raises(HTTPException):
            dependency(SimpleNamespace(id=1), None)
        code = dependency.__closure__[0].cell_contents
        return code

    from _pytest.monkeypatch import MonkeyPatch
    with MonkeyPatch.context() as mp:
        assert permission_for(finance_router, '/finance/payments/{payment_id}/paid', mp) == 'finance.payments.pay'
        assert permission_for(inventory_router, '/inventory/transfer-requests/{transfer_id}/execute', mp) == 'warehouse.inventory.transfer.execute'



def test_attachment_write_requires_business_permission_and_order_scope(monkeypatch):
    from app.modules.files import service
    user = SimpleNamespace(id=1)
    row = SimpleNamespace(id=5)
    monkeypatch.setattr(service, '_is_system_admin', lambda *args: False)
    monkeypatch.setattr(service, 'get_user_permission_codes', lambda *args: ['procurement.orders.read'])
    with pytest.raises(ResourceNotFoundError):
        service._check_resource_write_access(None, user, 'PURCHASE_ORDER', row)

@pytest.mark.parametrize(('resource_type', 'status'), [
    ('PURCHASE_ORDER', 'COMPLETED'),
    ('DELIVERY', 'ACCEPTED'),
    ('INVENTORY_RETURN', 'COMPLETED'),
    ('REPLENISHMENT', 'APPROVED'),
    ('FINANCE_INVOICE', 'VERIFIED'),
    ('OPERATION_EXCEPTION', 'CLOSED'),
    ('SUPPLIER_QUALITY_DOCUMENT', 'APPROVED'),
])
def test_attachment_rejects_final_business_record_even_for_admin(monkeypatch, resource_type, status):
    from app.modules.files import service
    from app.core.errors import BusinessValidationError
    monkeypatch.setattr(service, '_is_system_admin', lambda *_: True)
    with pytest.raises(BusinessValidationError):
        service._check_resource_write_access(None, SimpleNamespace(id=1), resource_type, SimpleNamespace(id=5, status=status))


def test_attachment_exception_requires_action_scope(monkeypatch):
    from app.modules.files import service
    from app.modules.operation_exceptions import service as exceptions
    user = SimpleNamespace(id=1)
    monkeypatch.setattr(service, '_is_system_admin', lambda *_: False)
    monkeypatch.setattr(service, 'get_user_permission_codes', lambda *_: ['operations.exceptions.write'])
    def deny(*_args):
        raise ResourceNotFoundError('not visible')
    monkeypatch.setattr(exceptions, '_require_task_creation_scope', deny)
    with pytest.raises(ResourceNotFoundError):
        service._check_resource_write_access(None, user, 'OPERATION_EXCEPTION', SimpleNamespace(id=5, status='OPEN'))


def test_order_list_uses_shared_read_scope(db_session, monkeypatch):
    from sqlalchemy import false
    from app.modules.purchase_orders import service
    user = SimpleNamespace(id=1, department_id=1)
    monkeypatch.setattr(service, 'get_user_role_codes', lambda *_: ['PROCUREMENT_MANAGER'])
    monkeypatch.setattr(service, 'order_read_condition', lambda *_: false())
    items, total = service.list_orders(db_session, user, keyword=None, status=None, page=1, page_size=20)
    assert items == [] and total == 0


def test_return_scope_condition_matches_applicant_and_admin(db_session):
    from sqlalchemy import select
    from app.modules.inventory_returns import service
    from app.modules.inventory_returns.model import InventoryReturnRequest
    user = SimpleNamespace(id=-1)
    scoped = set(db_session.scalars(select(InventoryReturnRequest.id).where(service.return_read_condition(db_session, user, roles={'BUYER'}))).all())
    assert scoped == set()
    admin = set(db_session.scalars(select(InventoryReturnRequest.id).where(service.return_read_condition(db_session, user, roles={'SYS_ADMIN'}))).all())
    assert admin == set(db_session.scalars(select(InventoryReturnRequest.id)).all())


def test_request_list_uses_shared_read_scope(db_session, monkeypatch):
    from sqlalchemy import false
    from app.modules.purchase_requests import service
    user = SimpleNamespace(id=1, department_id=1)
    monkeypatch.setattr(service, 'get_user_role_codes', lambda *_: ['PROCUREMENT_MANAGER'])
    monkeypatch.setattr(service, 'request_read_condition', lambda *_: false(), raising=False)
    items, total = service.list_requests(db_session, user, keyword=None, status=None, page=1, page_size=20)
    assert items == [] and total == 0


def test_rfq_list_uses_shared_read_scope(db_session, monkeypatch):
    from sqlalchemy import false
    from app.modules.rfqs import service
    user = SimpleNamespace(id=1, department_id=1)
    monkeypatch.setattr(service, 'get_user_role_codes', lambda *_: ['PROCUREMENT_MANAGER'])
    monkeypatch.setattr(service, 'rfq_read_condition', lambda *_: false(), raising=False)
    items, total = service.list_rfqs(db_session, user, keyword=None, status=None, page=1, page_size=20)
    assert items == [] and total == 0
