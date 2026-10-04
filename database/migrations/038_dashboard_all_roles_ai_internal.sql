INSERT IGNORE INTO sys_permissions (permission_code, permission_name, permission_type, resource, action)
VALUES
    ('dashboard.read', '查看运营 Dashboard', 'API', 'dashboard', 'read'),
    ('ai.workspace.read', '访问 AI 工作台', 'API', 'ai.workspace', 'read');

INSERT IGNORE INTO sys_roles (role_code, role_name, status)
VALUES ('SUPPLIER_PORTAL', '供应商门户用户', 'ACTIVE');

INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE role.role_code IN (
    'SYS_ADMIN', 'PROCUREMENT_MANAGER', 'BUYER', 'TECHNICAL', 'WAREHOUSE',
    'QUALITY', 'QUALITY_MANAGER', 'FINANCE_VIEWER', 'FINANCE_CLERK',
    'FINANCE_MANAGER', 'MANAGEMENT_VIEWER', 'SUPPLIER_PORTAL'
)
AND permission.permission_code = 'dashboard.read';

INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE role.role_code IN (
    'SYS_ADMIN', 'PROCUREMENT_MANAGER', 'BUYER', 'TECHNICAL', 'WAREHOUSE',
    'QUALITY', 'QUALITY_MANAGER', 'FINANCE_VIEWER', 'FINANCE_CLERK',
    'FINANCE_MANAGER', 'MANAGEMENT_VIEWER'
)
AND permission.permission_code = 'ai.workspace.read';
