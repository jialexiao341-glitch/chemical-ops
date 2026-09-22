import type { VbenFormSchema } from '#/adapter/form';
import type { VxeTableGridColumns } from '#/adapter/vxe-table';
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

/** 列表列定义（操作按钮在 index.vue 的 operation 插槽里按状态渲染） */
export function useColumns(
  resolveWarehouse: (id?: null | number) => string,
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
      field: 'operation',
      fixed: 'right',
      slots: { default: 'operation' },
      title: '操作',
      width: 260,
    },
  ];
}
