INSERT IGNORE INTO sys_permissions (permission_code, permission_name, permission_type, resource, action) VALUES
('warehouse.inventory.stocktake.execute', '执行库存盘点', 'API', 'warehouse.inventory.stocktake', 'execute');

INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM sys_roles r JOIN sys_permissions p
WHERE r.role_code IN ('SYS_ADMIN', 'WAREHOUSE') AND p.permission_code = 'warehouse.inventory.stocktake.execute';
