import type { VbenFormSchema } from '#/adapter/form';
import type {
  OnActionClickFn,
  VxeTableGridColumns,
} from '#/adapter/vxe-table';
import type { ReplenishmentApi } from '#/api';

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

/** 列表列定义；供应商名称由后端按当前权限补齐。 */
export function useColumns(
  onActionClick: OnActionClickFn<ReplenishmentApi.Replenishment>,
): VxeTableGridColumns {
  return [
    {
      field: 'replenishment_no',
      minWidth: 200,
      title: '补货单号',
    },
    {
      field: 'supplier_name',
      formatter: ({ row }: { row: ReplenishmentApi.Replenishment }) =>
        row.supplier_name || row.supplier_code || `#${row.supplier_id}`,
      minWidth: 200,
      title: '供应商',
    },
    {
      field: 'reason',
      minWidth: 260,
      showOverflow: 'tooltip',
      title: '补货原因',
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
      field: 'created_at',
      formatter: ({ cellValue }: { cellValue: any }) => formatDateTime(cellValue),
      title: '创建时间',
      width: 170,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'replenishment_no',
          nameTitle: '补货申请',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [{ code: 'detail', text: '详情' }],
      },
      field: 'operation',
      fixed: 'right',
      width: 100,
      title: '操作',
    },
  ];
}
