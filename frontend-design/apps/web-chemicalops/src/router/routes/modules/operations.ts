import type { RouteRecordRaw } from 'vue-router';

/**
 * 运营中心：运营异常的登记、指派、任务与处理记录，以及 AI 生成的运营建议。
 *
 * 首页「开放异常」KPI 跳转到这里。运营建议按业务归属放在这里，
 * 与 AI 中心的对话、提案确认分开，避免把待办事务都堆进 AI 入口。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      authority: ['operations.exceptions.read'],
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
      {
        name: 'OperationMyTasks',
        path: 'my-tasks',
        component: () => import('#/views/operations/my-tasks/index.vue'),
        meta: {
          authority: ['operations.exceptions.read'],
          icon: 'lucide:list-checks',
          title: '我的任务',
        },
      },
      {
        name: 'OperationSuggestions',
        path: 'suggestions',
        component: () => import('#/views/operations/suggestions/index.vue'),
        meta: {
          authority: ['operations.exceptions.read'],
          icon: 'lucide:lightbulb',
          title: '运营建议',
        },
      },
    ],
  },
];

export default routes;
