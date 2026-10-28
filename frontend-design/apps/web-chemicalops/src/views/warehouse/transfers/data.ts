import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
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

/** 列表列定义 */
export function useColumns(
  onActionClick: OnActionClickFn<TransferRequestApi.TransferRequest>,
  currentUserId?: string | number,
): VxeTableGridColumns {
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
      cellRender: {
        attrs: { onClick: onActionClick },
        name: 'CellOperation',
        options: [
          { code: 'detail', text: '详情' },
          {
            code: 'edit', text: '编辑', auth: 'warehouse.inventory.transfer.write',
            show: (row: TransferRequestApi.TransferRequest) => ['DRAFT', 'REJECTED'].includes(row.status),
          },
          {
            code: 'submit', text: '提交', auth: 'warehouse.inventory.transfer.write',
            show: (row: TransferRequestApi.TransferRequest) => ['DRAFT', 'REJECTED'].includes(row.status),
          },
          {
            code: 'approve', text: '审批通过', auth: 'warehouse.inventory.transfer.approve',
            show: (row: TransferRequestApi.TransferRequest) => row.status === 'SUBMITTED' && String(row.applicant_id) !== String(currentUserId),
          },
          {
            code: 'reject', text: '驳回', auth: 'warehouse.inventory.transfer.approve', danger: true,
            show: (row: TransferRequestApi.TransferRequest) => row.status === 'SUBMITTED' && String(row.applicant_id) !== String(currentUserId),
          },
          {
            code: 'execute', text: '执行调拨', auth: 'warehouse.inventory.transfer.execute',
            show: (row: TransferRequestApi.TransferRequest) => row.status === 'APPROVED',
          },
          {
            code: 'cancel', text: '取消', auth: 'warehouse.inventory.transfer.write', danger: true,
            show: (row: TransferRequestApi.TransferRequest) => ['DRAFT', 'REJECTED'].includes(row.status),
          },
        ],
        props: {
          menuCodes: ['edit', 'submit', 'approve', 'reject', 'execute', 'cancel'],
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
