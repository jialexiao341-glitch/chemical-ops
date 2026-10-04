INSERT IGNORE INTO sys_permissions (permission_code, permission_name, permission_type, resource, action)
VALUES
    ('supplier.portal.rfq.read', '查询受邀供应商询价', 'API', 'supplier.portal.rfq', 'read'),
    ('supplier.portal.rfq.quote', '提交受邀供应商报价', 'API', 'supplier.portal.rfq', 'quote');

INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE role.role_code = 'SUPPLIER_PORTAL'
  AND permission.permission_code IN ('supplier.portal.rfq.read', 'supplier.portal.rfq.quote');
