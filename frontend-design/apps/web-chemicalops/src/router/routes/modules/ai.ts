import type { RouteRecordRaw } from 'vue-router';

/**
 * AI 工作台。
 *
 * 工作台导航仅对内部账号显示。具体业务数据仍由后端按业务权限校验；
 * 此处的 dashboard.read 仅作为演示账号的内部账号标记，不替代 API 鉴权。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: { authority: ['dashboard.read'], hideInMenu: true, title: '采购只读任务' },
    name: 'AiAgentTask',
    path: '/ai/agent',
    redirect: '/ai/workspace',
  },
  {
    meta: {
      authority: ['dashboard.read'],
      fullPathKey: false,
      hideInMenu: false,
      icon: 'lucide:bot',
      order: 7,
      title: 'AI 工作台',
    },
    name: 'AiWorkspace',
    path: '/ai/workspace',
    component: () => import('#/views/ai/workspace/index.vue'),
  },
];

export default routes;
