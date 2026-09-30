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
      align: 'left',
      title: '产品',
    },
    { field: 'batch_no', minWidth: 150, title: '批次号' },
    {
      field: 'warehouse_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        resolveWarehouse(cellValue),
      title: '仓库',
      minWidth: 200,
      align: 'left',
    },
    {
      field: 'quantity',
      align: 'right',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatQuantity(cellValue),
      title: '数量',
      minWidth: 90,
    },
    {
      field: 'expiry_date',
      formatter: ({ cellValue }: { cellValue: any }) => formatDate(cellValue),
      title: '有效期至',
      minWidth: 120,
    },
    {
      field: 'days_remaining',
      formatter: ({ cellValue }: { cellValue: any }) =>
        cellValue < 0 ? `已过期 ${Math.abs(cellValue)} 天` : `剩余 ${cellValue} 天`,
      title: '剩余天数',
      minWidth: 120,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: EXPIRY_ALERT_LEVEL_DICT.items,
      },
      field: 'alert_level',
      title: '预警级别',
      minWidth: 140,
    },
  ];
}
