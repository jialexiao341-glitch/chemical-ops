-- Use Chinese display names for built-in export permissions already present in deployed databases.
UPDATE sys_permissions
SET permission_name = CASE permission_code
    WHEN 'master.chemicals.export' THEN '导出化学品数据'
    WHEN 'master.products.export' THEN '导出产品数据'
    WHEN 'master.suppliers.export' THEN '导出供应商数据'
    WHEN 'system.users.export' THEN '导出用户数据'
    WHEN 'system.departments.export' THEN '导出部门数据'
    WHEN 'system.roles.export' THEN '导出角色数据'
    WHEN 'system.permissions.export' THEN '导出权限数据'
    WHEN 'procurement.requests.export' THEN '导出采购申请数据'
    WHEN 'procurement.rfqs.export' THEN '导出采购询价数据'
    WHEN 'procurement.orders.export' THEN '导出采购订单数据'
    WHEN 'warehouse.deliveries.export' THEN '导出到货单数据'
    WHEN 'warehouse.inventory.balances.export' THEN '导出库存余额数据'
    WHEN 'warehouse.inventory.transactions.export' THEN '导出库存流水数据'
    WHEN 'warehouse.inventory.issues.export' THEN '导出库存领用记录'
    WHEN 'warehouse.inventory.transfers.export' THEN '导出库存调拨记录'
    WHEN 'warehouse.inventory.stocktakes.export' THEN '导出库存盘点记录'
    WHEN 'quality.acceptances.export' THEN '导出质量验收记录'
    WHEN 'finance.reconciliations.export' THEN '导出财务对账单'
    WHEN 'finance.invoices.export' THEN '导出供应商发票'
    WHEN 'finance.payments.export' THEN '导出付款记录'
    WHEN 'finance.settlements.export' THEN '导出采购结算单'
    WHEN 'operations.exceptions.export' THEN '导出运营异常记录'
    WHEN 'supplier.portal.export' THEN '导出供应商门户数据'
    WHEN 'supplier.portal.rfq.export' THEN '导出供应商询价数据'
    WHEN 'supplier.portal.delivery.export' THEN '导出供应商交期更新数据'
    WHEN 'supplier.portal.shipment.export' THEN '导出供应商发货通知'
    WHEN 'supplier.portal.quality.export' THEN '导出供应商质量资料'
    WHEN 'supplier.portal.reconciliation.export' THEN '导出供应商对账记录'
    ELSE permission_name
END
WHERE permission_code IN (
    'master.chemicals.export', 'master.products.export', 'master.suppliers.export',
    'system.users.export', 'system.departments.export', 'system.roles.export', 'system.permissions.export',
    'procurement.requests.export', 'procurement.rfqs.export', 'procurement.orders.export',
    'warehouse.deliveries.export', 'warehouse.inventory.balances.export',
    'warehouse.inventory.transactions.export', 'warehouse.inventory.issues.export',
    'warehouse.inventory.transfers.export', 'warehouse.inventory.stocktakes.export',
    'quality.acceptances.export', 'finance.reconciliations.export', 'finance.invoices.export',
    'finance.payments.export', 'finance.settlements.export', 'operations.exceptions.export',
    'supplier.portal.export', 'supplier.portal.rfq.export', 'supplier.portal.delivery.export',
    'supplier.portal.shipment.export', 'supplier.portal.quality.export',
    'supplier.portal.reconciliation.export'
);

UPDATE sys_permissions
SET permission_name = '查看运营仪表盘'
WHERE permission_code = 'dashboard.read';

UPDATE sys_permissions
SET permission_name = '访问智能工作台'
WHERE permission_code = 'ai.workspace.read';

UPDATE sys_permissions
SET permission_name = '执行先进先出成本出库'
WHERE permission_code = 'warehouse.inventory.cost.write';
