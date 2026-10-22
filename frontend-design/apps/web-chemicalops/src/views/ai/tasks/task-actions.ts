import type { AgentApi } from '../../../api/ai/agent';

export type TaskAction = 'view' | 'export' | 'continue' | 'cancel' | 'retry';

const ACTIONS_BY_STATUS: Record<AgentApi.Task['status'], TaskAction[]> = {
  WAITING_INPUT: ['view', 'export', 'continue'],
  RUNNING: ['view', 'export', 'cancel'],
  FAILED: ['view', 'export', 'retry'],
  SUCCEEDED: ['view', 'export'],
  CANCELLED: ['view', 'export'],
};

export function taskActions(status: AgentApi.Task['status']): TaskAction[] {
  return [...ACTIONS_BY_STATUS[status]];
}

export function retryQuestion(task: AgentApi.Task): string | undefined {
  const question = task.messages[0]?.trim();
  return question || undefined;
}

export function taskActionFeedback(
  action: 'continue' | 'cancel',
  status: AgentApi.Task['status'],
): string {
  if (action === 'cancel') {
    return status === 'CANCELLED'
      ? '任务已取消'
      : '任务状态已变化，请刷新查看最新结果';
  }
  return status === 'RUNNING'
    ? '已继续任务，查询正在运行'
    : '任务状态已更新，请刷新查看最新结果';
}
