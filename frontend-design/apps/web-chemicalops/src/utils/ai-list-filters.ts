import type { AiApi } from '#/api';

interface AiFilterTarget {
  dataset: string;
  fields: Record<string, string>;
  keyword: boolean;
  label: string;
  path: string;
}

export const AI_FILTER_TARGETS: AiFilterTarget[] = [
  {
    dataset: 'purchase_requests',
    fields: { status: 'status' },
    keyword: true,
    label: '采购申请',
    path: '/procurement/requests',
  },
  {
    dataset: 'purchase_orders',
    fields: { status: 'status' },
    keyword: true,
    label: '采购订单',
    path: '/procurement/orders',
  },
  {
    dataset: 'deliveries',
    fields: { status: 'status' },
    keyword: true,
    label: '到货单',
    path: '/warehouse/deliveries',
  },
  {
    dataset: 'quality_acceptances',
    fields: { result: 'result' },
    keyword: false,
    label: '质量验收',
    path: '/quality/acceptances',
  },
  {
    dataset: 'exceptions',
    fields: { status: 'status', type: 'exception_type' },
    keyword: false,
    label: '运营异常',
    path: '/operations/exceptions',
  },
  {
    dataset: 'finance_reconciliations',
    fields: { status: 'status' },
    keyword: false,
    label: '财务对账',
    path: '/finance/reconciliations',
  },
  {
    dataset: 'suppliers',
    fields: { region: 'region', status: 'status' },
    keyword: true,
    label: '供应商',
    path: '/master/suppliers',
  },
];

interface AiFilterFormApi {
  setValues: (values: Record<string, string>) => unknown;
}

/** 业务列表打开时，把明确支持的 AI 条件写入现有筛选表单。 */
export async function applyAiFiltersToList(
  dataset: string,
  rawQuery: unknown,
  formApi: AiFilterFormApi,
) {
  const target = AI_FILTER_TARGETS.find((item) => item.dataset === dataset);
  if (!target || typeof rawQuery !== 'string') return false;

  try {
    const payload = JSON.parse(rawQuery) as AiApi.NLFilterResult;
    if (payload.dataset !== dataset) return false;
    const values: Record<string, string> = {};
    for (const [key, field] of Object.entries(target.fields)) {
      const value = payload.filters[key];
      if (value) values[field] = value;
    }
    if (target.keyword && payload.keywords) values.keyword = payload.keywords;
    await formApi.setValues(values);
    return Object.keys(values).length > 0;
  } catch {
    return false;
  }
}
