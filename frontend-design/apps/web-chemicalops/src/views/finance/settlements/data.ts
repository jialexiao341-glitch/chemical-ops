import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { FinanceApi } from '#/api';

import { SETTLEMENT_STATUS_DICT } from '#/constants/dictionary';
import { formatAmount, formatDateTime } from '#/utils/format';

/** 列表筛选条件（后端支持 status 与 supplier_id） */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: SETTLEMENT_STATUS_DICT.options(),
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
  onActionClick: OnActionClickFn<FinanceApi.Settlement>,
  currentUserId?: string | number,
): VxeTableGridColumns {
  return [
    { field: 'settlement_no', minWidth: 170, title: '结算单号' },
    {
      field: 'supplier_id',
      formatter: ({ cellValue }) => resolveSupplier(cellValue),
      minWidth: 150,
      title: '供应商',
    },
    {
      align: 'right',
      field: 'settlement_amount',
      formatter: ({ cellValue }) => formatAmount(cellValue),
      title: '结算金额',
      width: 120,
    },
    { field: 'currency_code', title: '币种', width: 80 },
    {
      field: 'reconciliation_id',
      formatter: ({ cellValue }) => (cellValue ? `#${cellValue}` : '-'),
      title: '对账单',
      width: 90,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: SETTLEMENT_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    {
      formatter: ({ cellValue }) => formatDateTime(cellValue),
      field: 'created_at',
      title: '创建时间',
      width: 160,
    },
    {
      align: 'center',
      cellRender: {
        attrs: { onClick: onActionClick },
        name: 'CellOperation',
        options: [
          {
            code: 'confirm',
            text: '确认结算',
            auth: 'finance.settlements.approve',
            show: (row: FinanceApi.Settlement) =>
              row.status === 'DRAFT' &&
              String(row.created_by) !== String(currentUserId),
          },
          {
            code: 'cancel',
            text: '取消',
            auth: 'finance.settlements.write',
            danger: true,
            show: (row: FinanceApi.Settlement) => row.status === 'DRAFT',
          },
        ],
        props: {
          menuCodes: ['cancel'],
          menuText: '更多',
          renderMode: 'menu',
        },
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 130,
    },
  ];
}
