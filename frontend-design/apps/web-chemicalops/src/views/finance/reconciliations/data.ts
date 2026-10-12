import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { FinanceApi } from '#/api';

import { RECONCILIATION_STATUS_DICT } from '#/constants/dictionary';
import { formatAmount, formatDateTime } from '#/utils/format';

/** 列表筛选条件（后端支持 status 与 supplier_id） */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: RECONCILIATION_STATUS_DICT.options(),
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
  onActionClick: OnActionClickFn<FinanceApi.Reconciliation>,
): VxeTableGridColumns {
  return [
    { field: 'reconciliation_no', minWidth: 170, title: '对账单号' },
    {
      field: 'supplier_id',
      formatter: ({ cellValue }) => resolveSupplier(cellValue),
      minWidth: 160,
      title: '供应商',
    },
    {
      align: 'right',
      field: 'total_amount',
      formatter: ({ cellValue, row }) => formatAmount(cellValue, row.amount_precision ?? 2),
      title: '应付金额',
      width: 130,
    },
    { field: 'currency_code', title: '币种', width: 80 },
    {
      field: 'items_version',
      title: '明细依据',
      width: 140,
      formatter: ({ cellValue }) => Number(cellValue) > 0 ? `第 ${cellValue} 版快照` : '历史单据级记录',
    },
    {
      field: 'po_id',
      formatter: ({ cellValue }) => (cellValue ? `#${cellValue}` : '-'),
      title: '订单',
      width: 90,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: RECONCILIATION_STATUS_DICT.items,
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
          { code: 'items', text: (row: FinanceApi.Reconciliation) => row.items_version > 0 ? '对账明细' : '对账依据' },
          { code: 'collaboration', text: '供应商协同', auth: 'finance.reconciliations.read' },
          { code: 'confirm', text: '确认对账', auth: 'finance.reconciliations.write', show: (row: FinanceApi.Reconciliation) => ['DRAFT', 'DISPUTED'].includes(row.status) },
          { code: 'dispute', text: '发起争议', auth: 'finance.reconciliations.write', danger: true, show: (row: FinanceApi.Reconciliation) => ['DRAFT', 'CONFIRMED'].includes(row.status) },
        ],
        props: { menuCodes: ['collaboration', 'confirm', 'dispute'], menuText: '更多', renderMode: 'menu' },
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 130,
    },
  ];
}

/** 详情抽屉可复用的行类型别名 */
export type ReconciliationRow = FinanceApi.Reconciliation;
