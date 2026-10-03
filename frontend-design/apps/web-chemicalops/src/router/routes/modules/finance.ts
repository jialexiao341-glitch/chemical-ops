import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      authority: [
        'finance.reconciliations.read',
        'finance.invoices.read',
        'finance.payments.read',
        'finance.settlements.read',
      ],
      icon: 'lucide:landmark',
      order: 6,
      title: '财务管理',
    },
    name: 'Finance',
    path: '/finance',
    children: [
      {
        name: 'ReconciliationList',
        path: 'reconciliations',
        component: () => import('#/views/finance/reconciliations/index.vue'),
        meta: {
          authority: ['finance.reconciliations.read'],
          icon: 'lucide:scale',
          title: '财务对账',
        },
      },
      {
        name: 'InvoiceList',
        path: 'invoices',
        component: () => import('#/views/finance/invoices/index.vue'),
        meta: {
          authority: ['finance.invoices.read'],
          icon: 'lucide:file-text',
          title: '供应商发票',
        },
      },
      {
        name: 'PaymentList',
        path: 'payments',
        component: () => import('#/views/finance/payments/index.vue'),
        meta: {
          authority: ['finance.payments.read'],
          icon: 'lucide:wallet',
          title: '付款管理',
        },
      },
      {
        name: 'SettlementList',
        path: 'settlements',
        component: () => import('#/views/finance/settlements/index.vue'),
        meta: {
          authority: ['finance.settlements.read'],
          icon: 'lucide:hand-coins',
          title: '采购结算',
        },
      },
    ],
  },
];

export default routes;
