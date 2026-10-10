-- Align BUYER with the approved replenishment read/write baseline.
-- Approval remains restricted to procurement managers and administrators.
INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE role.role_code = 'BUYER'
  AND permission.permission_code IN (
      'procurement.replenishment.read', 'procurement.replenishment.write'
  );
