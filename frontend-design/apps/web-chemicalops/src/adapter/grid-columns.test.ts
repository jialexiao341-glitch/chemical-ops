import { describe, expect, it } from 'vitest';

import { fitBusinessColumns } from './grid-columns';

describe('业务列表列宽', () => {
  it('所有普通数据列共同填满宽度，保留字段最小空间和原配置', () => {
    const columns = [
      { field: 'rfq_no', minWidth: 220 },
      { field: 'quote_deadline', width: 170 },
      { field: 'quote_count', width: 100, minWidth: 110 },
    ];
    expect(fitBusinessColumns(columns)).toEqual([
      { field: 'rfq_no', minWidth: 220 },
      { field: 'quote_deadline', minWidth: 170 },
      { field: 'quote_count', minWidth: 110 },
    ]);
    expect(columns[1]?.width).toBe(170);
  });

  it('不拉伸选择、展开、固定操作及明确配置的百分比列，支持分组表头', () => {
    const fixed = [
      { type: 'checkbox' as const, width: 48 },
      { type: 'expand' as const, width: 48 },
      { field: 'operation', fixed: 'right' as const, width: 130 },
      { field: '__action', width: 110 },
      { field: 'custom', width: '25%' },
    ];
    expect(fitBusinessColumns(fixed)).toEqual(fixed);
    expect(fitBusinessColumns([{ title: '金额', children: [{ field: 'amount', width: 160, align: 'right' }] }]))
      .toEqual([{ title: '金额', children: [{ field: 'amount', minWidth: 160, align: 'right' }] }]);
  });
});
