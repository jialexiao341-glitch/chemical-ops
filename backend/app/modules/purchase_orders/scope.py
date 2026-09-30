"""订单只读数据范围；财务角色不因此获得采购修改权限。"""

from collections.abc import Collection

from sqlalchemy import true
from sqlalchemy.sql.elements import ColumnElement

from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.system.model import User


ORDER_READ_ALL_ROLES = frozenset({"SYS_ADMIN", "PROCUREMENT_MANAGER", "FINANCE_MANAGER", "FINANCE_CLERK"})


def order_read_condition(user: User, roles: Collection[str]) -> ColumnElement[bool]:
    """财务和采购管理岗位跨部门读取，其余按部门或本人订单限制。"""
    if ORDER_READ_ALL_ROLES.intersection(roles):
        return true()
    if user.department_id is not None:
        return PurchaseOrder.department_id == user.department_id
    return PurchaseOrder.buyer_id == user.id
