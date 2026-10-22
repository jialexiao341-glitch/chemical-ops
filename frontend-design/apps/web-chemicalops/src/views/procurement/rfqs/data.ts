import type { VbenFormSchema } from '#/adapter/form';
import type {
  OnActionClickFn,
  VxeTableGridColumns,
} from '#/adapter/vxe-table';
import type { RfqApi } from '#/api';

import { RFQ_STATUS_DICT } from '#/constants/dictionary';
import { formatDateTime } from '#/utils/format';

/** 列表筛选条件 */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { allowClear: true, placeholder: '请输入询价单号' },
      fieldName: 'keyword',
      label: '询价单号',
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: RFQ_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/** 列表列定义 */
export function useColumns(
  onActionClick: OnActionClickFn<RfqApi.Rfq>,
): VxeTableGridColumns {
  return [
    { field: 'rfq_no', minWidth: 220, title: '询价单号' },
    { field: 'source_request_id', title: '来源申请', width: 110 },
    {
      field: 'quote_deadline',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatDateTime(cellValue),
      title: '报价截止',
      width: 170,
    },
    {
      field: 'sent_at',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatDateTime(cellValue),
      title: '发送时间',
      width: 170,
    },
    {
      align: 'center',
      field: 'supplier_count',
      formatter: ({ row }: { row: RfqApi.Rfq }) =>
        String(row.suppliers?.length ?? 0),
      title: '受邀供应商',
      width: 110,
    },
    {
      align: 'center',
      field: 'quote_count',
      formatter: ({ row }: { row: RfqApi.Rfq }) =>
        String(row.quotes?.length ?? 0),
      title: '已收报价',
      width: 100,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: RFQ_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'rfq_no',
          nameTitle: '询价单',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'edit',
            text: '编辑',
            auth: 'procurement.rfqs.write',
            disabled: (row: RfqApi.Rfq) => row.status !== 'DRAFT',
            title: (row: RfqApi.Rfq) => row.status !== 'DRAFT' ? '只有草稿可以执行此操作' : undefined,
          },
          { code: 'detail', text: '详情与比价' },
          {
            code: 'send',
            text: '发送询价',
            auth: 'procurement.rfqs.write',
            disabled: (row: RfqApi.Rfq) => row.status !== 'DRAFT',
            title: (row: RfqApi.Rfq) => row.status !== 'DRAFT' ? '只有草稿可以执行此操作' : undefined,
          },
        ],
        props: { renderMode: 'menu' },
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 130,
    },
  ];
}

/** 询价明细的编辑行 */
export interface RfqItemRow {
  source_request_item_id?: null | number;
  product_id?: null | number;
  quantity?: null | number | string;
  requested_name?: string;
  required_delivery_date?: null | string;
  specification?: null | string;
  technical_requirements?: null | string;
  unit_id?: null | number;
}

/** 报价明细的编辑行，含用于展示的只读字段 */
export interface QuoteItemRow {
  lead_days?: null | number;
  moq_quantity?: null | number | string;
  note?: null | string;
  payment_terms?: null | string;
  quoted_quantity?: null | number | string;
  requestedName: string;
  requestedQuantity: string;
  rfq_item_id?: null | number;
  supplier_model?: null | string;
  tax_rate?: null | number | string;
  tax_basis?: 'EXCLUDED' | 'INCLUDED' | null;
  unit_id?: null | number;
  unitName: string;
  unit_price?: null | number | string;
}
