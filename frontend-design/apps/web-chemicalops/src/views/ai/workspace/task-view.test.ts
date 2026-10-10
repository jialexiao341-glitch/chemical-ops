import type { AgentApi } from '../../../api/ai/agent';
import { describe, expect, it } from 'vitest';
import { acceptTask, inventorySource, waitingCandidates, agentDisplayNumber, primaryTaskResults, agentSourcePreview, TASK_LABELS } from './task-view';

const waiting: AgentApi.Task = { id: 'a', revision: 2, status: 'WAITING_INPUT', reply: '', error_code: null, messages: [], trace: [
  { step: 1, action: 'call_tool', status: 'SUCCEEDED', result: { tool: 'catalog.search_products', total_rows: 2, truncated: false, rows: [], sources: [] } },
] };

describe('采购任务状态与来源', () => {
  it('五种任务终态和过程态都提供明确的界面文案', () => {
    expect(TASK_LABELS).toEqual({
      RUNNING: '正在查询',
      WAITING_INPUT: '等待补充',
      SUCCEEDED: '查询完成',
      FAILED: '已停止',
      CANCELLED: '已取消',
    });
  });
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

describe('聊天结果展示', () => {
  const inventory: AgentApi.Result = {
    tool: 'inventory.query_available', product_id: 11, product_name: '乙醇', observed_at: '2026-10-03T04:00:00Z', scope: '授权仓库', warnings: [], totals: [], total_rows: 2, truncated: false, sources: [],
    rows: [
      { balance_id: 1, warehouse_id: 22, warehouse_name: '甲仓', batch_no: 'A', expiry_date: null, available_quantity: '10.000000', unit_name: '升', status: 'AVAILABLE' },
      { balance_id: 2, warehouse_id: 23, warehouse_name: '乙仓', batch_no: 'B', expiry_date: null, available_quantity: '20.500000', unit_name: '升', status: 'AVAILABLE' },
    ],
  };
  it('来源翻页匹配对应余额与仓库，跳转保留授权查询过滤', () => {
    const preview = agentSourcePreview(inventory, { resource: 'inventory_balances', record_id: 2 });
    expect(preview.title).toBe('乙醇 · 乙仓');
    expect(preview.description).toContain('批次 B · 账面可用 20.5 升');
    expect(JSON.parse(preview.to!.query!.ai_filters!)).toEqual({ dataset: 'inventory', filters: { product_id: '11', warehouse_id: '23' } });
  });
  it('来源没有对应明细时不会借用其他记录的数量或链接', () => {
    const preview = agentSourcePreview(inventory, { resource: 'inventory_balances', record_id: 99 });
    expect(preview.reference).toBe('库存余额 #99');
    expect(preview.to).toBeUndefined();
    expect(preview.description).not.toContain('10');
  });
  it('保持金额和数量的精度，整数分组且移除末尾零', () => {
    expect(agentDisplayNumber('1954.000000')).toBe('1,954');
    expect(agentDisplayNumber('9007199254740993.123456')).toBe('9,007,199,254,740,993.123456');
    expect(agentDisplayNumber('0.000010')).toBe('0.00001');
    expect(agentDisplayNumber('-1200.500000')).toBe('-1,200.5');
    expect(agentDisplayNumber('0.000000')).toBe('0');
  });
  it('主结果仅使用完成证据，保留空结果且不把定位记录当库存', () => {
    const trace: AgentApi.Step[] = [
      ...waiting.trace,
      { step: 2, action: 'call_tool', status: 'SUCCEEDED', result: { tool: 'supplier_quotes.find_rfq_items', total_rows: 0, truncated: false, rows: [], sources: [] } },
      { step: 3, action: 'finish', status: 'SUCCEEDED', evidence_steps: [2] },
    ];
    expect(primaryTaskResults({ ...waiting, status: 'SUCCEEDED', trace }).map((entry) => entry.step)).toEqual([2]);
    expect(primaryTaskResults(waiting)).toEqual([]);
  });
});
