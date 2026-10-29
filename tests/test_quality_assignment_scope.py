from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.errors import BusinessValidationError
from app.modules.deliveries.model import Delivery
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.quality_acceptances import service
from app.modules.quality_acceptances.schema import QualityAcceptanceCreate
from app.modules.system.model import User, UserDepartmentScope, UserDepartmentGrant


def test_assignment_options_and_inspector_respect_department_scope(db_session, client):
    from app.core.auth import get_current_user
    from app.main import app
    manager = db_session.scalar(select(User).where(User.username == 'quality_manager'))
    inspector = db_session.scalar(select(User).where(User.username == 'quality_inspector'))
    departments = list(db_session.scalars(select(PurchaseOrder.department_id).where(
        PurchaseOrder.department_id.is_not(None)).distinct().limit(2)))
    assert manager is not None and inspector is not None and len(departments) == 2
    orders = [db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.department_id == department).limit(1)) for department in departments]
    deliveries = [Delivery(delivery_no=f'TEST-Q-{uuid4().hex[:12]}', po_id=order.id,
                           supplier_id=order.supplier_id, status='RECEIVED') for order in orders]
    db_session.add_all(deliveries + [UserDepartmentScope(user_id=manager.id), UserDepartmentScope(user_id=inspector.id)])
    db_session.flush()
    db_session.add_all([UserDepartmentGrant(user_id=manager.id, department_id=departments[0]),
                        UserDepartmentGrant(user_id=inspector.id, department_id=departments[1])])
    db_session.flush()
    app.dependency_overrides[get_current_user] = lambda: manager
    try:
        response = client.get('/api/v1/quality-acceptances/assignment-options')
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 200
    ids = {delivery['id'] for delivery in response.json()['deliveries']}
    assert deliveries[0].id in ids
    assert deliveries[1].id not in ids
    with pytest.raises(BusinessValidationError):
        service.create_acceptance(db_session, manager, QualityAcceptanceCreate(
            delivery_id=deliveries[0].id, inspector_id=inspector.id))
