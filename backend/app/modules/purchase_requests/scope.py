"""采购申请的共享读取范围。"""

from sqlalchemy import and_, true
from app.modules.purchase_requests.model import PurchaseRequest


def request_read_condition(user, roles):
    from app.modules.system.data_scope import department_scope_condition
    if {'SYS_ADMIN', 'PROCUREMENT_MANAGER'}.intersection(roles):
        base = true()
    elif user.department_id is not None:
        base = PurchaseRequest.department_id == user.department_id
    else:
        base = PurchaseRequest.applicant_id == user.id
    return and_(base, department_scope_condition(user, roles, PurchaseRequest.department_id))
