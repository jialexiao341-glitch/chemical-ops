import type { AgentApi } from '../../../api/ai/agent';
import { describe, expect, it } from 'vitest';
import { acceptTask, inventoryProductLabel, inventorySource, inventorySummary, waitingCandidates, agentDisplayNumber, primaryTaskResults, agentSourcePreview, TASK_LABELS, TASK_ERROR_HELP } from './task-view';

const waiting: AgentApi.Task = { id: 'a', revision: 2, status: 'WAITING_INPUT', reply: '', error_code: null, messages: [], trace: [
  { step: 1, action: 'call_tool', status: 'SUCCEEDED', result: { tool: 'catalog.search_products', total_rows: 2, truncated: false, rows: [], sources: [] } },
] };

describe('采购任务状态与来源', () => {
  it('全选结论只汇总完整 totals，按单位分别合计并保留小数精度', () => {
    const task = { ...waiting, status: 'SUCCEEDED', trace: [
      { step: 1, status: 'SUCCEEDED', result: { tool: 'inventory.query_available', product_id: 1, totals: [{ unit_id: 1, unit_name: '升', available_quantity: '1954.000000' }, { unit_id: 2, unit_name: '千克', available_quantity: '0.1' }] } },
      { step: 2, status: 'SUCCEEDED', result: { tool: 'inventory.query_available', product_id: 2, totals: [{ unit_id: 1, unit_name: '升', available_quantity: '216.250000' }, { unit_id: 2, unit_name: '千克', available_quantity: '0.2' }] } },
    ] } as AgentApi.Task;
    expect(inventorySummary(task)).toBe('查到这 2 个规格的可用库存合计为 2,170.25 升、0.3 千克。');
  });
  it('没有库存记录时不把缺少数据表述成零库存', () => {
    const task: AgentApi.Task = { ...waiting, trace: [{ step: 1, action: 'call_tool', status: 'SUCCEEDED', result: {
      tool: 'inventory.query_available', product_id: 1, product_name: '乙醇', totals: [], rows: [], sources: [],
      total_rows: 0, truncated: false, observed_at: '', scope: '', warnings: [],
    } }] };
    expect(inventorySummary(task)).toBe('查询了这 1 个规格，暂时没有找到库存记录。');
  });
  it('五种任务终态和过程态都提供明确的界面文案', () => {
    expect(TASK_LABELS).toEqual({
      RUNNING: '正在查询',
      WAITING_INPUT: '等待补充',
      SUCCEEDED: '查询完成',
      FAILED: '已停止',
      CANCELLED: '已取消',
    });
  });
  it('所有可恢复任务错误码都有行动建议，不只显示通用提示', () => {
    for (const code of [
      'INVALID_EVIDENCE', 'INCOMPLETE_TASK', 'REPEATED_TOOL', 'TOOL_ERRORS',
      'INTENT_MISMATCH', 'TOKEN_BUDGET_EXCEEDED', 'DATABASE_ERROR',
      'MODEL_SERVICE_ERROR', 'RUNTIME_ERROR',
    ]) {
      expect(TASK_ERROR_HELP[code], code).toBeTruthy();
    }
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
  it('多规格保留每个规格的最新结果，不被最后一次同名工具调用覆盖', () => {
    const task: AgentApi.Task = { ...waiting, status: 'SUCCEEDED', trace: [
      { step: 1, action: 'call_tool', status: 'SUCCEEDED', result: inventory },
      { step: 2, action: 'call_tool', status: 'SUCCEEDED', result: { ...inventory, product_id: 12 } },
      { step: 3, action: 'call_tool', status: 'SUCCEEDED', result: inventory },
    ] };
    expect(primaryTaskResults(task).map((entry) => entry.step)).toEqual([3, 2]);
    expect(inventoryProductLabel(task, 11, '乙醇')).toBe('乙醇 · 产品规格 #11');
    const lookup: AgentApi.Step = { step: 0, action: 'call_tool', status: 'SUCCEEDED', result: {
      tool: 'catalog.search_products', total_rows: 1, truncated: false, sources: [],
      rows: [{ product_id: 11, product_code: 'ETH-001', product_name: '无水乙醇', model: '分析纯', packaging_spec: '20L', unit_name: '升' }],
    } };
    expect(inventoryProductLabel({ ...task, trace: [lookup, ...task.trace] }, 11, '乙醇')).toBe('无水乙醇 · ETH-001（分析纯 / 20L）');
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
