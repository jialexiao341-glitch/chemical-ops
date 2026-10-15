import type { AgentApi } from '../../../api/ai/agent';
import { AI_TASK_STATUS_LABELS } from '../../../api/ai/task-status';

/** 字符串分组，去掉无意义的小数零而不经浮点数舍入。 */
export function agentDisplayNumber(value: string) {
  if (!/^-?\d+(\.\d+)?$/.test(value)) return value;
  const [integer = '', fraction = ''] = value.split('.');
  const significant = fraction.replace(/0+$/, '');
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (significant ? `.${significant}` : '');
}

/** 汇总完整 totals，使用定点整数保留数量精度，按原始单位分别合计。 */
export function inventorySummary(task: AgentApi.Task) {
  const inventory = primaryTaskResults(task).flatMap((entry) => entry.result?.tool === 'inventory.query_available' ? [entry.result] : []);
  const totals = new Map<number | string, { amount: bigint; scale: number; unit: string }>();
  for (const result of inventory) for (const row of result.totals) {
    const [integer = '0', fraction = ''] = row.available_quantity.split('.');
    const amount = BigInt(integer + fraction);
    const key = row.unit_id ?? row.unit_name;
    const previous = totals.get(key) ?? { amount: 0n, scale: 0, unit: row.unit_name };
    const scale = Math.max(previous.scale, fraction.length);
    totals.set(key, { amount: previous.amount * 10n ** BigInt(scale - previous.scale) + amount * 10n ** BigInt(scale - fraction.length), scale, unit: row.unit_name });
  }
  const quantities = [...totals.values()].map(({ amount, scale, unit }) => {
    const sign = amount < 0n ? '-' : '';
    const digits = (amount < 0n ? -amount : amount).toString().padStart(scale + 1, '0');
    const value = scale ? `${sign}${digits.slice(0, -scale)}.${digits.slice(-scale)}` : `${sign}${digits}`;
    return `${agentDisplayNumber(value)} ${unit}`;
  });
  return quantities.length
    ? `查到这 ${inventory.length} 个规格的可用库存合计为 ${quantities.join('、')}。`
    : `查询了这 ${inventory.length} 个规格，暂时没有找到库存记录。`;
}

/** 完成态只展示模型引用的实际证据，所有中间定位步骤留在折叠轨迹中。 */
export function primaryTaskResults(task: AgentApi.Task) {
  const finish = task.trace.at(-1);
  if (task.status === 'SUCCEEDED' && finish?.action === 'finish') {
    return task.trace.filter((entry) => entry.status === 'SUCCEEDED' && entry.result && finish.evidence_steps?.includes(entry.step));
  }
  const latest = new Map<string, AgentApi.Step>();
  for (const entry of task.trace) {
    if (entry.status === 'SUCCEEDED' && entry.result && ['inventory.query_available', 'supplier_quotes.compare'].includes(entry.result.tool)) {
      const key = entry.result.tool === 'inventory.query_available'
        ? `${entry.result.tool}:${entry.result.product_id}:${entry.result.warehouse_id ?? 'all'}`
        : entry.result.tool;
      latest.set(key, entry);
    }
  }
  return [...latest.values()];
}

/** 用本次目录定位结果标识规格，不能把单个规格可用量误当成全部规格合计。 */
export function inventoryProductLabel(task: AgentApi.Task, productId: number, fallback: string) {
  for (const entry of [...task.trace].reverse()) {
    if (entry.result?.tool !== 'catalog.search_products') continue;
    const product = entry.result.rows.find((row) => row.product_id === productId);
    if (product) return `${product.product_name} · ${product.product_code}（${product.model || '未登记型号'} / ${product.packaging_spec || '未登记包装'}）`;
  }
  return `${fallback} · 产品规格 #${productId}`;
}

export const TASK_LABELS: Record<AgentApi.Task['status'], string> = {
  RUNNING: AI_TASK_STATUS_LABELS.RUNNING, WAITING_INPUT: AI_TASK_STATUS_LABELS.WAITING_INPUT,
  SUCCEEDED: AI_TASK_STATUS_LABELS.SUCCEEDED, FAILED: AI_TASK_STATUS_LABELS.FAILED, CANCELLED: AI_TASK_STATUS_LABELS.CANCELLED,
};
export const TOOL_LABELS: Record<string, string> = {
  'catalog.search_products': '定位产品',
  'inventory.query_available': '查询库存',
  'supplier_quotes.find_rfq_items': '定位询价',
  'supplier_quotes.compare': '比较报价',
};
export const SOURCE_LABELS: Record<string, string> = {
  md_products: '产品规格', rfq_items: '询价明细', inventory_balances: '库存余额', supplier_quote_items: '报价明细',
};

/** 仅最新强制等待步骤可提供候选，避免从上一轮历史选择失效对象。 */
export function waitingCandidates(task?: AgentApi.Task) {
  if (task?.status !== 'WAITING_INPUT') return undefined;
  const last = task.trace.at(-1);
  if (last?.status !== 'SUCCEEDED' || !last.result) return undefined;
  return ['catalog.search_products', 'supplier_quotes.find_rfq_items'].includes(last.result.tool)
    ? last.result : undefined;
}

/** 低版本或其他任务的迟到响应不能覆盖刷新/取消得到的新状态。 */
export function acceptTask(current: AgentApi.Task | undefined, incoming: AgentApi.Task) {
  return !current || (incoming.id === current.id && incoming.revision >= current.revision);
}

export function inventorySource(productId: number, warehouseId: number) {
  return {
    path: '/warehouse/inventory',
    query: { ai_filters: JSON.stringify({ dataset: 'inventory', filters: { product_id: String(productId), warehouse_id: String(warehouseId) } }) },
  };
}

/** 预览只来自对应来源记录，不用第一行的数值冒充其他来源。 */
export function agentSourcePreview(result: AgentApi.Result, source: AgentApi.Source) {
  const base = { title: SOURCE_LABELS[source.resource] || '业务记录', description: '当前任务保存的来源记录', reference: `${SOURCE_LABELS[source.resource] || '业务记录'} #${source.record_id}`, to: undefined as undefined | { path: string; query?: Record<string, string> }, linkLabel: '查看原记录' };
  if (result.tool === 'inventory.query_available' && source.resource === 'inventory_balances') {
    const row = result.rows.find((item) => item.balance_id === source.record_id);
    if (row) return { ...base, title: `${result.product_name} · ${row.warehouse_name}`, description: `批次 ${row.batch_no} · 账面可用 ${agentDisplayNumber(row.available_quantity)} ${row.unit_name}`, to: inventorySource(result.product_id, row.warehouse_id), linkLabel: '查看库存列表' };
  }
  if (result.tool === 'supplier_quotes.compare' && source.resource === 'supplier_quote_items') {
    const row = result.rows.find((item) => item.quote_item_id === source.record_id);
    if (row) return { ...base, title: `${row.supplier_name} · ${row.quote_no}`, description: `未税单价 ${agentDisplayNumber(row.unit_price)} ${row.currency_code}/${row.unit_name} · ${row.rank === null ? '不参与排序' : `可比组内第 ${row.rank} 名`}，不同组不能相互比较。`, to: { path: '/procurement/rfqs', query: { ai_record_id: String(result.rfq_id) } } };
  }
  if (result.tool === 'supplier_quotes.find_rfq_items' && source.resource === 'rfq_items') {
    const row = result.rows.find((item) => item.rfq_item_id === source.record_id);
    if (row) return { ...base, title: row.rfq_no, description: `${row.specification || '未登记规格'} · ${row.technical_requirements || '无技术要求'}`, to: { path: '/procurement/rfqs', query: { ai_record_id: String(row.rfq_id) } } };
  }
  if (result.tool === 'catalog.search_products' && source.resource === 'md_products') {
    const row = result.rows.find((item) => item.product_id === source.record_id);
    if (row) return { ...base, title: `${row.product_name} · ${row.product_code}`, description: `${row.model || '未登记型号'} · ${row.packaging_spec || '未登记包装'} · ${row.unit_name}` };
  }
  return base;
}

export const TASK_ERROR_HELP: Record<string, string> = {
  PERMISSION_DENIED: '请核对产品、库存或询价读取权限；授权范围变化后需重新查询。',
  TASK_TIMEOUT: '查询超时。请缩小查询范围后重新发起。',
  MODEL_FORMAT_ERROR: '模型返回格式无效。请重新发起；若重复发生，请联系管理员检查模型配置。',
  STEP_LIMIT: '查询步骤达到上限。请明确产品规格及询价编号后重新发起。',
  CONTEXT_LIMIT: '任务内容超过上限。请缩小查询范围后重新发起。',
};
