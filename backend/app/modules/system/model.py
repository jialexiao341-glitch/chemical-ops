"""系统管理相关数据库模型。"""

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMBLOB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    """系统登录用户。"""

    __tablename__ = "sys_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("sys_departments.id"), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    token_version: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")
    # 个人中心头像原图（客户端已压缩）；列表接口的 UserRead 不声明该字段，不会外泄
    avatar: Mapped[bytes | None] = mapped_column(MEDIUMBLOB, nullable=True, deferred=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )


class Department(Base):
    """组织部门。"""

    __tablename__ = "sys_departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sys_departments.id"), nullable=True)
    department_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    department_name: Mapped[str] = mapped_column(String(128), nullable=False)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )


class Role(Base):
    """系统角色。"""

    __tablename__ = "sys_roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )


class Permission(Base):
    """系统权限。"""

    __tablename__ = "sys_permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    permission_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    permission_name: Mapped[str] = mapped_column(String(128), nullable=False)
    permission_type: Mapped[str] = mapped_column(String(20), nullable=False)
    resource: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )


class UserRole(Base):
    """用户和角色的关联记录。"""

    __tablename__ = "sys_user_roles"

    user_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("sys_roles.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )


class RolePermission(Base):
    """角色和权限的关联记录。"""

    __tablename__ = "sys_role_permissions"

    role_id: Mapped[int] = mapped_column(ForeignKey("sys_roles.id"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("sys_permissions.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
