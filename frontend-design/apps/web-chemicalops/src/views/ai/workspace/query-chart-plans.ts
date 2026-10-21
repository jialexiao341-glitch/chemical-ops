import {
  ACCEPTANCE_RESULT_DICT,
  DELIVERY_STATUS_DICT,
  EXCEPTION_SEVERITY_DICT,
  EXCEPTION_STATUS_DICT,
  EXCEPTION_TYPE_DICT,
  INVENTORY_BALANCE_STATUS_DICT,
  PRIORITY_DICT,
  PURCHASE_ORDER_STATUS_DICT,
  PURCHASE_REQUEST_STATUS_DICT,
  RECONCILIATION_STATUS_DICT,
  SUPPLIER_STATUS_DICT,
} from '#/constants/dictionary';

export interface QueryTrace {
  dataset?: string;
  dataset_label?: string;
  row_count?: number;
  rows?: Array<Record<string, unknown>>;
  columns?: Array<{ key: string; label: string }>;
  slots?: Array<{ name: string; value: unknown }>;
  truncated?: boolean;
  unit?: null | string;
}

export interface QueryChartPlan {
  title: string;
  note?: string;
  type: 'bar' | 'donut' | 'line';
  labels: string[];
  series: Array<{ name: string; values: number[] }>;
  unit?: string;
  horizontal?: boolean;
}

type Row = Record<string, unknown>;
type Entry = { label: string; value: number };

const CATEGORY_LABELS: Record<string, string> = {
  certificate_complete: '资料齐全情况',
  cooperation_level: '合作等级',
  currency: '币种',
  expiry_date: '有效期',
  priority: '优先级',
  product: '产品',
  region: '区域',
  result: '验收结果',
  severity: '严重程度',
  status: '状态',
  supplier: '供应商',
  type: '异常类型',
  warehouse: '仓库',
};
const COMPOSITION_DIMENSIONS = new Set([
  'certificate_complete', 'cooperation_level', 'priority', 'result',
  'severity', 'status', 'type',
]);

function label(value: unknown, fallback = '未标注'): string {
  const text = String(value ?? '').trim();
  return text || fallback;
}

function number(value: unknown): null | number {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function sumBy(rows: Row[], key: (row: Row) => string, value: (row: Row) => null | number): Entry[] {
  const totals = new Map<string, number>();
  for (const row of rows) {
    const amount = value(row);
    if (amount === null) continue;
    const name = key(row);
    totals.set(name, (totals.get(name) ?? 0) + amount);
  }
  return [...totals].map(([name, amount]) => ({ label: name, value: amount }));
}

function countBy(rows: Row[], key: (row: Row) => string): Entry[] {
  return sumBy(rows, key, () => 1);
}

function categoryLabel(dataset: string | undefined, dimension: string, value: unknown): string {
  const raw = label(value);
  if (dimension === 'certificate_complete') return raw === '1' ? '资料齐全' : raw === '0' ? '资料不齐' : raw;
  if (dimension === 'priority') return PRIORITY_DICT.label(raw);
  if (dimension === 'result') return ACCEPTANCE_RESULT_DICT.label(raw);
  if (dimension === 'severity') return EXCEPTION_SEVERITY_DICT.label(raw);
  if (dimension === 'type') return EXCEPTION_TYPE_DICT.label(raw);
  if (dimension !== 'status') return raw;
  const dict = {
    deliveries: DELIVERY_STATUS_DICT,
    exceptions: EXCEPTION_STATUS_DICT,
    finance_reconciliations: RECONCILIATION_STATUS_DICT,
    inventory: INVENTORY_BALANCE_STATUS_DICT,
    purchase_orders: PURCHASE_ORDER_STATUS_DICT,
    purchase_requests: PURCHASE_REQUEST_STATUS_DICT,
    suppliers: SUPPLIER_STATUS_DICT,
  }[dataset || ''];
  return dict?.label(raw) ?? raw;
}

function bar(title: string, entries: Entry[], unit?: string, note?: string): QueryChartPlan | undefined {
  if (!entries.length) return;
  const shown = [...entries].sort((a, b) => b.value - a.value).slice(0, 10);
  return {
    title,
    note: entries.length > shown.length ? `${note ? `${note}；` : ''}图中展示前 10 项` : note,
    type: 'bar',
    labels: shown.map((item) => item.label),
    series: [{ name: title, values: shown.map((item) => item.value) }],
    unit,
    horizontal: true,
  };
}

function donut(title: string, entries: Entry[], unit?: string, note?: string): QueryChartPlan | undefined {
  const usable = entries.filter((item) => item.value > 0);
  if (!usable.length) return;
  return {
    title,
    note,
    type: 'donut',
    labels: usable.map((item) => item.label),
    series: [{ name: title, values: usable.map((item) => item.value) }],
    unit,
  };
}

function line(title: string, entries: Entry[], unit?: string, note?: string): QueryChartPlan | undefined {
  if (!entries.length) return;
  const sorted = [...entries].sort((a, b) => a.label.localeCompare(b.label));
  return {
    title,
    note,
    type: 'line',
    labels: sorted.map((item) => item.label),
    series: [{ name: title, values: sorted.map((item) => item.value) }],
    unit,
  };
}

function slot(trace: QueryTrace, name: string): string {
  return label(trace.slots?.find((item) => item.name === name)?.value, '');
}

function genericCharts(trace: QueryTrace, rows: Row[]): QueryChartPlan[] {
  const metric = slot(trace, 'metric');
  const dimension = slot(trace, 'group_by');
  if (!rows.some((row) => number(row.metric_value) !== null)) return [];
  // 聚合库存如果没有单位列，不能把不同计量单位画在同一坐标轴上。
  if (metric === 'sum_quantity' && !rows.every((row) => label(row.unit, '') !== '')) return [];

  const groups = metric === 'amount' || metric === 'sum_quantity'
    ? [...new Set(rows.map((row) => label(row[metric === 'amount' ? 'currency' : 'unit'], '')))]
    : [''];
  const charts: QueryChartPlan[] = [];
  for (const group of groups) {
    if ((metric === 'amount' || metric === 'sum_quantity') && !group) continue;
    const scoped = group
      ? rows.filter((row) => label(row[metric === 'amount' ? 'currency' : 'unit'], '') === group)
      : rows;
    const entries = dimension
      ? sumBy(scoped, (row) => categoryLabel(trace.dataset, dimension, row[dimension]), (row) => number(row.metric_value))
      : [{ label: trace.dataset_label || '查询结果', value: scoped.reduce((sum, row) => sum + (number(row.metric_value) ?? 0), 0) }];
    const suffix = group ? ` · ${group}` : '';
    const title = `${CATEGORY_LABELS[dimension] || '查询结果'}${dimension ? '分布' : '汇总'}${suffix}`;
    const chart = dimension && COMPOSITION_DIMENSIONS.has(dimension) && entries.length <= 6
      ? donut(title, entries, group || trace.unit || undefined)
      : dimension === 'expiry_date'
        ? line(title, entries, group || trace.unit || undefined)
        : bar(title, entries, group || trace.unit || undefined);
    if (chart) charts.push(chart);
  }
  return charts;
}

function inventoryBatchCharts(rows: Row[]): QueryChartPlan[] {
  const charts: QueryChartPlan[] = [];
  const groups = [...new Set(rows.map((row) => `${label(row.product)}\u0000${label(row.unit)}`))];
  for (const group of groups.slice(0, 4)) {
    const [product = '', unit = ''] = group.split('\u0000');
    const scoped = rows.filter((row) => label(row.product) === product && label(row.unit) === unit);
    const warehouse = bar(`${product} · 各仓库可用量`, sumBy(scoped, (row) => label(row.warehouse), (row) => number(row.available_quantity)), unit);
    const batches = bar(`${product} · 各批次可用量`, sumBy(scoped, (row) => `${label(row.batch_no)} · ${label(row.warehouse)}`, (row) => number(row.available_quantity)), unit);
    if (warehouse) charts.push(warehouse);
    if (batches) charts.push(batches);
  }
  if (groups.length > 4 && charts[0]) charts[0].note = '图中仅展示前 4 组产品和计量单位；完整明细见下方数据';
  return charts;
}

function weeklyRiskCharts(rows: Row[]): QueryChartPlan[] {
  const risks: Entry[] = [
    { label: '逾期', value: rows.filter((row) => number(row.overdue_this_week) === 1).length },
    { label: '短交', value: rows.filter((row) => (number(row.short_quantity) ?? 0) > 0).length },
    { label: '单证未齐', value: rows.filter((row) => number(row.documents_missing) === 1).length },
  ];
  return [
    bar('履约风险类型', risks, '条', '一条明细可能同时命中多种风险'),
    bar('各供应商风险明细', countBy(rows, (row) => label(row.supplier)), '条'),
  ].filter((chart): chart is QueryChartPlan => Boolean(chart));
}

function financeGapCharts(rows: Row[]): QueryChartPlan[] {
  const stages = [
    ['对账', 'reconciliation_progress'], ['开票', 'invoice_progress'],
    ['付款', 'payment_progress'], ['结算', 'settlement_progress'],
  ] as const;
  const charts: QueryChartPlan[] = [];
  const pending = stages.map(([name, key]) => ({
    label: name,
    value: rows.filter((row) => row[key] === '未完成').length,
  }));
  charts.push({
    title: '各环节未完成订单数',
    note: '同一订单可能计入多个环节',
    type: 'bar', horizontal: true, unit: '笔',
    labels: pending.map((item) => item.label),
    series: [{ name: '未完成订单', values: pending.map((item) => item.value) }],
  });

  for (const currency of [...new Set(rows.map((row) => label(row.finance_currency, '')))]) {
    if (!currency) continue;
    const scoped = rows.filter((row) => label(row.finance_currency, '') === currency).slice(0, 10);
    const labels = scoped.map((row) => label(row.po_no));
    if (!labels.length) continue;
    charts.push({
      title: `订单财务金额对比 · ${currency}`,
      note: '对账金额、已核验发票和已付款金额按财务币种比较',
      type: 'bar', horizontal: true, unit: currency, labels,
      series: [
        { name: '对账金额', values: scoped.map((row) => number(row.reconciliation_amount) ?? 0) },
        { name: '已核验发票', values: scoped.map((row) => number(row.verified_invoice_amount) ?? 0) },
        { name: '已付款', values: scoped.map((row) => number(row.paid_amount) ?? 0) },
      ],
    });
  }
  return charts;
}

function supplierProfileCharts(rows: Row[]): QueryChartPlan[] {
  const charts: QueryChartPlan[] = [];
  const groups = [...new Set(rows.map((row) => `${label(row.product)}\u0000${label(row.currency, '')}\u0000${label(row.quote_unit, '')}`))];
  for (const group of groups.slice(0, 4)) {
    const [product = '', currency = '', unit = ''] = group.split('\u0000');
    if (!currency || !unit) continue;
    const scoped = rows.filter((row) => label(row.product) === product && label(row.currency, '') === currency && label(row.quote_unit, '') === unit);
    const entries = scoped.filter((row) => row.quote_date && number(row.quoted_unit_price) !== null)
      .map((row) => ({ label: `${label(row.quote_date)} · ${label(row.quote_no)}`, value: number(row.quoted_unit_price) ?? 0 }));
    const chart = line(`${product} · 报价变化`, entries, `${currency}/${unit}`);
    if (chart) charts.push(chart);
  }
  const leadRows = rows.filter((row) => number(row.quoted_lead_days) !== null || number(row.avg_actual_lead_days) !== null).slice(0, 10);
  if (leadRows.length) charts.push({
    title: '报价交期与实际到货周期', type: 'bar', horizontal: true, unit: '天',
    labels: leadRows.map((row) => `${label(row.supplier)} / ${label(row.product)}`),
    series: [
      { name: '报价交期', values: leadRows.map((row) => number(row.quoted_lead_days) ?? 0) },
      { name: '实际平均周期', values: leadRows.map((row) => number(row.avg_actual_lead_days) ?? 0) },
    ],
  });
  if (groups.length > 4 && charts[0]) charts[0].note = '图中仅展示前 4 组报价组合；完整明细见下方数据';
  return charts;
}

function movementCharts(rows: Row[]): QueryChartPlan[] {
  const charts: QueryChartPlan[] = [];
  const events = donut('库存变动类型', countBy(rows, (row) => label(row.event_type)), '条');
  if (events) charts.push(events);
  const groups = [...new Set(rows.map((row) => `${label(row.product)}\u0000${label(row.unit)}`))];
  for (const group of groups.slice(0, 4)) {
    const [product = '', unit = ''] = group.split('\u0000');
    const scoped = rows.filter((row) => label(row.product) === product && label(row.unit) === unit);
    const entries = sumBy(scoped, (row) => label(row.event_time).slice(0, 10), (row) => number(row.quantity_change));
    const chart = line(`${product} · 每日净变动`, entries, unit, '只统计当前返回的流水，不代表期末库存');
    if (chart) charts.push(chart);
  }
  if (groups.length > 4 && charts[0]) charts[0].note = '图中仅展示前 4 组产品和计量单位；完整明细见下方数据';
  return charts;
}

function overdueOrderCharts(rows: Row[]): QueryChartPlan[] {
  const ordersBySupplier = new Map<string, Set<string>>();
  for (const row of rows) {
    const supplier = label(row.supplier);
    const orderNo = label(row.po_no, '');
    if (!orderNo) continue;
    const orders = ordersBySupplier.get(supplier) ?? new Set<string>();
    orders.add(orderNo);
    ordersBySupplier.set(supplier, orders);
  }
  const orderCounts = [...ordersBySupplier].map(([supplier, orders]) => ({ label: supplier, value: orders.size }));
  const charts: QueryChartPlan[] = [];
  const orderChart = bar('各供应商逾期未交订单数（订单号去重）', orderCounts, '个订单');
  if (orderChart) charts.push(orderChart);

  const units = [...new Set(rows.map((row) => label(row.order_unit, '')))].filter(Boolean);
  for (const unit of units) {
    const scoped = rows.filter((row) => label(row.order_unit, '') === unit);
    const quantityChart = bar(
      `各供应商逾期未交数量 · ${unit}`,
      sumBy(scoped, (row) => label(row.supplier), (row) => number(row.unfulfilled_quantity)),
      unit,
    );
    if (quantityChart) charts.push(quantityChart);
  }
  return charts;
}

function orderTraceCharts(rows: Row[]): QueryChartPlan[] {
  return [
    donut('业务环节可见状态', countBy(rows, (row) => label(row.status)), '个环节'),
    bar('各环节关联记录', rows.filter((row) => row.status === 'AVAILABLE').map((row) => ({
      label: label(row.stage), value: Array.isArray(row.records) ? row.records.length : 0,
    })), '条', '仅统计当前账号可见的记录'),
  ].filter((chart): chart is QueryChartPlan => Boolean(chart));
}

export function buildQueryCharts(trace?: QueryTrace): QueryChartPlan[] {
  const rows = Array.isArray(trace?.rows) ? trace.rows.filter((row): row is Row => Boolean(row) && typeof row === 'object' && !Array.isArray(row)) : [];
  if (!trace || !rows.length) return [];
  switch (trace.dataset) {
    case 'approved_requests_without_rfq':
      return [
        donut('待询价申请优先级', countBy(rows, (row) => categoryLabel(trace.dataset, 'priority', row.priority)), '条'),
        line('审批日期分布', countBy(rows.filter((row) => row.approved_at), (row) => label(row.approved_at).slice(0, 10)), '条'),
      ].filter((chart): chart is QueryChartPlan => Boolean(chart));
    case 'weekly_order_risks': return weeklyRiskCharts(rows);
    case 'inventory_by_batch': return inventoryBatchCharts(rows);
    case 'accepted_orders_finance_gaps': return financeGapCharts(rows);
    case 'supplier_quote_delivery_profile': return supplierProfileCharts(rows);
    case 'inventory_movement_trace': return movementCharts(rows);
    case 'overdue_unfulfilled_orders': return overdueOrderCharts(rows);
    case 'purchase_order_trace': return orderTraceCharts(rows);
    default: return genericCharts(trace, rows);
  }
}
