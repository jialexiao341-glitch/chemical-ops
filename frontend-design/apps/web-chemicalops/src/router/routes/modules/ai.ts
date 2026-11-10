import type { RouteRecordRaw } from 'vue-router';

/**
 * AI 中心：对话、待确认提案、任务记录与业务文档。
 *
 * 一级菜单按“用 AI 做事 → 确认写入 → 回看记录 → 查业务文档”的使用链路分组。
 * 具体业务数据仍由后端按业务权限校验；ai.workspace.read 控制入口，
 * 不替代各业务 API 鉴权。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:bot',
      order: 7,
      title: 'AI 中心',
    },
    name: 'AiCenter',
    path: '/ai',
    redirect: '/ai/workspace',
    children: [
      {
        name: 'AiWorkspace',
        path: 'workspace',
        component: () => import('#/views/ai/workspace/index.vue'),
        meta: {
          authority: ['ai.workspace.read'],
          icon: 'lucide:messages-square',
          title: 'AI 对话',
        },
      },
      {
        name: 'AiProposals',
        path: 'proposals',
        component: () => import('#/views/ai/proposals/index.vue'),
        meta: {
          authority: ['ai.workspace.read'],
          icon: 'lucide:clipboard-check',
          title: '待确认提案',
        },
      },
      {
        name: 'AiTaskHistory',
        path: 'tasks',
        component: () => import('#/views/ai/tasks/index.vue'),
        meta: {
          authority: ['ai.workspace.read'],
          icon: 'lucide:history',
          title: '任务记录',
        },
      },
      {
        name: 'AiDocuments',
        path: 'documents',
        component: () => import('#/views/ai/documents/index.vue'),
        meta: {
          authority: ['ai.workspace.read'],
          icon: 'lucide:files',
          title: '业务文档',
        },
      },
    ],
  },
  {
    meta: { authority: ['ai.workspace.read'], hideInMenu: true, title: '采购只读任务' },
    name: 'AiAgentTask',
    path: '/ai/agent',
    redirect: '/ai/workspace',
  },
];

export default routes;
