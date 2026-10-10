-- Managers assign acceptance records, inspectors only process assigned records.
INSERT IGNORE INTO sys_permissions (permission_code, permission_name, permission_type, resource, action)
VALUES ('quality.acceptances.assign', '创建并指派质量验收', 'API', 'quality.acceptances', 'assign');

INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE role.role_code IN ('SYS_ADMIN', 'QUALITY_MANAGER')
  AND permission.permission_code = 'quality.acceptances.assign';
