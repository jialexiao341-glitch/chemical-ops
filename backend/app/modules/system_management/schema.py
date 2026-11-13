"""系统管理模块的 Pydantic 请求和响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class UserDepartmentScopeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    department_ids: list[int] = Field(default_factory=list, max_length=500)


class UserDepartmentScopeRead(BaseModel):
    enabled: bool
    department_ids: list[int]


class UserWarehouseScopeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    warehouse_ids: list[int] = Field(default_factory=list, max_length=500)


class UserWarehouseScopeRead(BaseModel):
    enabled: bool
    warehouse_ids: list[int]


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
    # 详情/更新接口会填充；分页列表不逐行查角色，保持 None
    role_ids: list[int] | None = None
    role_codes: list[str] = Field(default_factory=list)
    role_names: list[str] = Field(default_factory=list)


class RegistrationCreate(BaseModel):
    """公开注册只能申请一个非管理员角色，其他管理字段禁止提交。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    username: str = Field(min_length=8, max_length=16, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=16)
    display_name: str = Field(min_length=1, max_length=100)
    role_code: str = Field(min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    avatar_base64: str | None = Field(default=None, max_length=3_000_000)

    @field_validator("username", "password")
    @classmethod
    def require_mixed_case(cls, value: str) -> str:
        if not any("A" <= char <= "Z" for char in value) or not any("a" <= char <= "z" for char in value):
            raise ValueError("账号名和密码均须为 8–16 位，并同时包含大写和小写字母")
        return value


class RegistrationRoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    role_code: str
    role_name: str


class RegistrationRead(BaseModel):
    username: str
    status: str


class RegistrationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    reason: str = Field(default="", max_length=500)


class SupplierBindingUpdate(BaseModel):
    """管理员为用户选择一个启用的供应商。"""

    supplier_id: int = Field(gt=0)


class SupplierBindingOption(BaseModel):
    """绑定选择器仅返回供应商编号和名称。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_code: str
    supplier_name: str


class SupplierBindingRead(BaseModel):
    """用户当前的供应商绑定，包括停用状态。"""

    supplier_id: int
    supplier_code: str
    supplier_name: str
    supplier_status: str
    status: str


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
