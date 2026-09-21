import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:layout-dashboard',
      order: 1,
      title: '运营总览',
    },
    name: 'Dashboard',
    path: '/dashboard',
    children: [
      {
        name: 'Overview',
        path: 'overview',
        component: () => import('#/views/dashboard/overview/index.vue'),
        meta: {
          affixTab: true,
          icon: 'lucide:gauge',
          title: '运营总览',
        },
      },
    ],
  },
];

export default routes;
