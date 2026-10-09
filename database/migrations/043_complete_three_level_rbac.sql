-- Align built-in role grants with the approved three-level access matrix.
-- This migration is idempotent and never changes user credentials or UserRole links.
INSERT IGNORE INTO sys_permissions (permission_code, permission_name, permission_type, resource, action)
VALUES
    ('procurement.rfqs.award', '确认中选报价', 'API', 'procurement.rfqs', 'award'),
    ('warehouse.inventory.expiry.read', '查看库存有效期预警', 'API', 'warehouse.inventory.expiry', 'read'),
    ('warehouse.inventory.cost.read', '查看库存成本', 'API', 'warehouse.inventory.cost', 'read'),
    ('master.chemicals.delete', '删除化学品', 'API', 'master.chemicals', 'delete'),
    ('master.products.delete', '删除产品', 'API', 'master.products', 'delete'),
    ('master.suppliers.deactivate', '停用供应商', 'API', 'master.suppliers', 'deactivate'),
    ('master.chemicals.import', '导入化学品', 'API', 'master.chemicals', 'import'),
    ('master.products.import', '导入产品', 'API', 'master.products', 'import'),
    ('master.suppliers.import', '导入供应商', 'API', 'master.suppliers', 'import'),
    ('master.chemicals.export', '导出 master.chemicals', 'API', 'master.chemicals', 'export'),
    ('master.products.export', '导出 master.products', 'API', 'master.products', 'export'),
    ('master.suppliers.export', '导出 master.suppliers', 'API', 'master.suppliers', 'export'),
    ('system.users.export', '导出 system.users', 'API', 'system.users', 'export'),
    ('system.departments.export', '导出 system.departments', 'API', 'system.departments', 'export'),
    ('system.roles.export', '导出 system.roles', 'API', 'system.roles', 'export'),
    ('system.permissions.export', '导出 system.permissions', 'API', 'system.permissions', 'export'),
    ('procurement.requests.export', '导出 procurement.requests', 'API', 'procurement.requests', 'export'),
    ('procurement.rfqs.export', '导出 procurement.rfqs', 'API', 'procurement.rfqs', 'export'),
    ('procurement.orders.export', '导出 procurement.orders', 'API', 'procurement.orders', 'export'),
    ('warehouse.deliveries.export', '导出 warehouse.deliveries', 'API', 'warehouse.deliveries', 'export'),
    ('warehouse.inventory.balances.export', '导出 warehouse.inventory.balances', 'API', 'warehouse.inventory.balances', 'export'),
    ('warehouse.inventory.transactions.export', '导出 warehouse.inventory.transactions', 'API', 'warehouse.inventory.transactions', 'export'),
    ('warehouse.inventory.issues.export', '导出 warehouse.inventory.issues', 'API', 'warehouse.inventory.issues', 'export'),
    ('warehouse.inventory.transfers.export', '导出 warehouse.inventory.transfers', 'API', 'warehouse.inventory.transfers', 'export'),
    ('warehouse.inventory.stocktakes.export', '导出 warehouse.inventory.stocktakes', 'API', 'warehouse.inventory.stocktakes', 'export'),
    ('quality.acceptances.export', '导出 quality.acceptances', 'API', 'quality.acceptances', 'export'),
    ('finance.reconciliations.export', '导出 finance.reconciliations', 'API', 'finance.reconciliations', 'export'),
    ('finance.invoices.export', '导出 finance.invoices', 'API', 'finance.invoices', 'export'),
    ('finance.payments.export', '导出 finance.payments', 'API', 'finance.payments', 'export'),
    ('finance.settlements.export', '导出 finance.settlements', 'API', 'finance.settlements', 'export'),
    ('operations.exceptions.export', '导出 operations.exceptions', 'API', 'operations.exceptions', 'export'),
    ('supplier.portal.export', '导出 supplier.portal', 'API', 'supplier.portal', 'export'),
    ('supplier.portal.rfq.export', '导出 supplier.portal.rfq', 'API', 'supplier.portal.rfq', 'export'),
    ('supplier.portal.delivery.export', '导出 supplier.portal.delivery', 'API', 'supplier.portal.delivery', 'export'),
    ('supplier.portal.shipment.export', '导出 supplier.portal.shipment', 'API', 'supplier.portal.shipment', 'export'),
    ('supplier.portal.quality.export', '导出 supplier.portal.quality', 'API', 'supplier.portal.quality', 'export'),
    ('supplier.portal.reconciliation.export', '导出 supplier.portal.reconciliation', 'API', 'supplier.portal.reconciliation', 'export');

-- Grant new, explicitly approved role permissions before removing stale grants.
INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE (role.role_code, permission.permission_code) IN (
    ('PROCUREMENT_MANAGER', 'procurement.rfqs.award'),
    ('PROCUREMENT_MANAGER', 'warehouse.inventory.expiry.read'),
    ('PROCUREMENT_MANAGER', 'master.suppliers.import'),
    ('TECHNICAL', 'master.chemicals.import'),
    ('TECHNICAL', 'master.products.import'),
    ('BUYER', 'procurement.rfqs.compare'),
    ('BUYER', 'warehouse.inventory.expiry.read'),
    ('BUYER', 'warehouse.inventory.return.read'),
    ('TECHNICAL', 'master.chemicals.import'),
    ('TECHNICAL', 'master.products.import'),
    ('WAREHOUSE', 'master.chemicals.read'),
    ('WAREHOUSE', 'procurement.orders.read'),
    ('WAREHOUSE', 'quality.acceptances.read'),
    ('WAREHOUSE', 'procurement.replenishment.read'),
    ('QUALITY', 'procurement.orders.read'),
    ('QUALITY', 'warehouse.deliveries.read'),
    ('QUALITY', 'warehouse.inventory.read'),
    ('QUALITY', 'warehouse.inventory.expiry.read'),
    ('QUALITY', 'warehouse.inventory.return.read'),
    ('QUALITY_MANAGER', 'master.chemicals.read'),
    ('QUALITY_MANAGER', 'master.suppliers.read'),
    ('QUALITY_MANAGER', 'procurement.orders.read'),
    ('QUALITY_MANAGER', 'warehouse.deliveries.read'),
    ('QUALITY_MANAGER', 'warehouse.inventory.read'),
    ('QUALITY_MANAGER', 'warehouse.inventory.expiry.read'),
    ('QUALITY_MANAGER', 'warehouse.inventory.return.read'),
    ('QUALITY_MANAGER', 'operations.exceptions.read'),
    ('QUALITY_MANAGER', 'operations.exceptions.write'),
    ('QUALITY_MANAGER', 'procurement.replenishment.read'),
    ('FINANCE_VIEWER', 'finance.reconciliations.read'),
    ('FINANCE_VIEWER', 'finance.invoices.read'),
    ('FINANCE_VIEWER', 'finance.payments.read'),
    ('FINANCE_VIEWER', 'finance.settlements.read'),
    ('FINANCE_VIEWER', 'procurement.replenishment.read'),
    ('FINANCE_CLERK', 'procurement.replenishment.read'),
    ('FINANCE_MANAGER', 'warehouse.inventory.read'),
    ('FINANCE_MANAGER', 'warehouse.inventory.issue.read'),
    ('FINANCE_MANAGER', 'warehouse.inventory.transfer.read'),
    ('FINANCE_MANAGER', 'warehouse.inventory.stocktake.read'),
    ('FINANCE_MANAGER', 'operations.exceptions.read'),
    ('FINANCE_MANAGER', 'procurement.replenishment.read'),
    ('MANAGEMENT_VIEWER', 'finance.reconciliations.read'),
    ('MANAGEMENT_VIEWER', 'finance.invoices.read'),
    ('MANAGEMENT_VIEWER', 'finance.payments.read'),
    ('MANAGEMENT_VIEWER', 'finance.settlements.read'),
    ('MANAGEMENT_VIEWER', 'procurement.replenishment.read')
    ,('MANAGEMENT_VIEWER', 'warehouse.inventory.expiry.read')
);

-- Split RFQ award, expiry read, and cost detail from broader permissions.
DELETE binding FROM sys_role_permissions binding
JOIN sys_roles role ON role.id = binding.role_id
JOIN sys_permissions permission ON permission.id = binding.permission_id
WHERE
    (role.role_code = 'BUYER' AND permission.permission_code IN (
        'warehouse.inventory.read', 'warehouse.inventory.issue.read',
        'warehouse.inventory.transfer.read', 'warehouse.inventory.stocktake.read'
    ))
    OR (role.role_code = 'PROCUREMENT_MANAGER' AND permission.permission_code IN (
        'master.chemicals.write', 'master.products.write', 'warehouse.deliveries.write',
        'quality.acceptances.write', 'warehouse.inventory.write',
        'warehouse.inventory.issue.read', 'warehouse.inventory.issue.write', 'warehouse.inventory.issue.approve', 'warehouse.inventory.issue.execute',
        'warehouse.inventory.transfer.read', 'warehouse.inventory.transfer.write', 'warehouse.inventory.transfer.approve',
        'warehouse.inventory.stocktake.read', 'warehouse.inventory.stocktake.write', 'warehouse.inventory.stocktake.approve',
        'warehouse.inventory.freeze.write', 'warehouse.inventory.cost.write',
        'warehouse.inventory.return.write'
    ))
    OR (role.role_code = 'WAREHOUSE' AND permission.permission_code = 'warehouse.inventory.cost.write')
    OR (role.role_code = 'QUALITY' AND permission.permission_code IN (
        'warehouse.inventory.issue.read', 'warehouse.inventory.transfer.read', 'warehouse.inventory.stocktake.read'
    ))
    OR (role.role_code = 'FINANCE_VIEWER' AND permission.permission_code IN (
        'procurement.requests.read', 'procurement.rfqs.read'
    ));

-- Cost details and exports are administrator-only in the approved baseline.
INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE role.role_code = 'SYS_ADMIN'
  AND (RIGHT(permission.permission_code, 7) = '.export'
       OR permission.permission_code IN (
           'procurement.rfqs.award', 'warehouse.inventory.expiry.read',
           'warehouse.inventory.cost.read', 'master.chemicals.delete',
           'master.products.delete', 'master.suppliers.deactivate',
           'master.chemicals.import', 'master.products.import', 'master.suppliers.import'
       ));

