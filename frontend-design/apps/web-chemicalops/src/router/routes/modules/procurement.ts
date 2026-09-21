import type { RouteRecordRaw } from 'vue-router';

/**
 * 采购链路：采购申请 → 询价报价 → 采购订单。
 * 菜单顺序与业务流程顺序一致。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:shopping-cart',
      order: 3,
      title: '采购管理',
    },
    name: 'Procurement',
    path: '/procurement',
    children: [
      {
        name: 'PurchaseRequestList',
        path: 'requests',
        component: () =>
          import('#/views/procurement/purchase-requests/index.vue'),
        meta: {
          authority: ['procurement.requests.read'],
          icon: 'lucide:file-text',
          title: '采购申请',
        },
      },
      {
        name: 'RfqList',
        path: 'rfqs',
        component: () => import('#/views/procurement/rfqs/index.vue'),
        meta: {
          authority: ['procurement.rfqs.read'],
          icon: 'lucide:mail-question',
          title: '询价与报价',
        },
      },
      {
        name: 'PurchaseOrderList',
        path: 'orders',
        component: () =>
          import('#/views/procurement/purchase-orders/index.vue'),
        meta: {
          authority: ['procurement.orders.read'],
          icon: 'lucide:clipboard-list',
          title: '采购订单',
        },
      },
      {
        name: 'PurchaseOrderDetail',
        path: 'orders/:id',
        component: () =>
          import('#/views/procurement/purchase-orders/detail.vue'),
        meta: {
          authority: ['procurement.orders.read'],
          hideInMenu: true,
          title: '采购订单详情',
        },
      },
    ],
  },
];

export default routes;
