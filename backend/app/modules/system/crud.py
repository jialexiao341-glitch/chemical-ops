"""系统管理模块的数据持久化操作。"""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.modules.system.model import Department, Permission, Role, RolePermission, User, UserRole


def get_user(db: Session, user_id: int) -> User | None:
    """按 ID 查询用户。"""

    return db.scalar(select(User).where(User.id == user_id))


def get_user_by_username(db: Session, username: str) -> User | None:
    """按登录名查询用户。"""

    return db.scalar(select(User).where(User.username == username))


def list_users(db: Session, keyword: str | None, status: str | None, page: int, page_size: int) -> tuple[list[User], int]:
    """分页查询用户。"""

    conditions = []
    if keyword:
        conditions.append((User.username.like(f"%{keyword}%")) | (User.display_name.like(f"%{keyword}%")))
    if status:
        conditions.append(User.status == status)
    total = db.scalar(select(func.count(User.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(User).where(*conditions).order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return items, total


def get_department(db: Session, department_id: int) -> Department | None:
    """按 ID 查询部门。"""

    return db.scalar(select(Department).where(Department.id == department_id))


def list_departments(db: Session, keyword: str | None, status: str | None, page: int, page_size: int) -> tuple[list[Department], int]:
    """分页查询部门。"""

    conditions = []
    if keyword:
        conditions.append((Department.department_code.like(f"%{keyword}%")) | (Department.department_name.like(f"%{keyword}%")))
    if status:
        conditions.append(Department.status == status)
    total = db.scalar(select(func.count(Department.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(Department).where(*conditions).order_by(Department.id.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return items, total


def get_role(db: Session, role_id: int) -> Role | None:
    """按 ID 查询角色。"""

    return db.scalar(select(Role).where(Role.id == role_id))


def get_role_by_code(db: Session, role_code: str) -> Role | None:
    """按角色编码查询角色。"""

    return db.scalar(select(Role).where(Role.role_code == role_code))


def list_roles(db: Session, keyword: str | None, status: str | None, page: int, page_size: int) -> tuple[list[Role], int]:
    """分页查询角色。"""

    conditions = []
    if keyword:
        conditions.append((Role.role_code.like(f"%{keyword}%")) | (Role.role_name.like(f"%{keyword}%")))
    if status:
        conditions.append(Role.status == status)
    total = db.scalar(select(func.count(Role.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(Role).where(*conditions).order_by(Role.id.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return items, total


def get_permission(db: Session, permission_id: int) -> Permission | None:
    """按 ID 查询权限。"""

    return db.scalar(select(Permission).where(Permission.id == permission_id))


def get_permission_by_code(db: Session, permission_code: str) -> Permission | None:
    """按权限编码查询权限。"""

    return db.scalar(select(Permission).where(Permission.permission_code == permission_code))


def list_permissions(db: Session, keyword: str | None, permission_type: str | None, page: int, page_size: int) -> tuple[list[Permission], int]:
    """分页查询权限。"""

    conditions = []
    if keyword:
        conditions.append((Permission.permission_code.like(f"%{keyword}%")) | (Permission.permission_name.like(f"%{keyword}%")))
    if permission_type:
        conditions.append(Permission.permission_type == permission_type)
    total = db.scalar(select(func.count(Permission.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(Permission).where(*conditions).order_by(Permission.id.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return items, total


def get_user_role_ids(db: Session, user_id: int) -> list[int]:
    """查询用户当前绑定的角色 ID。"""

    return list(db.scalars(select(UserRole.role_id).where(UserRole.user_id == user_id)).all())


def get_user_role_codes(db: Session, user_id: int) -> list[str]:
    """查询用户当前绑定的角色编码。"""

    return list(
        db.scalars(
            select(Role.role_code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.status == "ACTIVE")
        ).all()
    )


def get_user_permission_codes(db: Session, user_id: int) -> list[str]:
    """查询用户通过角色获得的全部有效权限编码。"""

    return list(
        db.scalars(
            select(Permission.permission_code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .join(Role, Role.id == RolePermission.role_id)
            .where(UserRole.user_id == user_id, Role.status == "ACTIVE")
            .distinct()
        ).all()
    )


def replace_user_roles(db: Session, user_id: int, role_ids: list[int]) -> None:
    """用新的角色集合替换用户角色关联。"""

    db.execute(delete(UserRole).where(UserRole.user_id == user_id))
    db.add_all([UserRole(user_id=user_id, role_id=role_id) for role_id in sorted(set(role_ids))])


def add_entity(db: Session, entity: object) -> object:
    """新增任意系统实体并提交事务。"""

    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


def update_entity(db: Session, entity: object, values: dict) -> object:
    """更新系统实体字段并提交事务。"""

    for field, value in values.items():
        setattr(entity, field, value)
    db.commit()
    db.refresh(entity)
    return entity


def disable_entity(db: Session, entity: object) -> object:
    """将带状态的系统实体停用并提交事务。"""

    setattr(entity, "status", "INACTIVE")
    db.commit()
    db.refresh(entity)
    return entity
