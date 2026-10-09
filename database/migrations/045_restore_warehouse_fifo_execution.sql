-- WAREHOUSE executes FIFO outbounds per the approved role matrix. The response
-- hides cost values unless warehouse.inventory.cost.read is independently granted.
INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE role.role_code = 'WAREHOUSE'
  AND permission.permission_code = 'warehouse.inventory.cost.write';
