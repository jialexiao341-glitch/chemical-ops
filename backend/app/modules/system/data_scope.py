"""用户部门授权范围：角色授权的共同上限。"""
from sqlalchemy import exists, or_, select, true
from app.modules.system.model import UserDepartmentGrant, UserDepartmentScope
from app.modules.system.crud import get_user_role_codes
from app.core.errors import AuthorizationError


def department_scope_condition(user, roles, department_column):
    if 'SYS_ADMIN' in roles:
        return true()
    configured = exists(select(UserDepartmentScope.user_id).where(UserDepartmentScope.user_id == user.id))
    allowed = select(UserDepartmentGrant.department_id).where(UserDepartmentGrant.user_id == user.id)
    # 标记仅由服务端生成的范围谓词，供查询审计独立验证。
    return (or_(~configured, department_column.in_(allowed)).self_group() == true())._annotate({'trusted_department_scope': True})


def is_department_restricted(db, user):
    if 'SYS_ADMIN' in get_user_role_codes(db, user.id):
        return False
    return db.get(UserDepartmentScope, user.id) is not None


def is_warehouse_restricted(db, user):
    roles = set(get_user_role_codes(db, user.id))
    return 'SYS_ADMIN' not in roles and roles != {'SUPPLIER_PORTAL'}


def warehouse_scope_snapshot(db, user):
    from app.modules.system.model import UserWarehouseGrant
    from app.modules.inventory.model import Warehouse
    if not is_warehouse_restricted(db, user):
        return None
    return sorted(db.scalars(select(UserWarehouseGrant.warehouse_id).join(
        Warehouse, Warehouse.id == UserWarehouseGrant.warehouse_id
    ).where(UserWarehouseGrant.user_id == user.id, Warehouse.status == 'ACTIVE')).all())


def department_scope_snapshot(db, user):
    """返回当前授权部门；None 表示沿用未限制范围。"""
    if not is_department_restricted(db, user):
        return None
    return sorted(db.scalars(select(UserDepartmentGrant.department_id).where(
        UserDepartmentGrant.user_id == user.id
    )).all())


def require_global_analytics_scope(db, user):
    """全局聚合尚未按部门划分，不能返回给已限制部门的用户。"""
    if is_department_restricted(db, user):
        raise AuthorizationError('当前账号受部门范围限制，暂不能查看全局汇总')
