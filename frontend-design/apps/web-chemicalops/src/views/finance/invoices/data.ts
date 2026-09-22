import type { VbenFormSchema } from '#/adapter/form';
import type { VxeTableGridColumns } from '#/adapter/vxe-table';

import { INVOICE_STATUS_DICT } from '#/constants/dictionary';
import { formatAmount, formatDateTime } from '#/utils/format';

/** 列表筛选条件（后端支持 reconciliation_id 与 status） */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: INVOICE_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/** 列表列定义 */
export function useColumns(
  resolveSupplier: (id?: null | number) => string,
): VxeTableGridColumns {
  return [
    { field: 'invoice_no', minWidth: 160, title: '发票记录号' },
    { field: 'invoice_number', minWidth: 150, title: '发票号码' },
    {
      field: 'invoice_code',
      formatter: ({ cellValue }) => cellValue || '-',
      title: '发票代码',
      width: 130,
    },
    {
      formatter: ({ cellValue }) => formatDateTime(cellValue),
      field: 'invoice_date',
      title: '开票日期',
      width: 120,
    },
    {
      align: 'right',
      field: 'amount_excl_tax',
      formatter: ({ cellValue }) => formatAmount(cellValue),
      title: '不含税',
      width: 110,
    },
    {
      align: 'right',
      field: 'tax_amount',
      formatter: ({ cellValue }) => formatAmount(cellValue),
      title: '税额',
      width: 100,
    },
    {
      align: 'right',
      field: 'amount_incl_tax',
      formatter: ({ cellValue }) => formatAmount(cellValue),
      title: '价税合计',
      width: 120,
    },
    { field: 'currency_code', title: '币种', width: 80 },
    {
      field: 'supplier_id',
      formatter: ({ cellValue }) => resolveSupplier(cellValue),
      minWidth: 140,
      title: '供应商',
    },
    {
      cellRender: {
        name: 'CellTag',
        options: INVOICE_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    {
      field: 'reconciliation_id',
      formatter: ({ cellValue }) => (cellValue ? `#${cellValue}` : '-'),
      title: '对账单',
      width: 90,
    },
    {
      align: 'center',
      field: 'operation',
      fixed: 'right',
      slots: { default: 'operation' },
      title: '操作',
      width: 190,
    },
  ];
}
