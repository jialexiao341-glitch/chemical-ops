-- 分离付款登记和库存调拨执行，保持内置岗位现有办理能力。
INSERT IGNORE INTO sys_permissions (permission_code, permission_name, permission_type, resource, action) VALUES
('finance.payments.pay', '登记付款结果', 'API', 'finance.payments', 'pay'),
('warehouse.inventory.transfer.execute', '执行库存调拨', 'API', 'warehouse.inventory.transfer', 'execute');

INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM sys_roles r JOIN sys_permissions p
WHERE (r.role_code IN ('SYS_ADMIN', 'FINANCE_CLERK', 'FINANCE_MANAGER') AND p.permission_code = 'finance.payments.pay')
   OR (r.role_code IN ('SYS_ADMIN', 'WAREHOUSE') AND p.permission_code = 'warehouse.inventory.transfer.execute');
