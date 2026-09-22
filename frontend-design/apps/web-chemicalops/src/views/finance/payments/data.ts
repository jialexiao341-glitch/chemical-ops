import type { VbenFormSchema } from '#/adapter/form';
import type { VxeTableGridColumns } from '#/adapter/vxe-table';

import { PAYMENT_METHOD_DICT, PAYMENT_STATUS_DICT } from '#/constants/dictionary';
import { formatAmount, formatDateTime } from '#/utils/format';

/** 列表筛选条件（后端支持 reconciliation_id 与 status） */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: PAYMENT_STATUS_DICT.options(),
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
    { field: 'payment_no', minWidth: 170, title: '付款单号' },
    {
      field: 'supplier_id',
      formatter: ({ cellValue }) => resolveSupplier(cellValue),
      minWidth: 150,
      title: '供应商',
    },
    {
      align: 'right',
      field: 'amount',
      formatter: ({ cellValue }) => formatAmount(cellValue),
      title: '付款金额',
      width: 120,
    },
    { field: 'currency_code', title: '币种', width: 80 },
    {
      cellRender: {
        name: 'CellTag',
        options: PAYMENT_METHOD_DICT.items,
      },
      field: 'payment_method',
      title: '付款方式',
      width: 110,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: PAYMENT_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    {
      field: 'transaction_ref',
      formatter: ({ cellValue }) => cellValue || '-',
      minWidth: 140,
      title: '外部流水号',
    },
    {
      formatter: ({ cellValue }) => formatDateTime(cellValue),
      field: 'created_at',
      title: '申请时间',
      width: 160,
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
