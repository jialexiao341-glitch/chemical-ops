import type { AgentApi } from '../../../api/ai/agent';
import { describe, expect, it } from 'vitest';
import { acceptTask, inventorySource, waitingCandidates } from './task-view';

const waiting: AgentApi.Task = { id: 'a', revision: 2, status: 'WAITING_INPUT', reply: '', error_code: null, messages: [], trace: [
  { step: 1, action: 'call_tool', status: 'SUCCEEDED', result: { tool: 'catalog.search_products', total_rows: 2, truncated: false, rows: [], sources: [] } },
] };

describe('采购任务状态与来源', () => {
  it('强制等待只展示最新候选，普通追问不能选择历史候选', () => {
    expect(waitingCandidates(waiting)?.tool).toBe('catalog.search_products');
    expect(waitingCandidates({ ...waiting, trace: [...waiting.trace, { step: 2, action: 'ask_user', status: 'WAITING_INPUT' }] })).toBeUndefined();
    expect(waitingCandidates({ ...waiting, status: 'CANCELLED' })).toBeUndefined();
  });
  it('取消/刷新后较旧续跑响应不能覆盖新状态，其他任务响应也不能覆盖', () => {
    const cancelled = { ...waiting, status: 'CANCELLED' as const, revision: 4 };
    expect(acceptTask(cancelled, { ...waiting, status: 'SUCCEEDED', revision: 3 })).toBe(false);
    expect(acceptTask(cancelled, { ...waiting, id: 'other', revision: 5 })).toBe(false);
    expect(acceptTask(waiting, { ...waiting, revision: 3 })).toBe(true);
  });
  it('库存来源入口同时带上产品及仓库，不混成全企业库存', () => {
    const link = inventorySource(11, 22);
    expect(link.path).toBe('/warehouse/inventory');
    expect(JSON.parse(link.query.ai_filters)).toEqual({ dataset: 'inventory', filters: { product_id: '11', warehouse_id: '22' } });
  });
});
