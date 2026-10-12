import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { FinanceApi } from '#/api';

import { INVOICE_STATUS_DICT } from '#/constants/dictionary';
import { formatAmount, formatDate } from '#/utils/format';

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
  onActionClick: OnActionClickFn<FinanceApi.Invoice>,
  currentUserId?: string | number,
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
      formatter: ({ cellValue }) => formatDate(cellValue),
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
      cellRender: {
        attrs: { onClick: onActionClick },
        name: 'CellOperation',
        options: [
          { code: 'detail', text: '详情', auth: 'finance.invoices.read' },
          { code: 'matches', text: '行匹配', auth: 'finance.invoices.read' },
          {
            code: 'void', text: '作废', auth: 'finance.invoices.write', danger: true,
            show: (row: FinanceApi.Invoice) => ['DRAFT', 'REJECTED'].includes(row.status),
          },
          {
            code: 'submit', text: '提交核验', auth: 'finance.invoices.write',
            show: (row: FinanceApi.Invoice) => ['DRAFT', 'REJECTED'].includes(row.status),
          },
          {
            code: 'verify', text: '核验', auth: 'finance.invoices.verify',
            show: (row: FinanceApi.Invoice) => row.status === 'SUBMITTED' && String(row.submitted_by) !== String(currentUserId),
          },
          {
            code: 'reject', text: '驳回', auth: 'finance.invoices.verify', danger: true,
            show: (row: FinanceApi.Invoice) => row.status === 'SUBMITTED' && String(row.submitted_by) !== String(currentUserId),
          },
        ],
        props: {
          menuCodes: ['matches', 'void', 'submit', 'verify', 'reject'],
          menuText: '更多',
          renderMode: 'menu',
        },
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 110,
    },
  ];
}
