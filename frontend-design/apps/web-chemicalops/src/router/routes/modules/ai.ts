import type { RouteRecordRaw } from 'vue-router';

/**
 * AI 工作台。
 *
 * 后端对话接口只校验登录态（get_current_user），不校验业务权限码，
 * 因此路由不设 authority，登录即可访问（与站内通知同模式）。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: { hideInMenu: true, title: '采购只读任务' },
    name: 'AiAgentTask',
    path: '/ai/agent',
    component: () => import('#/views/ai/agent/index.vue'),
  },
  {
    meta: {
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
