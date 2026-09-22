"""系统管理和认证相关的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_permission
from app.core.db import get_db
from app.core.errors import ResourceNotFoundError
from app.modules.system import crud, service
from app.modules.system.model import User
from app.modules.system.schema import (
    CurrentUserRead,
    DepartmentCreate,
    DepartmentPage,
    DepartmentRead,
    DepartmentUpdate,
    LoginRequest,
    PasswordChange,
    PermissionCreate,
    PermissionPage,
    PermissionRead,
    PermissionUpdate,
    ProfileUpdate,
    RoleCreate,
    RolePage,
    RoleRead,
    RoleUpdate,
    TokenResponse,
    UserCreate,
    UserPage,
    UserRead,
    UserUpdate,
)


router = APIRouter(tags=["系统管理"])
auth_router = APIRouter(prefix="/auth", tags=["登录认证"])


def _current_user_response(db: Session, user: User) -> CurrentUserRead:
    """组装当前用户、角色和权限信息。"""

    data = UserRead.model_validate(user).model_dump()
    data["role_codes"] = crud.get_user_role_codes(db, user.id)
    data["permission_codes"] = crud.get_user_permission_codes(db, user.id)
    return CurrentUserRead.model_validate(data)


@auth_router.post("/login", response_model=TokenResponse, summary="用户登录")
def login(data: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """校验用户名和密码，返回 Bearer JWT 访问令牌。"""

    token, expires_in = service.login(db, data)
    return TokenResponse(access_token=token, expires_in=expires_in)


@auth_router.get("/me", response_model=CurrentUserRead, summary="查询当前用户")
def current_user(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> CurrentUserRead:
    """返回当前登录用户的基本信息、角色和权限。"""

    return _current_user_response(db, user)


@auth_router.patch("/me", response_model=CurrentUserRead, summary="更新个人资料")
def update_current_user(
    data: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CurrentUserRead:
    """个人中心更新昵称/邮箱/手机（不含角色与部门）。"""

    service.update_profile(db, user, data)
    return _current_user_response(db, user)


@auth_router.put("/me/password", summary="修改个人登录密码")
def change_current_password(
    data: PasswordChange,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """校验原密码后修改自己的登录密码；JWT 无状态，旧令牌到期前仍有效。"""

    service.change_password(db, user, data)
    return {"changed": True}


@router.post("/system/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="新增用户")
def create_user(data: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("system.users.write"))) -> UserRead:
    """新增用户，并按请求中的角色 ID 建立用户角色关联。"""

    return service.create_user(db, data)


@router.get("/system/users", response_model=UserPage, summary="分页查询用户")
def list_users(
    keyword: str | None = Query(default=None, description="按用户名或显示姓名模糊查询"),
    status: str | None = Query(default=None, pattern="^(ACTIVE|LOCKED|INACTIVE)$", description="用户状态"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.users.read")),
) -> UserPage:
    """分页查询系统用户，不返回密码哈希。"""

    items, total = service.list_users(db, keyword, status, page, page_size)
    return UserPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/system/users/{user_id}", response_model=UserRead, summary="查询用户详情")
def get_user(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("system.users.read"))) -> UserRead:
    """按用户 ID 查询用户详情。"""

    return service._require_user(db, user_id)


@router.patch("/system/users/{user_id}", response_model=UserRead, summary="更新用户")
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), _: User = Depends(require_permission("system.users.write"))) -> UserRead:
    """部分更新用户资料、密码、状态和角色。"""

    return service.update_user(db, user_id, data)


@router.delete("/system/users/{user_id}", response_model=UserRead, summary="停用用户")
def delete_user(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("system.users.write"))) -> UserRead:
    """软删除用户，将状态改为 INACTIVE。"""

    return service.delete_user(db, user_id)


@router.post("/system/departments", response_model=DepartmentRead, status_code=status.HTTP_201_CREATED, summary="新增部门")
def create_department(data: DepartmentCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("system.departments.write"))) -> DepartmentRead:
    """创建部门并校验父部门和负责人。"""

    return service.create_department(db, data)


@router.get("/system/departments", response_model=DepartmentPage, summary="分页查询部门")
def list_departments(
    keyword: str | None = Query(default=None, description="按编码或名称查询"),
    status: str | None = Query(default=None, pattern="^(ACTIVE|INACTIVE)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.departments.read")),
) -> DepartmentPage:
    """分页查询部门。"""

    items, total = service.list_departments(db, keyword, status, page, page_size)
    return DepartmentPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/system/departments/{department_id}", response_model=DepartmentRead, summary="查询部门详情")
def get_department(department_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("system.departments.read"))) -> DepartmentRead:
    """按部门 ID 查询详情。"""

    department = crud.get_department(db, department_id)
    if department is None:
        raise ResourceNotFoundError(f"部门 {department_id} 不存在")
    return department


@router.patch("/system/departments/{department_id}", response_model=DepartmentRead, summary="更新部门")
def update_department(department_id: int, data: DepartmentUpdate, db: Session = Depends(get_db), _: User = Depends(require_permission("system.departments.write"))) -> DepartmentRead:
    """部分更新部门信息。"""

    return service.update_department(db, department_id, data)


@router.delete("/system/departments/{department_id}", response_model=DepartmentRead, summary="停用部门")
def delete_department(department_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("system.departments.write"))) -> DepartmentRead:
    """软删除部门，将状态改为 INACTIVE。"""

    return service.delete_department(db, department_id)


@router.post("/system/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED, summary="新增角色")
def create_role(data: RoleCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("system.roles.write"))) -> RoleRead:
    """创建角色并绑定权限。"""

    return service.create_role(db, data)


@router.get("/system/roles", response_model=RolePage, summary="分页查询角色")
def list_roles(
    keyword: str | None = Query(default=None, description="按编码或名称查询"),
    status: str | None = Query(default=None, pattern="^(ACTIVE|INACTIVE)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.roles.read")),
) -> RolePage:
    """分页查询角色。"""

    items, total = service.list_roles(db, keyword, status, page, page_size)
    return RolePage(items=items, total=total, page=page, page_size=page_size)


@router.get("/system/roles/{role_id}", response_model=RoleRead, summary="查询角色详情")
def get_role(role_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("system.roles.read"))) -> RoleRead:
    """按角色 ID 查询详情。"""

    role = crud.get_role(db, role_id)
    if role is None:
        raise ResourceNotFoundError(f"角色 {role_id} 不存在")
    return role


@router.patch("/system/roles/{role_id}", response_model=RoleRead, summary="更新角色")
def update_role(role_id: int, data: RoleUpdate, db: Session = Depends(get_db), _: User = Depends(require_permission("system.roles.write"))) -> RoleRead:
    """部分更新角色并替换权限关联。"""

    return service.update_role(db, role_id, data)


@router.delete("/system/roles/{role_id}", response_model=RoleRead, summary="停用角色")
def delete_role(role_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("system.roles.write"))) -> RoleRead:
    """软删除角色，将状态改为 INACTIVE。"""

    return service.delete_role(db, role_id)


@router.post("/system/permissions", response_model=PermissionRead, status_code=status.HTTP_201_CREATED, summary="新增权限")
def create_permission(data: PermissionCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("system.permissions.write"))) -> PermissionRead:
    """创建一条系统权限。"""

    return service.create_permission(db, data)


@router.get("/system/permissions", response_model=PermissionPage, summary="分页查询权限")
def list_permissions(
    keyword: str | None = Query(default=None, description="按编码或名称查询"),
    permission_type: str | None = Query(default=None, description="权限类型"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.permissions.read")),
) -> PermissionPage:
    """分页查询权限。"""

    items, total = service.list_permissions(db, keyword, permission_type, page, page_size)
    return PermissionPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/system/permissions/{permission_id}", response_model=PermissionRead, summary="查询权限详情")
def get_permission(permission_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("system.permissions.read"))) -> PermissionRead:
    """按权限 ID 查询详情。"""

    permission = crud.get_permission(db, permission_id)
    if permission is None:
        raise ResourceNotFoundError(f"权限 {permission_id} 不存在")
    return permission


@router.patch("/system/permissions/{permission_id}", response_model=PermissionRead, summary="更新权限")
def update_permission(permission_id: int, data: PermissionUpdate, db: Session = Depends(get_db), _: User = Depends(require_permission("system.permissions.write"))) -> PermissionRead:
    """部分更新权限信息。"""

    return service.update_permission(db, permission_id, data)


@router.delete("/system/permissions/{permission_id}", response_model=PermissionRead, summary="删除权限")
def delete_permission(permission_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("system.permissions.write"))) -> PermissionRead:
    """删除未绑定角色的权限。"""

    return service.delete_permission(db, permission_id)
