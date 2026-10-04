import type { RouteRecordRaw } from 'vue-router';

/** 供应商仅访问受邀询价和当前绑定供应商的订单协作页面。 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      authority: ['supplier.portal.read'],
      icon: 'lucide:store',
      order: 2,
      title: '供应商门户',
    },
    name: 'SupplierPortal',
    path: '/supplier-portal',
    children: [
      {
        name: 'SupplierRfqList',
        path: 'rfqs',
        component: () => import('#/views/supplier-portal/rfqs/index.vue'),
        meta: {
          authority: ['supplier.portal.rfq.read'],
          icon: 'lucide:clipboard-list',
          title: '我的询价',
        },
      },
      {
        name: 'SupplierRfqDetail',
        path: 'rfqs/:id',
        component: () => import('#/views/supplier-portal/rfqs/detail.vue'),
        meta: {
          authority: ['supplier.portal.rfq.read'],
          hideInMenu: true,
          title: '询价详情与报价',
        },
      },
      {
        name: 'SupplierOrderList',
        path: 'orders',
        component: () => import('#/views/supplier-portal/orders/index.vue'),
        meta: {
          authority: ['supplier.portal.read'],
          icon: 'lucide:clipboard-list',
          title: '我的订单',
        },
      },
      {
        name: 'SupplierOrderDetail',
        path: 'orders/:id',
        component: () => import('#/views/supplier-portal/orders/detail.vue'),
        meta: {
          authority: ['supplier.portal.read'],
          hideInMenu: true,
          title: '订单详情',
        },
      },
      {
        name: 'SupplierDeliveryUpdates',
        path: 'delivery-updates',
        component: () => import('#/views/supplier-portal/delivery-updates/index.vue'),
        meta: {
          authority: ['supplier.portal.delivery.read'],
          icon: 'lucide:calendar-clock',
          title: '交期更新',
        },
      },
      {
        name: 'SupplierShipments',
        path: 'shipments',
        component: () => import('#/views/supplier-portal/shipments/index.vue'),
        meta: {
          authority: ['supplier.portal.shipment.read'],
          icon: 'lucide:truck',
          title: '发货通知',
        },
      },
      {
        name: 'SupplierQualityDocuments',
        path: 'quality-documents',
        component: () => import('#/views/supplier-portal/quality-documents/index.vue'),
        meta: {
          authority: ['supplier.portal.quality.read'],
          icon: 'lucide:file-check-2',
          title: '质量资料',
        },
      },
      {
        name: 'SupplierReconciliations',
        path: 'reconciliations',
        component: () => import('#/views/supplier-portal/reconciliations/index.vue'),
        meta: {
          authority: ['supplier.portal.reconciliation.read'],
          icon: 'lucide:handshake',
          title: '对账协同',
        },
      },
    ],
  },
];

export default routes;
