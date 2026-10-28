"""订单只读数据范围；财务角色不因此获得采购修改权限。"""

from collections.abc import Collection

from sqlalchemy import and_, true
from sqlalchemy.sql.elements import ColumnElement

from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.system.model import User


ORDER_READ_ALL_ROLES = frozenset({"SYS_ADMIN", "PROCUREMENT_MANAGER", "FINANCE_MANAGER", "FINANCE_CLERK"})


def order_read_condition(user: User, roles: Collection[str]) -> ColumnElement[bool]:
    """财务和采购管理岗位跨部门读取，其余按部门或本人订单限制。"""
    from app.modules.system.data_scope import department_scope_condition
    if ORDER_READ_ALL_ROLES.intersection(roles):
        base = true()
    elif user.department_id is not None:
        base = PurchaseOrder.department_id == user.department_id
    else:
        base = PurchaseOrder.buyer_id == user.id
    return and_(base, department_scope_condition(user, roles, PurchaseOrder.department_id))
