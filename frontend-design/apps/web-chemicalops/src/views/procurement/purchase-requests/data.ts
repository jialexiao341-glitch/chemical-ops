import type { VbenFormSchema } from '#/adapter/form';
import type {
  OnActionClickFn,
  VxeTableGridColumns,
} from '#/adapter/vxe-table';
import type { PurchaseRequestApi } from '#/api';

import {
  PRIORITY_DICT,
  PURCHASE_REQUEST_STATUS_DICT,
} from '#/constants/dictionary';
import { formatAmount, formatDate } from '#/utils/format';

/** 列表筛选条件 */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: {
        allowClear: true,
        placeholder: '请输入申请编号或用途',
      },
      fieldName: 'keyword',
      label: '关键字',
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: PURCHASE_REQUEST_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/** 列表列定义 */
export function useColumns(
  onActionClick: OnActionClickFn<PurchaseRequestApi.PurchaseRequest>,
): VxeTableGridColumns {
  return [
    { field: 'request_no', minWidth: 180, title: '申请编号' },
    { field: 'purpose', minWidth: 200, title: '用途' },
    {
      cellRender: {
        name: 'CellTag',
        options: PRIORITY_DICT.items,
      },
      field: 'priority',
      title: '优先级',
      width: 90,
    },
    {
      field: 'budget_amount',
      align: 'right',
      formatter: ({ cellValue, row }: { cellValue: any; row: any }) =>
        cellValue ? `${formatAmount(cellValue)} ${row.currency_code ?? ''}` : '-',
      title: '预算金额',
      width: 150,
    },
    {
      field: 'expected_date',
      formatter: ({ cellValue }: { cellValue: any }) => formatDate(cellValue),
      title: '期望到货',
      width: 120,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: PURCHASE_REQUEST_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'request_no',
          nameTitle: '采购申请',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'edit',
            text: '编辑',
            auth: 'procurement.requests.write',
            show: (row: PurchaseRequestApi.PurchaseRequest) =>
              row.status === 'DRAFT' || row.status === 'REJECTED',
          },
          {
            code: 'detail',
            text: '详情',
          },
          {
            code: 'submit',
            text: '提交',
            auth: 'procurement.requests.write',
            show: (row: PurchaseRequestApi.PurchaseRequest) =>
              row.status === 'DRAFT' || row.status === 'REJECTED',
          },
          {
            code: 'approve',
            text: '审批通过',
            auth: 'procurement.requests.approve',
            show: (row: PurchaseRequestApi.PurchaseRequest) =>
              row.status === 'SUBMITTED' || row.status === 'APPROVING',
          },
          {
            code: 'reject',
            text: '驳回',
            auth: 'procurement.requests.approve',
            show: (row: PurchaseRequestApi.PurchaseRequest) =>
              row.status === 'SUBMITTED' || row.status === 'APPROVING',
          },
          {
            code: 'cancel',
            text: '取消',
            auth: 'procurement.requests.write',
            show: (row: PurchaseRequestApi.PurchaseRequest) =>
              !['APPROVED', 'CANCELLED'].includes(row.status),
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

/** 采购申请明细的可编辑行 */
export interface RequestItemRow {
  budget_price?: null | number | string;
  expected_date?: null | string;
  product_id?: null | number;
  quantity?: null | number | string;
  requested_name?: string;
  technical_requirements?: null | string;
  unit_id?: null | number;
}
