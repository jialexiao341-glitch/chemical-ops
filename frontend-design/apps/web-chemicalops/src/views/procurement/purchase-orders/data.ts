import type { VbenFormSchema } from '#/adapter/form';
import type {
  OnActionClickFn,
  VxeTableGridColumns,
} from '#/adapter/vxe-table';
import type { PurchaseOrderApi } from '#/api';

import { PURCHASE_ORDER_STATUS_DICT } from '#/constants/dictionary';
import { formatAmount, formatDate } from '#/utils/format';

/** 列表筛选条件 */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { allowClear: true, placeholder: '请输入订单编号' },
      fieldName: 'keyword',
      label: '订单编号',
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: PURCHASE_ORDER_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/**
 * 列表列定义。
 *
 * 操作项按订单状态显隐，避免出现点了必然失败的按钮。
 */
export function useColumns(
  onActionClick: OnActionClickFn<PurchaseOrderApi.PurchaseOrder>,
  resolveSupplier: (id?: null | number) => string,
): VxeTableGridColumns {
  return [
    {
      field: 'po_no',
      minWidth: 180,
      slots: { default: 'po_no' },
      title: '订单编号',
    },
    {
      field: 'supplier_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        resolveSupplier(cellValue),
      minWidth: 180,
      title: '供应商',
    },
    {
      field: 'order_amount',
      align: 'right',
      formatter: ({ cellValue, row }: { cellValue: any; row: any }) =>
        `${formatAmount(cellValue)} ${row.currency_code ?? ''}`,
      title: '订单金额',
      width: 160,
    },
    {
      field: 'expected_arrival_date',
      formatter: ({ cellValue }: { cellValue: any }) => formatDate(cellValue),
      title: '期望到货',
      width: 120,
    },
    {
      field: 'order_date',
      formatter: ({ cellValue }: { cellValue: any }) => formatDate(cellValue),
      title: '下单日期',
      width: 120,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: PURCHASE_ORDER_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'po_no',
          nameTitle: '采购订单',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'edit',
            text: '编辑',
            auth: 'procurement.orders.write',
            show: (row: PurchaseOrderApi.PurchaseOrder) =>
              row.status === 'DRAFT',
          },
          { code: 'detail', text: '详情' },
          {
            code: 'submit',
            text: '提交审批',
            auth: 'procurement.orders.write',
            show: (row: PurchaseOrderApi.PurchaseOrder) =>
              row.status === 'DRAFT',
          },
          {
            code: 'approve',
            text: '审批通过',
            auth: 'procurement.orders.approve',
            show: (row: PurchaseOrderApi.PurchaseOrder) =>
              row.status === 'APPROVING',
          },
          {
            code: 'reject',
            text: '驳回',
            auth: 'procurement.orders.approve',
            show: (row: PurchaseOrderApi.PurchaseOrder) =>
              row.status === 'APPROVING',
          },
          {
            code: 'place',
            text: '正式下单',
            auth: 'procurement.orders.write',
            show: (row: PurchaseOrderApi.PurchaseOrder) =>
              row.status === 'APPROVED',
          },
          {
            code: 'cancel',
            text: '取消',
            auth: 'procurement.orders.write',
            show: (row: PurchaseOrderApi.PurchaseOrder) =>
              ['APPROVED', 'APPROVING', 'DRAFT'].includes(row.status),
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
