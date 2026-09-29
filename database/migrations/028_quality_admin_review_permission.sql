INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id FROM sys_roles role JOIN sys_permissions permission
WHERE role.role_code = 'SYS_ADMIN' AND permission.permission_code = 'quality.acceptances.review';
