import type { VbenFormSchema } from '#/adapter/form';
import type { VxeTableGridColumns } from '#/adapter/vxe-table';
import type { TransferRequestApi } from '#/api';

import { APPROVAL_FLOW_STATUS_DICT } from '#/constants/dictionary';
import { formatDateTime } from '#/utils/format';

/** 列表筛选条件 */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: APPROVAL_FLOW_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/** 列表列定义（操作按钮在 index.vue 的 operation 插槽里按状态渲染） */
export function useColumns(): VxeTableGridColumns {
  return [
    { field: 'transfer_no', minWidth: 170, title: '调拨单号' },
    { field: 'purpose', minWidth: 220, title: '用途' },
    {
      cellRender: {
        name: 'CellTag',
        options: APPROVAL_FLOW_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    {
      field: 'applicant_id',
      title: '申请人',
      width: 90,
    },
    {
      formatter: ({ row }: { row: TransferRequestApi.TransferRequest }) =>
        String(row.items?.length ?? 0),
      title: '明细数',
      width: 80,
    },
    {
      formatter: ({ cellValue }: { cellValue?: null | string }) =>
        formatDateTime(cellValue),
      field: 'created_at',
      title: '创建时间',
      width: 160,
    },
    {
      align: 'center',
      field: 'operation',
      fixed: 'right',
      slots: { default: 'operation' },
      title: '操作',
      width: 260,
    },
  ];
}
