-- The warehouse role can review expiry alerts under its accessible warehouse scope.
INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE role.role_code = 'WAREHOUSE'
  AND permission.permission_code = 'warehouse.inventory.expiry.read';
