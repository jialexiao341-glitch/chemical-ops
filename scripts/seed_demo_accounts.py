"""创建开发环境使用的演示部门、角色、权限和用户账号。"""

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.system.model import Department, Permission, Role, RolePermission, User, UserRole
from app.modules.supplier_portal.model import SupplierPortalAccount
from app.modules.suppliers.model import Supplier


PERMISSIONS = (
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
    ("procurement.requests.read", "查看采购申请", "API", "procurement.requests", "read"),
    ("procurement.requests.write", "管理采购申请", "API", "procurement.requests", "write"),
    ("procurement.requests.approve", "审批采购申请", "API", "procurement.requests", "approve"),
    ("procurement.rfqs.read", "查看询价单", "API", "procurement.rfqs", "read"),
    ("procurement.rfqs.write", "管理询价单", "API", "procurement.rfqs", "write"),
    ("procurement.rfqs.quote", "录入供应商报价", "API", "procurement.rfqs", "quote"),
    ("procurement.rfqs.compare", "生成比价和定标", "API", "procurement.rfqs", "compare"),
    ("procurement.orders.read", "查看采购订单", "API", "procurement.orders", "read"),
    ("procurement.orders.write", "管理采购订单", "API", "procurement.orders", "write"),
    ("procurement.orders.approve", "审批采购订单", "API", "procurement.orders", "approve"),
    ("warehouse.deliveries.read", "查看到货单", "API", "warehouse.deliveries", "read"),
    ("warehouse.deliveries.write", "管理到货和收货", "API", "warehouse.deliveries", "write"),
    ("quality.acceptances.read", "查看质量验收", "API", "quality.acceptances", "read"),
    ("quality.acceptances.write", "管理质量验收", "API", "quality.acceptances", "write"),
    ("quality.acceptances.review", "复核质量报告", "API", "quality.acceptances", "review"),
    ("warehouse.inventory.read", "查看库存", "API", "warehouse.inventory", "read"),
    ("warehouse.inventory.write", "执行库存入库", "API", "warehouse.inventory", "write"),
    ("warehouse.inventory.issue.read", "查看库存领用", "API", "warehouse.inventory.issue", "read"),
    ("warehouse.inventory.issue.write", "管理库存领用", "API", "warehouse.inventory.issue", "write"),
    ("warehouse.inventory.issue.approve", "审批库存领用", "API", "warehouse.inventory.issue", "approve"),
    ("warehouse.inventory.transfer.read", "查看库存调拨", "API", "warehouse.inventory.transfer", "read"),
    ("warehouse.inventory.transfer.write", "管理库存调拨", "API", "warehouse.inventory.transfer", "write"),
    ("warehouse.inventory.transfer.approve", "审批库存调拨", "API", "warehouse.inventory.transfer", "approve"),
    ("warehouse.inventory.stocktake.read", "查看库存盘点", "API", "warehouse.inventory.stocktake", "read"),
    ("warehouse.inventory.stocktake.write", "管理库存盘点", "API", "warehouse.inventory.stocktake", "write"),
    ("warehouse.inventory.stocktake.approve", "审批库存盘点", "API", "warehouse.inventory.stocktake", "approve"),
    ("warehouse.inventory.freeze.write", "冻结和解冻库存", "API", "warehouse.inventory.freeze", "write"),
    ("operations.exceptions.read", "查看运营异常", "API", "operations.exceptions", "read"),
    ("operations.exceptions.write", "管理运营异常", "API", "operations.exceptions", "write"),
    ("system.notifications.read", "查看站内通知", "API", "system.notifications", "read"),
    ("system.notifications.write", "处理站内通知", "API", "system.notifications", "write"),
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
    ("supplier.portal.read", "查询供应商门户订单", "API", "supplier.portal", "read"),
    ("supplier.portal.confirm", "确认供应商采购订单", "API", "supplier.portal", "confirm"),
    ("system.files.read", "查看文件元数据", "API", "system.files", "read"),
    ("system.files.download", "下载文件", "API", "system.files", "download"),
    ("system.files.write", "上传文件", "API", "system.files", "write"),
    ("system.files.attach", "关联业务附件", "API", "system.files", "attach"),
    ("warehouse.inventory.cost.write", "执行 FIFO 成本出库", "API", "warehouse.inventory.cost", "write"),
    ("dashboard.read", "查看运营 Dashboard", "API", "dashboard", "read"),
)

DEPARTMENTS = (
    ("PROCUREMENT", "采购部"),
    ("R_AND_D", "技术研发部"),
    ("WAREHOUSE", "仓储部"),
    ("QUALITY", "质量部"),
    ("FINANCE", "财务部"),
    ("MANAGEMENT", "管理层"),
)

ROLE_SCOPES = {
    "SYS_ADMIN": {code for code, *_ in PERMISSIONS},
    "PROCUREMENT_MANAGER": {
        "master.chemicals.read", "master.chemicals.write", "master.products.read", "master.products.write",
        "master.suppliers.read", "master.suppliers.write",
        "procurement.requests.read", "procurement.requests.write", "procurement.requests.approve",
        "procurement.rfqs.read", "procurement.rfqs.write", "procurement.rfqs.quote", "procurement.rfqs.compare",
        "procurement.orders.read", "procurement.orders.write", "procurement.orders.approve",
        "warehouse.deliveries.read", "warehouse.deliveries.write",
        "quality.acceptances.read", "quality.acceptances.write",
        "warehouse.inventory.read", "warehouse.inventory.write",
        "warehouse.inventory.issue.read", "warehouse.inventory.issue.write", "warehouse.inventory.issue.approve",
        "warehouse.inventory.transfer.read", "warehouse.inventory.transfer.write", "warehouse.inventory.transfer.approve",
        "warehouse.inventory.stocktake.read", "warehouse.inventory.stocktake.write", "warehouse.inventory.stocktake.approve",
        "warehouse.inventory.freeze.write",
        "operations.exceptions.read", "operations.exceptions.write",
        "system.notifications.read", "system.notifications.write",
        "system.files.read", "system.files.download", "system.files.write", "system.files.attach", "warehouse.inventory.cost.write",
        "dashboard.read",
        "warehouse.inventory.return.read", "warehouse.inventory.return.write", "warehouse.inventory.return.approve",
        "procurement.replenishment.read", "procurement.replenishment.write", "procurement.replenishment.approve",
    },
    "BUYER": {
        "master.chemicals.read", "master.products.read",
        "master.suppliers.read", "master.suppliers.write",
        "procurement.requests.read", "procurement.requests.write",
        "procurement.rfqs.read", "procurement.rfqs.write", "procurement.rfqs.quote", "procurement.rfqs.compare",
        "procurement.orders.read", "procurement.orders.write",
        "warehouse.deliveries.read",
        "warehouse.inventory.read",
        "warehouse.inventory.issue.read",
        "warehouse.inventory.transfer.read",
        "warehouse.inventory.stocktake.read",
        "operations.exceptions.read",
        "system.notifications.read", "system.notifications.write",
    },
    "TECHNICAL": {
        "master.chemicals.read", "master.chemicals.write", "master.products.read", "master.products.write",
        "warehouse.inventory.issue.read", "warehouse.inventory.issue.write",
        "warehouse.inventory.transfer.read", "warehouse.inventory.transfer.write",
        "warehouse.inventory.stocktake.read", "warehouse.inventory.stocktake.write",
        "system.notifications.read", "system.notifications.write",
    },
    "WAREHOUSE": {"master.products.read", "master.suppliers.read", "warehouse.deliveries.read", "warehouse.deliveries.write", "warehouse.inventory.read", "warehouse.inventory.write", "warehouse.inventory.issue.read", "warehouse.inventory.issue.write", "warehouse.inventory.transfer.read", "warehouse.inventory.transfer.write", "warehouse.inventory.stocktake.read", "warehouse.inventory.stocktake.write", "warehouse.inventory.freeze.write", "warehouse.inventory.return.read", "warehouse.inventory.return.write", "operations.exceptions.read", "operations.exceptions.write", "system.notifications.read", "system.notifications.write", "system.files.read", "system.files.download", "system.files.write", "system.files.attach", "warehouse.inventory.cost.write"},
    "QUALITY": {"master.chemicals.read", "master.products.read", "master.suppliers.read", "quality.acceptances.read", "quality.acceptances.write", "warehouse.inventory.issue.read", "warehouse.inventory.transfer.read", "warehouse.inventory.stocktake.read", "operations.exceptions.read", "operations.exceptions.write", "system.notifications.read", "system.notifications.write"},
    "QUALITY_MANAGER": {"master.products.read", "quality.acceptances.read", "quality.acceptances.write", "quality.acceptances.review", "system.files.read", "system.files.download", "system.notifications.read"},
    "FINANCE_VIEWER": {"master.chemicals.read", "master.products.read", "master.suppliers.read", "procurement.requests.read", "procurement.rfqs.read", "procurement.orders.read", "warehouse.deliveries.read", "quality.acceptances.read", "warehouse.inventory.read", "warehouse.inventory.issue.read", "warehouse.inventory.transfer.read", "warehouse.inventory.stocktake.read", "operations.exceptions.read", "system.notifications.read", "system.notifications.write", "dashboard.read"},
    "FINANCE_CLERK": {"finance.reconciliations.read", "finance.reconciliations.write", "finance.invoices.read", "finance.invoices.write", "finance.payments.read", "finance.payments.write", "finance.settlements.read", "finance.settlements.write", "master.suppliers.read", "procurement.orders.read", "warehouse.deliveries.read", "quality.acceptances.read", "system.files.read", "system.files.download", "system.files.write", "system.files.attach"},
    "FINANCE_MANAGER": {"finance.reconciliations.read", "finance.reconciliations.write", "finance.invoices.read", "finance.invoices.write", "finance.invoices.verify", "finance.payments.read", "finance.payments.write", "finance.payments.approve", "finance.settlements.read", "finance.settlements.write", "finance.settlements.approve", "master.suppliers.read", "procurement.orders.read", "warehouse.deliveries.read", "quality.acceptances.read", "system.files.read", "system.files.download", "system.files.write", "system.files.attach", "dashboard.read"},
    "MANAGEMENT_VIEWER": {"master.chemicals.read", "master.products.read", "master.suppliers.read", "procurement.requests.read", "procurement.rfqs.read", "procurement.orders.read", "warehouse.deliveries.read", "quality.acceptances.read", "warehouse.inventory.read", "warehouse.inventory.issue.read", "warehouse.inventory.transfer.read", "warehouse.inventory.stocktake.read", "operations.exceptions.read", "system.notifications.read", "system.notifications.write", "dashboard.read"},
    "SUPPLIER_PORTAL": {"supplier.portal.read", "supplier.portal.confirm"},
}

# 运营看板是内部账号的通用入口；外部供应商门户不授予内部运营汇总权限。
for _role_code, _scope in ROLE_SCOPES.items():
    if _role_code != "SUPPLIER_PORTAL":
        _scope.add("dashboard.read")

REVOKED_ROLE_PERMISSIONS = {
    "BUYER": {"procurement.orders.approve", "master.products.write"},
}

ROLE_NAMES = {
    "SYS_ADMIN": "系统管理员",
    "PROCUREMENT_MANAGER": "采购经理",
    "BUYER": "采购员",
    "TECHNICAL": "技术研发人员",
    "WAREHOUSE": "仓库收货人员",
    "QUALITY": "质量人员",
    "QUALITY_MANAGER": "质量负责人",
    "FINANCE_VIEWER": "财务查看者",
    "MANAGEMENT_VIEWER": "管理层查看者",
    "FINANCE_CLERK": "财务专员",
    "FINANCE_MANAGER": "财务经理",
    "SUPPLIER_PORTAL": "供应商门户用户",
}

USERS = (
    ("system_admin", "系统管理员", "MANAGEMENT", "SYS_ADMIN"),
    ("procurement_manager", "采购经理", "PROCUREMENT", "PROCUREMENT_MANAGER"),
    ("buyer", "采购员", "PROCUREMENT", "BUYER"),
    ("technical_engineer", "技术研发人员", "R_AND_D", "TECHNICAL"),
    ("warehouse_receiver", "仓库收货人员", "WAREHOUSE", "WAREHOUSE"),
    ("quality_inspector", "质量检验人员", "QUALITY", "QUALITY"),
    ("quality_manager", "质量负责人", "QUALITY", "QUALITY_MANAGER"),
    ("finance_viewer", "财务查看者", "FINANCE", "FINANCE_VIEWER"),
    ("management_viewer", "管理层查看者", "MANAGEMENT", "MANAGEMENT_VIEWER"),
    ("finance_clerk", "财务专员", "FINANCE", "FINANCE_CLERK"),
    ("finance_manager", "财务经理", "FINANCE", "FINANCE_MANAGER"),
    ("supplier_portal_demo", "供应商门户账号", "MANAGEMENT", "SUPPLIER_PORTAL"),
)


def ensure_permission(db, code: str, name: str, permission_type: str, resource: str, action: str) -> Permission:
    """获取或创建一条权限。"""

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
    return permission


def ensure_role(db, role_code: str) -> Role:
    """获取或创建一条角色。"""

    role = db.scalar(select(Role).where(Role.role_code == role_code))
    if role is None:
        role = Role(role_code=role_code, role_name=ROLE_NAMES[role_code], status="ACTIVE")
        db.add(role)
        db.flush()
    return role


def main() -> None:
    """创建演示账号；已存在账号不会重置密码。"""

    settings = get_settings()
    if not settings.demo_default_password or settings.demo_default_password.startswith("CHANGE_ME"):
        raise SystemExit("请先在 .env 中设置 DEMO_DEFAULT_PASSWORD")

    db = SessionLocal()
    try:
        departments = {}
        for code, name in DEPARTMENTS:
            department = db.scalar(select(Department).where(Department.department_code == code))
            if department is None:
                department = Department(department_code=code, department_name=name, status="ACTIVE")
                db.add(department)
                db.flush()
            departments[code] = department

        permissions = {
            code: ensure_permission(db, code, name, permission_type, resource, action)
            for code, name, permission_type, resource, action in PERMISSIONS
        }
        roles = {role_code: ensure_role(db, role_code) for role_code in ROLE_SCOPES}

        for role_code, scope in ROLE_SCOPES.items():
            role = roles[role_code]
            bound_ids = set(db.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)).all())
            for permission_code in scope:
                permission_id = permissions[permission_code].id
                if permission_id not in bound_ids:
                    db.add(RolePermission(role_id=role.id, permission_id=permission_id))
            for permission_code in REVOKED_ROLE_PERMISSIONS.get(role_code, set()):
                permission_id = permissions[permission_code].id
                db.query(RolePermission).filter(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission_id,
                ).delete(synchronize_session=False)

        created_users = []
        for username, display_name, department_code, role_code in USERS:
            user = db.scalar(select(User).where(User.username == username))
            if user is None:
                user = User(
                    username=username,
                    password_hash=hash_password(settings.demo_default_password),
                    display_name=display_name,
                    department_id=departments[department_code].id,
                    status="ACTIVE",
                )
                db.add(user)
                db.flush()
                created_users.append(username)
            binding = db.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == roles[role_code].id))
            if binding is None:
                db.add(UserRole(user_id=user.id, role_id=roles[role_code].id))

        portal_user = db.scalar(select(User).where(User.username == "supplier_portal_demo"))
        supplier = db.scalar(select(Supplier).where(Supplier.status == "ACTIVE").order_by(Supplier.id))
        if portal_user is not None and supplier is not None:
            account = db.scalar(select(SupplierPortalAccount).where(SupplierPortalAccount.user_id == portal_user.id))
            if account is None:
                db.add(SupplierPortalAccount(user_id=portal_user.id, supplier_id=supplier.id, status="ACTIVE"))
            elif account.supplier_id != supplier.id:
                account.supplier_id = supplier.id

        db.commit()
        print("demo_accounts_ready=true")
        print("created_user_count=" + str(len(created_users)))
        print("default_password=" + settings.demo_default_password)
        print("usernames=" + ",".join(username for username, *_ in USERS))
    finally:
        db.close()


if __name__ == "__main__":
    main()
