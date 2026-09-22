"""系统管理和登录认证业务服务。"""

import base64
import binascii
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.core.security import create_access_token, hash_password, verify_password
from app.modules.system import crud
from app.modules.system.model import Department, Permission, Role, RolePermission, User
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
    UserCreate,
    UserUpdate,
)


def _require_user(db: Session, user_id: int) -> User:
    """查询用户并确保用户存在。"""

    user = crud.get_user(db, user_id)
    if user is None:
        raise ResourceNotFoundError(f"用户 {user_id} 不存在")
    return user


def _require_roles(db: Session, role_ids: list[int]) -> None:
    """校验角色 ID 全部存在。"""

    if not role_ids:
        return
    actual = set(db.scalars(select(Role.id).where(Role.id.in_(set(role_ids)))).all())
    missing = sorted(set(role_ids) - actual)
    if missing:
        raise ResourceNotFoundError(f"角色不存在：{missing}")


def _require_department(db: Session, department_id: int | None) -> None:
    """校验部门 ID 存在。"""

    if department_id is not None and crud.get_department(db, department_id) is None:
        raise ResourceNotFoundError(f"部门 {department_id} 不存在")


def list_users(db: Session, keyword: str | None, status: str | None, page: int, page_size: int):
    """查询用户分页列表。"""

    return crud.list_users(db, keyword, status, page, page_size)


def create_user(db: Session, data: UserCreate) -> User:
    """校验用户名、部门和角色后创建用户。"""

    if crud.get_user_by_username(db, data.username):
        raise DuplicateResourceError(f"用户名 {data.username} 已存在")
    _require_department(db, data.department_id)
    _require_roles(db, data.role_ids)
    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
        department_id=data.department_id,
        email=data.email,
        phone=data.phone,
    )
    db.add(user)
    db.flush()
    crud.replace_user_roles(db, user.id, data.role_ids)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user_id: int, data: UserUpdate) -> User:
    """更新用户资料、状态、密码和角色关联。"""

    user = _require_user(db, user_id)
    values = data.model_dump(exclude_unset=True, exclude={"password", "role_ids"})
    if data.password is not None:
        values["password_hash"] = hash_password(data.password)
    _require_department(db, data.department_id)
    if data.role_ids is not None:
        _require_roles(db, data.role_ids)
        crud.replace_user_roles(db, user.id, data.role_ids)
    return crud.update_entity(db, user, values)


def delete_user(db: Session, user_id: int) -> User:
    """软删除用户并保留历史操作记录。"""

    return crud.disable_entity(db, _require_user(db, user_id))


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


def delete_department(db: Session, department_id: int) -> Department:
    """软删除部门，将状态设置为 INACTIVE。"""

    department = crud.get_department(db, department_id)
    if department is None:
        raise ResourceNotFoundError(f"部门 {department_id} 不存在")
    return crud.disable_entity(db, department)


def list_roles(db: Session, keyword: str | None, status: str | None, page: int, page_size: int):
    """查询角色分页列表。"""

    return crud.list_roles(db, keyword, status, page, page_size)


def create_role(db: Session, data: RoleCreate) -> Role:
    """校验角色编码和权限后创建角色。"""

    if crud.get_role_by_code(db, data.role_code):
        raise DuplicateResourceError(f"角色编码 {data.role_code} 已存在")
    _require_permissions(db, data.permission_ids)
    role = Role(role_code=data.role_code, role_name=data.role_name, description=data.description)
    db.add(role)
    db.flush()
    for permission_id in sorted(set(data.permission_ids)):
        db.add(RolePermission(role_id=role.id, permission_id=permission_id))
    db.commit()
    db.refresh(role)
    return role


def update_role(db: Session, role_id: int, data: RoleUpdate) -> Role:
    """更新角色资料和权限关联。"""

    role = crud.get_role(db, role_id)
    if role is None:
        raise ResourceNotFoundError(f"角色 {role_id} 不存在")
    values = data.model_dump(exclude_unset=True, exclude={"permission_ids"})
    if data.permission_ids is not None:
        _require_permissions(db, data.permission_ids)
        db.query(RolePermission).filter_by(role_id=role_id).delete()
        for permission_id in sorted(set(data.permission_ids)):
            db.add(RolePermission(role_id=role_id, permission_id=permission_id))
    return crud.update_entity(db, role, values)


def _require_permissions(db: Session, permission_ids: list[int]) -> None:
    """校验权限 ID 全部存在。"""

    if not permission_ids:
        return
    actual = set(db.scalars(select(Permission.id).where(Permission.id.in_(set(permission_ids)))).all())
    missing = sorted(set(permission_ids) - actual)
    if missing:
        raise ResourceNotFoundError(f"权限不存在：{missing}")


def delete_role(db: Session, role_id: int) -> Role:
    """软删除角色，将状态设置为 INACTIVE。"""

    role = crud.get_role(db, role_id)
    if role is None:
        raise ResourceNotFoundError(f"角色 {role_id} 不存在")
    return crud.disable_entity(db, role)


def list_permissions(db: Session, keyword: str | None, permission_type: str | None, page: int, page_size: int):
    """查询权限分页列表。"""

    return crud.list_permissions(db, keyword, permission_type, page, page_size)


def create_permission(db: Session, data: PermissionCreate) -> Permission:
    """校验权限编码后创建权限。"""

    if crud.get_permission_by_code(db, data.permission_code):
        raise DuplicateResourceError(f"权限编码 {data.permission_code} 已存在")
    return crud.add_entity(db, Permission(**data.model_dump()))


def update_permission(db: Session, permission_id: int, data: PermissionUpdate) -> Permission:
    """更新权限名称、类型、资源或操作。"""

    permission = crud.get_permission(db, permission_id)
    if permission is None:
        raise ResourceNotFoundError(f"权限 {permission_id} 不存在")
    return crud.update_entity(db, permission, data.model_dump(exclude_unset=True))


def delete_permission(db: Session, permission_id: int) -> Permission:
    """权限表没有状态字段，删除前必须确认没有角色引用。"""

    permission = crud.get_permission(db, permission_id)
    if permission is None:
        raise ResourceNotFoundError(f"权限 {permission_id} 不存在")
    if db.scalar(select(RolePermission).where(RolePermission.permission_id == permission_id).limit(1)):
        raise BusinessValidationError("权限已绑定角色，不能直接删除")
    db.delete(permission)
    db.commit()
    return permission


def login(db: Session, data: LoginRequest) -> tuple[str, int]:
    """校验登录凭据并生成访问令牌。"""

    user = crud.get_user_by_username(db, data.username)
    if user is None or user.status != "ACTIVE" or not verify_password(data.password, user.password_hash):
        raise AuthenticationError("用户名或密码错误")
    user.last_login_at = datetime.now()
    db.commit()
    from app.core.config import get_settings

    settings = get_settings()
    return create_access_token(user.id), settings.access_token_expire_minutes * 60


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
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: User, data: PasswordChange) -> None:
    """个人中心修改自己的密码；校验原密码后重置哈希。"""

    if not verify_password(data.old_password, user.password_hash):
        raise BusinessValidationError("原密码不正确")
    if data.old_password == data.new_password:
        raise BusinessValidationError("新密码不能与原密码相同")
    user.password_hash = hash_password(data.new_password)
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
