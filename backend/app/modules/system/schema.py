"""系统管理模块的 Pydantic 请求和响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    """创建用户时提交的字段。"""

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    department_id: int | None = Field(default=None, gt=0)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    role_ids: list[int] = Field(default_factory=list)


class ProfileUpdate(BaseModel):
    """个人中心更新自己的资料。

    只开放昵称/邮箱/手机/头像；角色、部门、状态属于管理动作，
    必须走 /system/users 并受对应权限码保护。
    avatar_base64：图片 base64（可带 data: 前缀）更新头像，null/空串清除。
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    avatar_base64: str | None = Field(default=None, max_length=3_000_000)


class PasswordChange(BaseModel):
    """个人中心修改自己的登录密码。"""

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    """更新用户时提交的可选字段。"""

    password: str | None = Field(default=None, min_length=8, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    department_id: int | None = Field(default=None, gt=0)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, pattern="^(ACTIVE|LOCKED|INACTIVE)$")
    role_ids: list[int] | None = None


class UserRead(BaseModel):
    """用户响应，不返回密码哈希。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    department_id: int | None
    email: str | None
    phone: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class UserPage(BaseModel):
    """分页用户列表响应。"""

    items: list[UserRead]
    total: int
    page: int
    page_size: int


class DepartmentCreate(BaseModel):
    """创建部门时提交的字段。"""

    parent_id: int | None = Field(default=None, gt=0)
    department_code: str = Field(min_length=1, max_length=64)
    department_name: str = Field(min_length=1, max_length=128)
    manager_id: int | None = Field(default=None, gt=0)


class DepartmentUpdate(BaseModel):
    """更新部门时提交的可选字段。"""

    parent_id: int | None = Field(default=None, gt=0)
    department_name: str | None = Field(default=None, min_length=1, max_length=128)
    manager_id: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, pattern="^(ACTIVE|INACTIVE)$")


class DepartmentRead(BaseModel):
    """部门响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None
    department_code: str
    department_name: str
    manager_id: int | None
    status: str
    created_at: datetime
    updated_at: datetime


class DepartmentPage(BaseModel):
    """分页部门列表响应。"""

    items: list[DepartmentRead]
    total: int
    page: int
    page_size: int


class RoleCreate(BaseModel):
    """创建角色时提交的字段。"""

    role_code: str = Field(min_length=1, max_length=64)
    role_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permission_ids: list[int] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    """更新角色时提交的可选字段。"""

    role_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern="^(ACTIVE|INACTIVE)$")
    permission_ids: list[int] | None = None


class RoleRead(BaseModel):
    """角色响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role_code: str
    role_name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class RolePage(BaseModel):
    """分页角色列表响应。"""

    items: list[RoleRead]
    total: int
    page: int
    page_size: int


class PermissionCreate(BaseModel):
    """创建权限时提交的字段。"""

    permission_code: str = Field(min_length=1, max_length=128)
    permission_name: str = Field(min_length=1, max_length=128)
    permission_type: str = Field(min_length=1, max_length=20)
    resource: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)


class PermissionUpdate(BaseModel):
    """更新权限时提交的可选字段。"""

    permission_name: str | None = Field(default=None, min_length=1, max_length=128)
    permission_type: str | None = Field(default=None, min_length=1, max_length=20)
    resource: str | None = Field(default=None, min_length=1, max_length=128)
    action: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)


class PermissionRead(BaseModel):
    """权限响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    permission_code: str
    permission_name: str
    permission_type: str
    resource: str
    action: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class PermissionPage(BaseModel):
    """分页权限列表响应。"""

    items: list[PermissionRead]
    total: int
    page: int
    page_size: int


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """登录成功后的访问令牌响应。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUserRead(UserRead):
    """当前用户信息及权限摘要。"""

    role_codes: list[str]
    permission_codes: list[str]
    # 头像以 data URL 返回（data:image/...;base64,...），img 直接可用、无需鉴权头
    avatar: str | None = None
