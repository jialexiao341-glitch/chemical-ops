"""创建 ChemicalOps 初始管理员、角色和基础权限。"""

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.system.model import Permission, Role, RolePermission, User, UserRole


PERMISSIONS = (
    ("quality.acceptances.assign", "创建并指派质量验收", "API", "quality.acceptances", "assign"),
    ("system.users.read", "查看用户", "API", "system.users", "read"),
    ("system.users.write", "管理用户", "API", "system.users", "write"),
    ("system.departments.read", "查看部门", "API", "system.departments", "read"),
    ("system.departments.write", "管理部门", "API", "system.departments", "write"),
    ("system.roles.read", "查看角色", "API", "system.roles", "read"),
    ("system.roles.write", "管理角色", "API", "system.roles", "write"),
    ("system.permissions.read", "查看权限", "API", "system.permissions", "read"),
    ("system.permissions.write", "管理权限", "API", "system.permissions", "write"),
    ("master.chemicals.read", "查看化学品", "API", "master.chemicals", "read"),
    ("master.chemicals.write", "管理化学品", "API", "master.chemicals", "write"),
    ("master.products.read", "查看产品", "API", "master.products", "read"),
    ("master.products.write", "管理产品", "API", "master.products", "write"),
    ("master.suppliers.read", "查看供应商", "API", "master.suppliers", "read"),
    ("master.suppliers.write", "管理供应商", "API", "master.suppliers", "write"),
    ("finance.reconciliations.read", "查看财务对账", "API", "finance.reconciliations", "read"),
    ("finance.reconciliations.write", "管理财务对账", "API", "finance.reconciliations", "write"),
    ("finance.invoices.read", "查看供应商发票", "API", "finance.invoices", "read"),
    ("finance.invoices.write", "录入供应商发票", "API", "finance.invoices", "write"),
    ("finance.invoices.verify", "核验供应商发票", "API", "finance.invoices", "verify"),
    ("finance.payments.read", "查看付款记录", "API", "finance.payments", "read"),
    ("finance.payments.write", "管理付款记录", "API", "finance.payments", "write"),
    ("finance.payments.approve", "审批付款申请", "API", "finance.payments", "approve"),
    ("finance.settlements.read", "查看采购结算", "API", "finance.settlements", "read"),
    ("finance.settlements.write", "管理采购结算", "API", "finance.settlements", "write"),
    ("finance.settlements.approve", "确认采购结算", "API", "finance.settlements", "approve"),
    ("warehouse.inventory.return.read", "查看供应商退货", "API", "warehouse.inventory.return", "read"),
    ("warehouse.inventory.return.write", "管理供应商退货", "API", "warehouse.inventory.return", "write"),
    ("warehouse.inventory.return.approve", "审批供应商退货", "API", "warehouse.inventory.return", "approve"),
    ("procurement.replenishment.read", "查看供应商补货", "API", "procurement.replenishment", "read"),
    ("procurement.replenishment.write", "管理供应商补货", "API", "procurement.replenishment", "write"),
    ("procurement.replenishment.approve", "审批供应商补货", "API", "procurement.replenishment", "approve"),
)


def main() -> None:
    """创建或补齐初始管理员数据，不覆盖已存在用户的密码。"""

    settings = get_settings()
    if not settings.admin_password:
        raise SystemExit("请先在 .env 中设置 ADMIN_PASSWORD")

    db = SessionLocal()
    try:
        role = db.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
        if role is None:
            role = Role(role_code="SYS_ADMIN", role_name="系统管理员", description="拥有系统管理权限")
            db.add(role)
            db.flush()

        permission_ids = []
        for code, name, permission_type, resource, action in PERMISSIONS:
            permission = db.scalar(select(Permission).where(Permission.permission_code == code))
            if permission is None:
                permission = Permission(
                    permission_code=code,
                    permission_name=name,
                    permission_type=permission_type,
                    resource=resource,
                    action=action,
                )
                db.add(permission)
                db.flush()
            permission_ids.append(permission.id)

        current_permission_ids = set(
            db.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)).all()
        )
        for permission_id in set(permission_ids) - current_permission_ids:
            db.add(RolePermission(role_id=role.id, permission_id=permission_id))

        user = db.scalar(select(User).where(User.username == settings.admin_username))
        if user is None:
            user = User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                display_name=settings.admin_display_name,
                status="ACTIVE",
            )
            db.add(user)
            db.flush()

        role_binding = db.scalar(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
        )
        if role_binding is None:
            db.add(UserRole(user_id=user.id, role_id=role.id))

        db.commit()
        print(f"admin_ready={settings.admin_username}")
        print(f"permission_count={len(permission_ids)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
