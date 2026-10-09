-- Reconcile additional stale grants found by the post-043 read-only matrix check.
DELETE binding FROM sys_role_permissions binding
JOIN sys_roles role ON role.id = binding.role_id
JOIN sys_permissions permission ON permission.id = binding.permission_id
WHERE
    (role.role_code = 'PROCUREMENT_MANAGER' AND permission.permission_code IN (
        'master.chemicals.write', 'master.products.write',
        'warehouse.deliveries.write', 'quality.acceptances.write'
    ))
    OR (role.role_code = 'BUYER' AND permission.permission_code = 'warehouse.inventory.issue.read');

UPDATE sys_permissions
SET permission_name = '生成报价比较'
WHERE permission_code = 'procurement.rfqs.compare';
