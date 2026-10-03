import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      authority: ['quality.acceptances.read'],
      icon: 'lucide:shield-check',
      order: 5,
      title: '质量管理',
    },
    name: 'Quality',
    path: '/quality',
    children: [
      {
        name: 'AcceptanceList',
        path: 'acceptances',
        component: () => import('#/views/quality/acceptances/index.vue'),
        meta: {
          authority: ['quality.acceptances.read'],
          icon: 'lucide:clipboard-check',
          title: '质量验收',
        },
      },
    ],
  },
];

export default routes;
