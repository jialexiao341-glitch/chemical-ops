import type { RouteRecordRaw } from 'vue-router';

/**
 * 运营中心：运营异常的登记、指派、任务与处理记录。
 *
 * 首页「开放异常」KPI 跳转到这里。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:siren',
      order: 6,
      title: '运营中心',
    },
    name: 'Operations',
    path: '/operations',
    children: [
      {
        name: 'OperationExceptions',
        path: 'exceptions',
        component: () => import('#/views/operations/exceptions/index.vue'),
        meta: {
          authority: ['operations.exceptions.read'],
          icon: 'lucide:triangle-alert',
          title: '运营异常',
        },
      },
    ],
  },
];

export default routes;
