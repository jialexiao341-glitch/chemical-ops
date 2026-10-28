"""询价的共享读取范围。"""
from sqlalchemy import and_, case, select, true
from app.modules.rfqs.model import RFQ
from app.modules.purchase_requests.model import PurchaseRequest
from app.modules.system.model import User
from app.modules.system.data_scope import department_scope_condition


def _department(user, roles):
    source_department = select(PurchaseRequest.department_id).where(PurchaseRequest.id == RFQ.source_request_id).scalar_subquery()
    creator_department = select(User.department_id).where(User.id == RFQ.requester_id).scalar_subquery()
    department = case((RFQ.source_request_id.is_not(None), source_department), else_=creator_department)
    return department_scope_condition(user, roles, department)


def rfq_read_condition(user, roles):
    if {'SYS_ADMIN', 'PROCUREMENT_MANAGER', 'MANAGEMENT_VIEWER'}.intersection(roles):
        base = true()
    else:
        base = RFQ.requester_id == user.id
    return and_(base, _department(user, roles))


def rfq_write_condition(user, roles):
    if {'SYS_ADMIN', 'PROCUREMENT_MANAGER'}.intersection(roles):
        base = true()
    else:
        base = RFQ.requester_id == user.id
    return and_(base, _department(user, roles))
