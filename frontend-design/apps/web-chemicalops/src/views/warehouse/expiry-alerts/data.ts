import type { VxeTableGridColumns } from '#/adapter/vxe-table';

import { EXPIRY_ALERT_LEVEL_DICT } from '#/constants/dictionary';
import { formatDate, formatQuantity } from '#/utils/format';

/**
 * 列表列定义。
 *
 * 预警级别同时用文字标签和颜色表达，避免只靠颜色传递风险信息。
 */
export function useColumns(
  resolveProduct: (id?: null | number) => string,
  resolveWarehouse: (id?: null | number) => string,
): VxeTableGridColumns {
  return [
    {
      field: 'product_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        resolveProduct(cellValue),
      minWidth: 180,
      title: '产品',
    },
    { field: 'batch_no', width: 160, title: '批次号' },
    {
      field: 'warehouse_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        resolveWarehouse(cellValue),
      title: '仓库',
      width: 140,
    },
    {
      field: 'quantity',
      align: 'right',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatQuantity(cellValue),
      title: '数量',
      width: 120,
    },
    {
      field: 'expiry_date',
      formatter: ({ cellValue }: { cellValue: any }) => formatDate(cellValue),
      title: '有效期至',
      width: 130,
    },
    {
      field: 'days_remaining',
      formatter: ({ cellValue }: { cellValue: any }) =>
        cellValue < 0 ? `已过期 ${Math.abs(cellValue)} 天` : `剩余 ${cellValue} 天`,
      title: '剩余天数',
      width: 140,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: EXPIRY_ALERT_LEVEL_DICT.items,
      },
      field: 'alert_level',
      title: '预警级别',
      width: 120,
    },
  ];
}
