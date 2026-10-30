"""系统管理和登录认证业务服务。"""

import base64
import binascii
from datetime import datetime, timedelta
import hashlib

from fastapi import HTTPException
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.errors import AuthorizationError, AuthenticationError, BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.core.security import create_access_token, hash_password, verify_password
from app.modules.system import crud
from app.modules.suppliers.model import Supplier
from app.modules.supplier_portal.model import SupplierPortalAccount
from app.modules.system.model import Department, Permission, Role, RolePermission, User, UserRole, UserDepartmentScope, UserDepartmentGrant
from app.modules.system.model import UserWarehouseScope, UserWarehouseGrant
from app.modules.system.audit import add_audit_log
from app.modules.system.schema import (
    DepartmentCreate,
    DepartmentUpdate,
    LoginRequest,
    PasswordChange,
    PermissionCreate,
    PermissionUpdate,
    ProfileUpdate,
    RoleCreate,
    RoleUpdate,
    SupplierBindingRead,
    RegistrationCreate,
    RegistrationReview,
    UserRead,
    UserCreate,
    UserUpdate,
)


def _require_user(db: Session, user_id: int) -> User:
    """查询用户并确保用户存在。"""

    user = crud.get_user(db, user_id)
    if user is None:
        raise ResourceNotFoundError(f"用户 {user_id} 不存在")
    return user


def get_user_department_scope(db: Session, user_id: int) -> dict:
    _require_user(db, user_id)
    scope = db.get(UserDepartmentScope, user_id)
    ids = list(db.scalars(select(UserDepartmentGrant.department_id).where(
        UserDepartmentGrant.user_id == user_id
    ).order_by(UserDepartmentGrant.department_id)).all()) if scope else []
    return {"enabled": scope is not None, "department_ids": ids}


def get_user_warehouse_scope(db: Session, user_id: int) -> dict:
    _require_user(db, user_id)
    enabled = True
    ids = list(db.scalars(select(UserWarehouseGrant.warehouse_id).where(
        UserWarehouseGrant.user_id == user_id).order_by(UserWarehouseGrant.warehouse_id)).all()) if enabled else []
    return {"enabled": enabled, "warehouse_ids": ids}


def set_user_warehouse_scope(db: Session, user_id: int, *, enabled: bool, warehouse_ids: list[int], actor_id: int) -> dict:
    from app.modules.inventory.model import Warehouse
    require_authorization_admin(db, actor_id)
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ResourceNotFoundError("用户不存在")
    roles = set(crud.get_user_role_codes(db, user_id))
    if not enabled:
        raise BusinessValidationError("仓库授权始终生效；如需禁止访问，请清空授权仓库")
    if enabled and "SYS_ADMIN" in roles:
        raise BusinessValidationError("系统管理员不受仓库范围限制")
    if enabled and roles == {"SUPPLIER_PORTAL"}:
        raise BusinessValidationError("供应商账号不能配置仓库授权")
    if len(warehouse_ids) != len(set(warehouse_ids)) or any(value <= 0 for value in warehouse_ids):
        raise BusinessValidationError("仓库授权包含重复或无效仓库")
    ids = sorted(warehouse_ids)
    if ids and set(db.scalars(select(Warehouse.id).where(Warehouse.id.in_(ids), Warehouse.status == "ACTIVE")).all()) != set(ids):
        raise BusinessValidationError("授权仓库不存在或已停用")
    previous = get_user_warehouse_scope(db, user_id)
    if previous == {"enabled": enabled, "warehouse_ids": ids}:
        return previous
    db.execute(delete(UserWarehouseGrant).where(UserWarehouseGrant.user_id == user_id))
    scope = db.get(UserWarehouseScope, user_id)
    if enabled:
        if scope is None:
            db.add(UserWarehouseScope(user_id=user_id))
            db.flush()
        db.add_all(UserWarehouseGrant(user_id=user_id, warehouse_id=value) for value in ids)
    user.token_version += 1
    add_audit_log(db, actor_id=actor_id, action_type="UPDATE_WAREHOUSE_SCOPE", resource_type="USER", resource_id=user.id,
                  request_summary=f"仓库授权 {previous} -> {{'enabled': {enabled}, 'warehouse_ids': {ids}}}", result_status="SUCCESS")
    db.commit()
    return {"enabled": enabled, "warehouse_ids": ids}


def set_user_department_scope(db: Session, user_id: int, *, enabled: bool, department_ids: list[int], actor_id: int) -> dict:
    require_authorization_admin(db, actor_id)
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ResourceNotFoundError("用户不存在")
    roles = set(crud.get_user_role_codes(db, user_id))
    if enabled and "SYS_ADMIN" in roles:
        raise BusinessValidationError("系统管理员不受部门范围限制")
    if enabled and ("SUPPLIER_PORTAL" in roles or not roles.intersection({"PROCUREMENT_MANAGER", "FINANCE_VIEWER", "FINANCE_CLERK", "FINANCE_MANAGER"})):
        raise BusinessValidationError("部门授权仅适用于内部采购经理或财务岗位账号")
    if len(department_ids) != len(set(department_ids)) or any(value <= 0 for value in department_ids):
        raise BusinessValidationError("部门授权包含重复或无效部门")
    if not enabled and department_ids:
        raise BusinessValidationError("未启用部门限制时不能指定部门")
    ids = sorted(department_ids)
    if ids:
        actual = set(db.scalars(select(Department.id).where(Department.id.in_(ids), Department.status == "ACTIVE")).all())
        if actual != set(ids):
            raise BusinessValidationError("授权部门不存在或已停用")
    previous = get_user_department_scope(db, user_id)
    if previous == {"enabled": enabled, "department_ids": ids}:
        return previous
    db.execute(delete(UserDepartmentGrant).where(UserDepartmentGrant.user_id == user_id))
    scope = db.get(UserDepartmentScope, user_id)
    if enabled:
        if scope is None:
            db.add(UserDepartmentScope(user_id=user_id))
            db.flush()
        db.add_all(UserDepartmentGrant(user_id=user_id, department_id=value) for value in ids)
    elif scope is not None:
        db.delete(scope)
    user.token_version += 1
    add_audit_log(db, actor_id=actor_id, action_type="UPDATE_DEPARTMENT_SCOPE", resource_type="USER", resource_id=user.id,
                  request_summary=f"部门授权 {previous} -> {{'enabled': {enabled}, 'department_ids': {ids}}}", result_status="SUCCESS")
    db.commit()
    return {"enabled": enabled, "department_ids": ids}


def _require_roles(db: Session, role_ids: list[int]) -> None:
    """校验角色 ID 全部存在。"""

    if not role_ids:
        return
    actual = set(db.scalars(select(Role.id).where(Role.id.in_(set(role_ids)))).all())
    missing = sorted(set(role_ids) - actual)
    if missing:
        raise ResourceNotFoundError(f"角色不存在：{missing}")


def _invalidate_role_members(db: Session, role_id: int) -> None:
    """使持有指定角色的旧访问令牌失效，覆盖幂等响应重放路径。"""

    member_ids = select(UserRole.user_id).where(UserRole.role_id == role_id)
    db.execute(
        update(User)
        .where(User.id.in_(member_ids))
        .values(token_version=User.token_version + 1)
        .execution_options(synchronize_session=False)
    )


def _require_department(db: Session, department_id: int | None) -> None:
    """校验部门 ID 存在。"""

    if department_id is not None and crud.get_department(db, department_id) is None:
        raise ResourceNotFoundError(f"部门 {department_id} 不存在")


def list_users(db: Session, keyword: str | None, status: str | None, page: int, page_size: int):
    """查询用户分页列表。"""

    users, total = crud.list_users(db, keyword, status, page, page_size)
    reads = {user.id: UserRead.model_validate(user) for user in users}
    if reads:
        for user_id, code, name in db.execute(
            select(UserRole.user_id, Role.role_code, Role.role_name)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(reads), Role.status == "ACTIVE").order_by(Role.id)
        ):
            reads[user_id].role_codes.append(code)
            reads[user_id].role_names.append(name)
    return list(reads.values()), total


def user_read(db: Session, user: User) -> UserRead:
    read = UserRead.model_validate(user)
    read.role_ids = crud.get_user_role_ids(db, user.id)
    roles = db.execute(select(Role.role_code, Role.role_name).join(UserRole, UserRole.role_id == Role.id)
                       .where(UserRole.user_id == user.id, Role.status == "ACTIVE").order_by(Role.id)).all()
    read.role_codes = [row[0] for row in roles]
    read.role_names = [row[1] for row in roles]
    return read


def registration_roles(db: Session):
    return db.scalars(select(Role).where(Role.status == "ACTIVE", Role.role_code != "SYS_ADMIN").order_by(Role.id)).all()


def check_registration_rate(db: Session, client_ip: str) -> None:
    """数据库共享的 15 分钟/IP 注册限额，在密码散列前计数。"""
    now = datetime.now()
    key = _login_scope_key("registration_ip", client_ip)
    db.execute(text("INSERT IGNORE INTO sys_login_attempts (scope_key, failure_count, window_started_at) VALUES (:key, 0, :now)"), {"key": key, "now": now})
    row = db.execute(text("SELECT failure_count, window_started_at FROM sys_login_attempts WHERE scope_key=:key FOR UPDATE"), {"key": key}).mappings().one()
    expired = now - row["window_started_at"] >= timedelta(minutes=15)
    count = 0 if expired else row["failure_count"]
    if count >= 3:
        db.rollback()
        raise HTTPException(429, "注册请求过于频繁，请稍后重试", headers={"Retry-After": "900"})
    db.execute(text("UPDATE sys_login_attempts SET failure_count=:count, window_started_at=:started WHERE scope_key=:key"),
               {"count": count + 1, "started": now if expired else row["window_started_at"], "key": key})
    db.commit()


def register_user(db: Session, data: RegistrationCreate) -> User:
    role = db.scalar(select(Role).where(Role.role_code == data.role_code, Role.status == "ACTIVE"))
    if role is None or role.role_code == "SYS_ADMIN":
        raise BusinessValidationError("请选择有效的非管理员角色")
    if not data.display_name.strip():
        raise BusinessValidationError("请填写姓名")
    if crud.get_user_by_username(db, data.username) or (data.email and db.scalar(select(User.id).where(User.email == data.email))):
        raise DuplicateResourceError("账号名或邮箱已被使用")
    user = User(username=data.username, display_name=data.display_name.strip(), password_hash=hash_password(data.password),
                email=data.email or None, phone=data.phone or None, avatar=_decode_avatar(data.avatar_base64), status="PENDING")
    try:
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        add_audit_log(db, actor_id=None, action_type="REGISTER_USER", resource_type="system.users",
                      resource_id=user.id, request_summary=f"申请角色：{role.role_code}", result_status="PENDING")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateResourceError("账号名或邮箱已被使用") from None
    return user


def review_registration(db: Session, user_id: int, data: RegistrationReview, *, actor_id: int) -> UserRead:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ResourceNotFoundError(f"用户 {user_id} 不存在")
    if user.status != "PENDING":
        raise BusinessValidationError("只能审批待审核的注册申请")
    codes = crud.get_user_role_codes(db, user_id)
    if data.decision == "approve" and (not codes or "SYS_ADMIN" in codes):
        raise BusinessValidationError("注册申请角色已失效，请拒绝申请后重新注册")
    user.status = "ACTIVE" if data.decision == "approve" else "REJECTED"
    user.token_version += 1
    add_audit_log(db, actor_id=actor_id, action_type="REVIEW_REGISTRATION", resource_type="system.users",
                  resource_id=user.id, request_summary=f"{data.decision}：{data.reason.strip()}", result_status=user.status)
    db.commit()
    return user_read(db, user)


def list_supplier_binding_options(db: Session):
    """同一供应商可以绑定多个账号，仅启用供应商可供选择。"""

    return db.scalars(select(Supplier).where(Supplier.status == "ACTIVE").order_by(Supplier.supplier_code)).all()


def get_supplier_binding(db: Session, user_id: int) -> SupplierBindingRead | None:
    """回填当前绑定，即使供应商或绑定已停用也保留展示。"""

    _require_user(db, user_id)
    row = db.execute(
        select(SupplierPortalAccount, Supplier)
        .join(Supplier, Supplier.id == SupplierPortalAccount.supplier_id)
        .where(SupplierPortalAccount.user_id == user_id)
    ).first()
    if row is None:
        return None
    account, supplier = row
    return SupplierBindingRead(
        supplier_id=supplier.id, supplier_code=supplier.supplier_code,
        supplier_name=supplier.supplier_name, supplier_status=supplier.status, status=account.status,
    )


def set_supplier_binding(db: Session, user_id: int, supplier_id: int, *, actor_id: int) -> SupplierBindingRead:
    """串行更新同一用户的唯一绑定，记录变更前后供应商。"""

    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ResourceNotFoundError(f"用户 {user_id} 不存在")
    if user.status != "ACTIVE":
        raise BusinessValidationError("只能为启用的用户绑定供应商")
    if set(crud.get_user_role_codes(db, user_id)) != {"SUPPLIER_PORTAL"}:
        raise BusinessValidationError("只能为供应商门户角色账号绑定供应商")
    supplier = db.scalar(select(Supplier).where(Supplier.id == supplier_id).with_for_update())
    if supplier is None:
        raise ResourceNotFoundError(f"供应商 {supplier_id} 不存在")
    if supplier.status != "ACTIVE":
        raise BusinessValidationError("只能绑定启用的供应商")
    account = db.scalar(select(SupplierPortalAccount).where(SupplierPortalAccount.user_id == user_id))
    if account is None or account.supplier_id != supplier_id or account.status != "ACTIVE":
        previous = f"{account.supplier_id}/{account.status}" if account else "未绑定"
        if account is None:
            db.add(SupplierPortalAccount(user_id=user_id, supplier_id=supplier_id, status="ACTIVE"))
        else:
            account.supplier_id = supplier_id
            account.status = "ACTIVE"
        add_audit_log(
            db, actor_id=actor_id, action_type="BIND_SUPPLIER", resource_type="system.users",
            resource_id=user_id, request_summary=f"供应商绑定：{previous} -> {supplier_id}/ACTIVE",
            result_status="SUCCESS",
        )
    db.commit()
    return get_supplier_binding(db, user_id)


def ensure_active_system_admin_remains(db: Session, excluded_user_ids: set[int]) -> None:
    """Prevent an account operation from removing the final active system admin."""

    active_admin_ids = set(
        db.scalars(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.status == "ACTIVE",
                Role.status == "ACTIVE",
                Role.role_code == "SYS_ADMIN",
            )
            .order_by(User.id)
            .with_for_update()
        ).all()
    )
    if not active_admin_ids - excluded_user_ids:
        raise BusinessValidationError("至少保留一个启用的系统管理员账号")


def _require_role_assignment(db: Session, actor_id: int | None, role_ids: list[int], *, target_id: int | None = None) -> None:
    """只有系统管理员能变更管理员或管理授权的角色，防止委派管理间接提权。"""
    if actor_id is None or "SYS_ADMIN" in crud.get_user_role_codes(db, actor_id):
        return
    roles = set(db.scalars(select(Role.role_code).where(Role.id.in_(set(role_ids)))).all())
    permissions = set(db.scalars(select(Permission.permission_code).join(
        RolePermission, RolePermission.permission_id == Permission.id,
    ).where(RolePermission.role_id.in_(set(role_ids)))).all())
    if "SYS_ADMIN" in roles or permissions & {"system.users.write", "system.roles.write", "system.permissions.write"}:
        raise AuthorizationError("仅系统管理员可以授予管理授权角色")
    if target_id is not None and "SYS_ADMIN" in crud.get_user_role_codes(db, target_id):
        raise AuthorizationError("仅系统管理员可以修改系统管理员账号")


def create_user(db: Session, data: UserCreate, *, actor_id: int | None = None) -> User:
    """校验用户名、部门和角色后创建用户。"""

    email = data.email.strip() if data.email and data.email.strip() else None
    if crud.get_user_by_username(db, data.username):
        raise DuplicateResourceError(f"用户名 {data.username} 已存在")
    if email and db.scalar(select(User.id).where(User.email == email).limit(1)):
        raise DuplicateResourceError(f"邮箱 {email} 已被其他用户使用")
    _require_department(db, data.department_id)
    _require_roles(db, data.role_ids)
    _require_role_assignment(db, actor_id, data.role_ids)
    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
        department_id=data.department_id,
        email=email,
        phone=data.phone,
    )
    try:
        db.add(user)
        db.flush()
        crud.replace_user_roles(db, user.id, data.role_ids)
        add_audit_log(db, actor_id=actor_id, action_type="CREATE", resource_type="USER", resource_id=user.id, request_summary=f"创建用户，角色 ID={sorted(data.role_ids)}", result_status="SUCCESS")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateResourceError("用户名或邮箱已被占用") from None
    db.refresh(user)
    return user


def update_user(
    db: Session, user_id: int, data: UserUpdate, *, actor_id: int | None = None
) -> User:
    """更新用户资料、状态、密码和角色关联。"""

    user = _require_user(db, user_id)
    values = data.model_dump(exclude_unset=True, exclude={"password", "role_ids"})
    if "email" in values:
        values["email"] = values["email"].strip() if values["email"] and values["email"].strip() else None
        if values["email"] and db.scalar(select(User.id).where(User.email == values["email"], User.id != user_id).limit(1)):
            raise DuplicateResourceError(f"邮箱 {values['email']} 已被其他用户使用")
    if user.status in {"PENDING", "REJECTED"}:
        raise BusinessValidationError("注册申请只能通过专用审批操作处理")
    current_role_codes = set(crud.get_user_role_codes(db, user_id))
    if actor_id == user_id and values.get("status", user.status) != "ACTIVE":
        raise BusinessValidationError("不能停用当前登录账号")
    next_role_codes = current_role_codes
    current_role_ids = set(crud.get_user_role_ids(db, user_id))
    _require_role_assignment(db, actor_id, data.role_ids if data.role_ids is not None else list(current_role_ids), target_id=user_id)
    role_membership_changed = False
    if data.role_ids is not None:
        _require_roles(db, data.role_ids)
        role_membership_changed = current_role_ids != set(data.role_ids)
        next_role_codes = set(
            db.scalars(select(Role.role_code).where(Role.id.in_(set(data.role_ids)))).all()
        )
    if user.status == "ACTIVE" and "SYS_ADMIN" in current_role_codes and (
        values.get("status", user.status) != "ACTIVE"
        or "SYS_ADMIN" not in next_role_codes
    ):
        ensure_active_system_admin_remains(db, {user_id})
    if actor_id == user_id and "SYS_ADMIN" in current_role_codes and "SYS_ADMIN" not in next_role_codes:
        raise BusinessValidationError("不能移除当前登录账号的系统管理员角色")
    if data.password is not None:
        values["password_hash"] = hash_password(data.password)
    if (
        data.password is not None
        or role_membership_changed
        or ("status" in values and values["status"] != user.status)
    ):
        values["token_version"] = user.token_version + 1
    _require_department(db, data.department_id)
    if data.role_ids is not None:
        crud.replace_user_roles(db, user.id, data.role_ids)
        if next_role_codes != {"SUPPLIER_PORTAL"}:
            account = db.scalar(select(SupplierPortalAccount).where(SupplierPortalAccount.user_id == user.id))
            if account is not None:
                account.status = "INACTIVE"
    add_audit_log(db, actor_id=actor_id, action_type="UPDATE", resource_type="USER", resource_id=user.id, request_summary=f"更新用户字段={sorted(values.keys())}，角色 ID={sorted(data.role_ids) if data.role_ids is not None else '未变更'}", result_status="SUCCESS")
    try:
        return crud.update_entity(db, user, values)
    except IntegrityError:
        db.rollback()
        raise DuplicateResourceError("邮箱已被其他用户使用") from None


def delete_user(db: Session, user_id: int, *, actor_id: int | None = None, commit: bool = True) -> User:
    """软删除用户并保留历史操作记录。"""

    user = _require_user(db, user_id)
    if user.status in {"PENDING", "REJECTED"}:
        raise BusinessValidationError("注册申请只能通过专用审批操作处理")
    if actor_id == user_id:
        raise BusinessValidationError("不能停用当前登录账号")
    if user.status == "ACTIVE" and "SYS_ADMIN" in crud.get_user_role_codes(db, user_id):
        ensure_active_system_admin_remains(db, {user_id})
    _require_role_assignment(db, actor_id, [], target_id=user_id)
    user.token_version += 1
    add_audit_log(db, actor_id=actor_id, action_type="DISABLE", resource_type="USER", resource_id=user.id, request_summary="停用用户", result_status="SUCCESS")
    user.status = "INACTIVE"
    if commit:
        db.commit()
        db.refresh(user)
    return user


def list_departments(db: Session, keyword: str | None, status: str | None, page: int, page_size: int):
    """查询部门分页列表。"""

    return crud.list_departments(db, keyword, status, page, page_size)


def create_department(db: Session, data: DepartmentCreate) -> Department:
    """校验父部门和负责人后创建部门。"""

    if db.scalar(select(Department).where(Department.department_code == data.department_code)):
        raise DuplicateResourceError(f"部门编码 {data.department_code} 已存在")
    if data.parent_id is not None and crud.get_department(db, data.parent_id) is None:
        raise ResourceNotFoundError(f"父部门 {data.parent_id} 不存在")
    _require_user(db, data.manager_id) if data.manager_id is not None else None
    return crud.add_entity(db, Department(**data.model_dump()))


def update_department(db: Session, department_id: int, data: DepartmentUpdate) -> Department:
    """更新部门名称、层级、负责人或状态。"""

    department = crud.get_department(db, department_id)
    if department is None:
        raise ResourceNotFoundError(f"部门 {department_id} 不存在")
    if data.parent_id == department_id:
        raise BusinessValidationError("部门不能将自己设置为父部门")
    if data.parent_id is not None and crud.get_department(db, data.parent_id) is None:
        raise ResourceNotFoundError(f"父部门 {data.parent_id} 不存在")
    if data.manager_id is not None:
        _require_user(db, data.manager_id)
    return crud.update_entity(db, department, data.model_dump(exclude_unset=True))


def delete_department(db: Session, department_id: int, *, commit: bool = True) -> Department:
    """软删除部门，将状态设置为 INACTIVE。"""

    department = crud.get_department(db, department_id)
    if department is None:
        raise ResourceNotFoundError(f"部门 {department_id} 不存在")
    department.status = "INACTIVE"
    if commit:
        db.commit()
        db.refresh(department)
    return department


def list_roles(db: Session, keyword: str | None, status: str | None, page: int, page_size: int):
    """查询角色分页列表。"""

    return crud.list_roles(db, keyword, status, page, page_size)


def require_authorization_admin(db: Session, actor_id: int | None) -> None:
    if actor_id is not None and "SYS_ADMIN" not in crud.get_user_role_codes(db, actor_id):
        raise AuthorizationError("仅系统管理员可以修改角色或权限定义")


def create_role(db: Session, data: RoleCreate, *, actor_id: int | None = None) -> Role:
    """校验角色编码和权限后创建角色。"""

    require_authorization_admin(db, actor_id)

    if crud.get_role_by_code(db, data.role_code):
        raise DuplicateResourceError(f"角色编码 {data.role_code} 已存在")
    _require_permissions(db, data.permission_ids)
    role = Role(role_code=data.role_code, role_name=data.role_name, description=data.description)
    db.add(role)
    db.flush()
    for permission_id in sorted(set(data.permission_ids)):
        db.add(RolePermission(role_id=role.id, permission_id=permission_id))
    add_audit_log(db, actor_id=actor_id, action_type="CREATE", resource_type="ROLE", resource_id=role.id, request_summary="create_role", result_status="SUCCESS")
    db.commit()
    db.refresh(role)
    return role


def update_role(db: Session, role_id: int, data: RoleUpdate, *, actor_id: int | None = None) -> Role:
    """更新角色资料和权限关联。"""

    require_authorization_admin(db, actor_id)

    role = crud.get_role(db, role_id)
    if role is None:
        raise ResourceNotFoundError(f"角色 {role_id} 不存在")
    values = data.model_dump(exclude_unset=True, exclude={"permission_ids"})
    if role.role_code == "SYS_ADMIN" and values.get("status") == "INACTIVE":
        raise BusinessValidationError("系统管理员角色不能停用")
    authorization_changed = values.get("status", role.status) != role.status
    if data.permission_ids is not None:
        _require_permissions(db, data.permission_ids)
        current_permission_ids = set(
            db.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role_id)).all()
        )
        authorization_changed = authorization_changed or current_permission_ids != set(data.permission_ids)
        if role.role_code == "SYS_ADMIN":
            all_permission_ids = set(db.scalars(select(Permission.id)).all())
            if set(data.permission_ids) != all_permission_ids:
                raise BusinessValidationError("系统管理员角色必须保留全部权限")
        db.query(RolePermission).filter_by(role_id=role_id).delete()
        for permission_id in sorted(set(data.permission_ids)):
            db.add(RolePermission(role_id=role_id, permission_id=permission_id))
    if authorization_changed:
        _invalidate_role_members(db, role_id)
    add_audit_log(db, actor_id=actor_id, action_type="UPDATE", resource_type="ROLE", resource_id=role.id, request_summary="update_role", result_status="SUCCESS")
    return crud.update_entity(db, role, values)


def _require_permissions(db: Session, permission_ids: list[int]) -> None:
    """校验权限 ID 全部存在。"""

    if not permission_ids:
        return
    actual = set(db.scalars(select(Permission.id).where(Permission.id.in_(set(permission_ids)))).all())
    missing = sorted(set(permission_ids) - actual)
    if missing:
        raise ResourceNotFoundError(f"权限不存在：{missing}")


def delete_role(db: Session, role_id: int, *, actor_id: int | None = None, commit: bool = True) -> Role:
    """软删除角色，将状态设置为 INACTIVE。"""

    require_authorization_admin(db, actor_id)

    role = crud.get_role(db, role_id)
    if role is None:
        raise ResourceNotFoundError(f"角色 {role_id} 不存在")
    if role.role_code == "SYS_ADMIN":
        raise BusinessValidationError("系统管理员角色不能停用")
    if role.status != "INACTIVE":
        _invalidate_role_members(db, role_id)
    add_audit_log(db, actor_id=actor_id, action_type="DELETE", resource_type="ROLE", resource_id=role.id, request_summary="delete_role", result_status="SUCCESS")
    role.status = "INACTIVE"
    if commit:
        db.commit()
        db.refresh(role)
    return role


def list_permissions(db: Session, keyword: str | None, permission_type: str | None, page: int, page_size: int):
    """查询权限分页列表。"""

    return crud.list_permissions(db, keyword, permission_type, page, page_size)


def create_permission(db: Session, data: PermissionCreate, *, actor_id: int | None = None) -> Permission:
    """校验权限编码后创建权限。"""

    require_authorization_admin(db, actor_id)

    if crud.get_permission_by_code(db, data.permission_code):
        raise DuplicateResourceError(f"权限编码 {data.permission_code} 已存在")
    permission = Permission(**data.model_dump())
    db.add(permission)
    db.flush()
    add_audit_log(db, actor_id=actor_id, action_type="CREATE", resource_type="PERMISSION", resource_id=permission.id, request_summary="创建权限", result_status="SUCCESS")
    db.commit()
    db.refresh(permission)
    return permission


def update_permission(db: Session, permission_id: int, data: PermissionUpdate, *, actor_id: int | None = None) -> Permission:
    """更新权限名称、类型、资源或操作。"""

    require_authorization_admin(db, actor_id)

    permission = crud.get_permission(db, permission_id)
    if permission is None:
        raise ResourceNotFoundError(f"权限 {permission_id} 不存在")
    add_audit_log(db, actor_id=actor_id, action_type="UPDATE", resource_type="PERMISSION", resource_id=permission.id, request_summary="update_permission", result_status="SUCCESS")
    return crud.update_entity(db, permission, data.model_dump(exclude_unset=True))


def delete_permission(db: Session, permission_id: int, *, actor_id: int | None = None, commit: bool = True) -> Permission:
    """权限表没有状态字段，删除前必须确认没有角色引用。"""

    require_authorization_admin(db, actor_id)

    permission = crud.get_permission(db, permission_id)
    if permission is None:
        raise ResourceNotFoundError(f"权限 {permission_id} 不存在")
    if db.scalar(select(RolePermission).where(RolePermission.permission_id == permission_id).limit(1)):
        raise BusinessValidationError("权限已绑定角色，不能直接删除")
    db.delete(permission)
    add_audit_log(db, actor_id=actor_id, action_type="DELETE", resource_type="PERMISSION", resource_id=permission.id, request_summary="delete_permission", result_status="SUCCESS")
    if commit:
        db.commit()
    return permission


LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_LOCKOUT = timedelta(minutes=15)
LOGIN_LIMITS = {"account_ip": 5, "ip": 30}
DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$310000$MDEyMzQ1Njc4OWFiY2RlZg=="
    "$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)


def _login_scope_key(scope: str, value: str) -> str:
    return hashlib.sha256(f"{scope}:{value}".encode("utf-8")).hexdigest()


def _lock_login_scopes(db: Session, username: str, client_ip: str, now: datetime):
    """创建并按固定顺序锁定限速行，避免并发请求绕过失败计数。"""

    account_ip = f"{username.strip().casefold()}\0{client_ip}"
    scopes = {
        _login_scope_key("account_ip", account_ip): LOGIN_LIMITS["account_ip"],
        _login_scope_key("ip", client_ip): LOGIN_LIMITS["ip"],
    }
    for key in sorted(scopes):
        db.execute(
            text(
                "INSERT IGNORE INTO sys_login_attempts "
                "(scope_key, failure_count, window_started_at) VALUES (:key, 0, :now)"
            ),
            {"key": key, "now": now},
        )
    rows = {}
    for key in sorted(scopes):
        row = db.execute(
            text(
                "SELECT failure_count, window_started_at, locked_until "
                "FROM sys_login_attempts WHERE scope_key=:key FOR UPDATE"
            ),
            {"key": key},
        ).mappings().one()
        rows[key] = dict(row)
    return scopes, rows


def login(db: Session, data: LoginRequest, client_ip: str = "unknown") -> tuple[str, int]:
    """检查登录限速、校验凭据并生成带会话版本的访问令牌。"""

    now = datetime.now()
    scopes, attempts = _lock_login_scopes(db, data.username, client_ip, now)
    active_locks = [
        row["locked_until"]
        for row in attempts.values()
        if row["locked_until"] is not None and row["locked_until"] > now
    ]
    if active_locks:
        retry_after = max(1, int((max(active_locks) - now).total_seconds()))
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail="登录失败次数过多，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )

    for key, row in attempts.items():
        if now - row["window_started_at"] >= LOGIN_WINDOW:
            row["failure_count"] = 0
            row["window_started_at"] = now
            row["locked_until"] = None

    user = crud.get_user_by_username(db, data.username)
    password_matches = verify_password(
        data.password,
        user.password_hash if user is not None else DUMMY_PASSWORD_HASH,
    )
    password_valid = (
        user is not None
        and user.status == "ACTIVE"
        and password_matches
    )
    if user is not None and password_matches and user.status in {"PENDING", "REJECTED"}:
        db.commit()
        raise AuthenticationError("注册申请待管理员审批" if user.status == "PENDING" else "注册申请已被拒绝，请联系管理员")
    if not password_valid:
        lock_triggered = False
        for key, row in attempts.items():
            failures = row["failure_count"] + 1
            locked_until = now + LOGIN_LOCKOUT if failures >= scopes[key] else None
            lock_triggered = lock_triggered or locked_until is not None
            db.execute(
                text(
                    "UPDATE sys_login_attempts SET failure_count=:failures, "
                    "window_started_at=:window_started_at, locked_until=:locked_until "
                    "WHERE scope_key=:key"
                ),
                {
                    "failures": failures,
                    "window_started_at": row["window_started_at"],
                    "locked_until": locked_until,
                    "key": key,
                },
            )
        db.execute(
            text("DELETE FROM sys_login_attempts WHERE updated_at < :cutoff LIMIT 100"),
            {"cutoff": now - timedelta(days=1)},
        )
        db.commit()
        if lock_triggered:
            raise HTTPException(
                status_code=429,
                detail="登录失败次数过多，请稍后重试",
                headers={"Retry-After": str(int(LOGIN_LOCKOUT.total_seconds()))},
            )
        raise AuthenticationError("用户名或密码错误")

    for key in scopes:
        db.execute(
            text(
                "UPDATE sys_login_attempts SET failure_count=0, window_started_at=:now, "
                "locked_until=NULL WHERE scope_key=:key"
            ),
            {"now": now, "key": key},
        )
    user.last_login_at = datetime.now()
    db.commit()
    from app.core.config import get_settings

    settings = get_settings()
    return create_access_token(user.id, user.token_version), settings.access_token_expire_minutes * 60


def revoke_sessions(db: Session, user: User) -> None:
    """递增会话版本，使该用户已有的所有访问令牌立即失效。"""

    user.token_version += 1
    db.commit()


AVATAR_MAX_BYTES = 512 * 1024


def _looks_like_image(raw: bytes) -> bool:
    """按魔数识别 JPG/PNG/GIF/WebP，防止把任意字节塞进头像列。"""

    if raw.startswith((b"\xff\xd8\xff", b"\x89PNG", b"GIF8")):
        return True
    return raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"


def _decode_avatar(value: str | None) -> bytes | None:
    """校验并解码头像 base64；None/空串表示清除。"""

    if value is None or not value.strip():
        return None
    try:
        # 容错：允许前端带上 data:image/...;base64, 前缀
        payload = value.split(",", 1)[1] if value.startswith("data:") else value
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BusinessValidationError("头像 base64 格式不正确") from exc
    if len(raw) > AVATAR_MAX_BYTES:
        raise BusinessValidationError("头像过大，请压缩到 512KB 以内")
    if not _looks_like_image(raw):
        raise BusinessValidationError("仅支持 JPG/PNG/GIF/WebP 图片")
    return raw


def update_profile(db: Session, user: User, data: ProfileUpdate) -> User:
    """个人中心更新自己的昵称/邮箱/手机/头像。"""

    values = data.model_dump(exclude_unset=True)
    if "email" in values:
        values["email"] = values["email"].strip() if values["email"] and values["email"].strip() else None
        if values["email"] and db.scalar(select(User.id).where(User.email == values["email"], User.id != user.id).limit(1)):
            raise DuplicateResourceError(f"邮箱 {values['email']} 已被其他用户使用")
    has_avatar = "avatar_base64" in values
    avatar_value = values.pop("avatar_base64", None)
    if not values and not has_avatar:
        raise BusinessValidationError("没有需要更新的字段")
    if has_avatar:
        user.avatar = _decode_avatar(avatar_value)
    for field_name, value in values.items():
        setattr(user, field_name, value)
    summary = "更新头像" if has_avatar and not values else "个人中心更新资料"
    add_audit_log(
        db,
        actor_id=user.id,
        action_type="UPDATE",
        resource_type="USER",
        resource_id=user.id,
        request_summary=summary,
        result_status="SUCCESS",
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateResourceError("邮箱已被其他用户使用") from None
    db.refresh(user)
    return user


def change_password(db: Session, user: User, data: PasswordChange) -> None:
    """个人中心修改自己的密码；校验原密码后重置哈希。"""

    if not verify_password(data.old_password, user.password_hash):
        raise BusinessValidationError("原密码不正确")
    if data.old_password == data.new_password:
        raise BusinessValidationError("新密码不能与原密码相同")
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    add_audit_log(
        db,
        actor_id=user.id,
        action_type="CHANGE_PASSWORD",
        resource_type="USER",
        resource_id=user.id,
        request_summary="个人中心修改登录密码",
        result_status="SUCCESS",
    )
    db.commit()
