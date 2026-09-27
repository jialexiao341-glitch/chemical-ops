import { describe, expect, it } from 'vitest';

import { buildQueryCharts } from './query-chart-plans';

describe('AI 查询图表规划', () => {
  it('按仓库和批次展示库存，同时隔离不同计量单位', () => {
    const charts = buildQueryCharts({
      dataset: 'inventory_by_batch',
      rows: [
        { product: '乙醇', warehouse: '易燃液体周转仓', batch_no: 'A', unit: '升', available_quantity: '10' },
        { product: '乙醇', warehouse: '易燃液体周转仓', batch_no: 'B', unit: '升', available_quantity: '5' },
        { product: '乙醇', warehouse: '甲类易燃液体仓', batch_no: 'C', unit: '升', available_quantity: '20' },
        { product: '乙醇', warehouse: '甲类易燃液体仓', batch_no: 'D', unit: '千克', available_quantity: '3' },
      ],
    });

    expect(charts).toHaveLength(4);
    expect(charts[0]?.unit).toBe('升');
    expect(charts[0]?.series[0]?.values).toEqual([20, 15]);
    expect(charts[2]?.unit).toBe('千克');
    expect(charts[2]?.series[0]?.values).toEqual([3]);
  });

  it('金额按币种分图，不跨币种合计', () => {
    const charts = buildQueryCharts({
      dataset: 'purchase_orders',
      dataset_label: '采购订单',
      slots: [{ name: 'metric', value: 'amount' }, { name: 'group_by', value: 'supplier' }],
      rows: [
        { supplier: '甲', currency: 'CNY', metric_value: '100' },
        { supplier: '甲', currency: 'USD', metric_value: '20' },
        { supplier: '乙', currency: 'CNY', metric_value: '50' },
      ],
    });

    expect(charts).toHaveLength(2);
    expect(charts[0]?.unit).toBe('CNY');
    expect(charts[0]?.series[0]?.values).toEqual([100, 50]);
    expect(charts[1]?.unit).toBe('USD');
    expect(charts[1]?.series[0]?.values).toEqual([20]);
  });

  it('旧库存汇总缺少单位时不绘制误导性数量图', () => {
    expect(buildQueryCharts({
      dataset: 'inventory',
      slots: [{ name: 'metric', value: 'sum_quantity' }, { name: 'group_by', value: 'warehouse' }],
      rows: [{ warehouse: '甲仓', metric_value: '100' }],
    })).toEqual([]);
  });

  it('重叠的履约风险使用条形图', () => {
    const charts = buildQueryCharts({
      dataset: 'weekly_order_risks',
      rows: [{ supplier: '甲', overdue_this_week: 1, short_quantity: 2, documents_missing: 0 }],
    });
    expect(charts[0]?.type).toBe('bar');
    expect(charts[0]?.series[0]?.values).toEqual([1, 1, 0]);
  });

  it('库存流水用真实日期绘制净变动折线，并保留冻结事件统计', () => {
    const charts = buildQueryCharts({
      dataset: 'inventory_movement_trace',
      rows: [
        { product: '乙醇', unit: '升', event_time: '2026-09-26T08:00:00', event_type: '出库', quantity_change: '-4' },
        { product: '乙醇', unit: '升', event_time: '2026-09-25T08:00:00', event_type: '入库', quantity_change: '10' },
        { product: '乙醇', unit: '升', event_time: '2026-09-26T09:00:00', event_type: '库存冻结', quantity_change: '0' },
      ],
    });

    expect(charts).toHaveLength(2);
    expect(charts[0]?.type).toBe('donut');
    expect(charts[1]?.type).toBe('line');
    expect(charts[1]?.labels).toEqual(['2026-09-25', '2026-09-26']);
    expect(charts[1]?.series[0]?.values).toEqual([10, -4]);
  });

  it('财务金额按财务币种拆分，环节统计独立展示', () => {
    const charts = buildQueryCharts({
      dataset: 'accepted_orders_finance_gaps',
      rows: [
        { po_no: 'PO-1', finance_currency: 'CNY', reconciliation_amount: '100', verified_invoice_amount: '80', paid_amount: '20', reconciliation_progress: '已完成', invoice_progress: '未完成', payment_progress: '未完成', settlement_progress: '未完成' },
        { po_no: 'PO-2', finance_currency: 'USD', reconciliation_amount: '50', verified_invoice_amount: '0', paid_amount: '0', reconciliation_progress: '未完成', invoice_progress: '未完成', payment_progress: '未完成', settlement_progress: '未完成' },
      ],
    });

    expect(charts).toHaveLength(3);
    expect(charts[0]?.series[0]?.values).toEqual([1, 2, 2, 2]);
    expect(charts[1]?.unit).toBe('CNY');
    expect(charts[2]?.unit).toBe('USD');
  });
});
