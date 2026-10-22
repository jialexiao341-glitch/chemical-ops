import { describe, expect, it } from 'vitest';
import type { AgentApi } from '../../../api/ai/agent';
import { retryQuestion, taskActions, taskActionFeedback } from './task-actions';

const task = (
  status: AgentApi.Task['status'],
  messages: string[],
): AgentApi.Task => ({
  id: 'task-1',
  revision: 2,
  status,
  reply: '',
  error_code: null,
  messages,
  trace: [],
});

describe('Agent 任务中心操作策略', () => {
  it.each([
    ['WAITING_INPUT', ['view', 'export', 'continue']],
    ['RUNNING', ['view', 'export', 'cancel']],
    ['FAILED', ['view', 'export', 'retry']],
    ['SUCCEEDED', ['view', 'export']],
    ['CANCELLED', ['view', 'export']],
  ] as const)('%s 只提供当前状态允许的操作', (status, expected) => {
    expect(taskActions(status)).toEqual(expected);
  });

  it('重试多轮失败任务时只取首次查询', () => {
    expect(
      retryQuestion(task('FAILED', ['  查询乙醇库存  ', '选择分析纯', '继续'])),
    ).toBe('查询乙醇库存');
  });

  it('原始查询为空时不允许重试', () => {
    expect(retryQuestion(task('FAILED', ['  ', '后续补充']))).toBeUndefined();
    expect(retryQuestion(task('FAILED', []))).toBeUndefined();
  });

  it('取消响应没有进入 CANCELLED 时不显示成功取消', () => {
    expect(taskActionFeedback('cancel', 'SUCCEEDED')).toBe(
      '任务状态已变化，请刷新查看最新结果',
    );
    expect(taskActionFeedback('cancel', 'CANCELLED')).toBe('任务已取消');
  });
});
