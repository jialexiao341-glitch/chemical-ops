import type { RouteRecordRaw } from 'vue-router';

/**
 * 仓储模块：到货收货 → 库存入库 → 库存台账与预警。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:warehouse',
      order: 4,
      title: '仓储管理',
    },
    name: 'Warehouse',
    path: '/warehouse',
    children: [
      {
        name: 'InventoryReturns',
        path: 'returns',
        component: () => import('#/views/warehouse/returns/index.vue'),
        meta: { authority: ['warehouse.inventory.return.read'], icon: 'lucide:package-minus', title: '供应商退货' },
      },
      {
        name: 'DeliveryList',
        path: 'deliveries',
        component: () => import('#/views/warehouse/deliveries/index.vue'),
        meta: {
          authority: ['warehouse.deliveries.read'],
          icon: 'lucide:truck',
          title: '到货与收货',
        },
      },
      {
        name: 'InventoryList',
        path: 'inventory',
        component: () => import('#/views/warehouse/inventory/index.vue'),
        meta: {
          authority: ['warehouse.inventory.read'],
          icon: 'lucide:boxes',
          title: '库存台账',
        },
      },
      {
        name: 'InventoryTransaction',
        path: 'transactions',
        component: () => import('#/views/warehouse/transactions/index.vue'),
        meta: {
          authority: ['warehouse.inventory.read'],
          icon: 'lucide:arrow-left-right',
          title: '库存流水',
        },
      },
      {
        name: 'ExpiryAlert',
        path: 'expiry-alerts',
        component: () => import('#/views/warehouse/expiry-alerts/index.vue'),
        meta: {
          authority: ['warehouse.inventory.read'],
          icon: 'lucide:calendar-clock',
          title: '有效期预警',
        },
      },
      {
        name: 'IssueRequestList',
        path: 'issue-requests',
        component: () => import('#/views/warehouse/issue-requests/index.vue'),
        meta: {
          authority: ['warehouse.inventory.issue.read'],
          icon: 'lucide:package-open',
          title: '库存领用',
        },
      },
      {
        name: 'TransferRequestList',
        path: 'transfers',
        component: () => import('#/views/warehouse/transfers/index.vue'),
        meta: {
          authority: ['warehouse.inventory.transfer.read'],
          icon: 'lucide:replace',
          title: '库存调拨',
        },
      },
      {
        name: 'StocktakeList',
        path: 'stocktakes',
        component: () => import('#/views/warehouse/stocktakes/index.vue'),
        meta: {
          authority: ['warehouse.inventory.stocktake.read'],
          icon: 'lucide:list-checks',
          title: '库存盘点',
        },
      },
    ],
  },
];

export default routes;
