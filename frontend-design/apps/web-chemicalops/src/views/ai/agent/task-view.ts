import type { AgentApi } from '../../../api/ai/agent';

export const TASK_LABELS: Record<AgentApi.Task['status'], string> = {
  RUNNING: '正在查询', WAITING_INPUT: '等待补充', SUCCEEDED: '查询完成', FAILED: '已停止', CANCELLED: '已取消',
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

export const TASK_ERROR_HELP: Record<string, string> = {
  PERMISSION_DENIED: '请核对产品、库存或询价读取权限；授权范围变化后需重新查询。',
  TASK_TIMEOUT: '查询超时。请缩小查询范围后重新发起。',
  MODEL_FORMAT_ERROR: '模型返回格式无效。请重新发起；若重复发生，请联系管理员检查模型配置。',
  STEP_LIMIT: '查询步骤达到上限。请明确产品规格及询价编号后重新发起。',
  CONTEXT_LIMIT: '任务内容超过上限。请缩小查询范围后重新发起。',
};
