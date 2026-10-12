import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { StocktakeApi } from '#/api';

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
  resolveWarehouse: (id?: null | number) => string,
  onActionClick: OnActionClickFn<StocktakeApi.StocktakeRequest>,
  currentUserId?: string | number,
): VxeTableGridColumns {
  return [
    { field: 'stocktake_no', minWidth: 170, title: '盘点单号' },
    { field: 'purpose', minWidth: 200, title: '用途' },
    {
      field: 'warehouse_id',
      formatter: ({ cellValue }) => resolveWarehouse(cellValue),
      title: '仓库',
      width: 130,
    },
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
      formatter: ({ row }: { row: StocktakeApi.StocktakeRequest }) =>
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
            code: 'edit',
            text: '编辑',
            auth: 'warehouse.inventory.stocktake.write',
            show: (row: StocktakeApi.StocktakeRequest) =>
              ['DRAFT', 'REJECTED'].includes(row.status),
          },
          {
            code: 'submit',
            text: '提交',
            auth: 'warehouse.inventory.stocktake.write',
            show: (row: StocktakeApi.StocktakeRequest) =>
              ['DRAFT', 'REJECTED'].includes(row.status),
          },
          {
            code: 'approve',
            text: '审批通过',
            auth: 'warehouse.inventory.stocktake.approve',
            show: (row: StocktakeApi.StocktakeRequest) =>
              row.status === 'SUBMITTED' &&
              String(row.applicant_id) !== String(currentUserId),
          },
          {
            code: 'reject',
            text: '驳回',
            auth: 'warehouse.inventory.stocktake.approve',
            danger: true,
            show: (row: StocktakeApi.StocktakeRequest) =>
              row.status === 'SUBMITTED' &&
              String(row.applicant_id) !== String(currentUserId),
          },
          {
            code: 'execute',
            text: '执行盘点',
            auth: 'warehouse.inventory.stocktake.write',
            show: (row: StocktakeApi.StocktakeRequest) => row.status === 'APPROVED',
          },
          {
            code: 'cancel',
            text: '取消',
            auth: 'warehouse.inventory.stocktake.write',
            danger: true,
            show: (row: StocktakeApi.StocktakeRequest) =>
              ['DRAFT', 'REJECTED'].includes(row.status),
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
