import type { RouteRecordRaw } from 'vue-router';

/**
 * AI 工作台。
 *
 * 工作台导航仅对内部账号显示。具体业务数据仍由后端按业务权限校验；
 * ai.workspace.read 控制工作台入口，不替代各业务 API 鉴权。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: { authority: ['ai.workspace.read'], hideInMenu: true, title: '采购只读任务' },
    name: 'AiAgentTask',
    path: '/ai/agent',
    redirect: '/ai/workspace',
  },
  {
    meta: {
      authority: ['ai.workspace.read'],
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
  {
    meta: { authority: ['ai.workspace.read'], hideInMenu: true, title: 'AI 任务记录' },
    name: 'AiTaskHistory',
    path: '/ai/tasks',
    component: () => import('#/views/ai/tasks/index.vue'),
  },
];

export default routes;
