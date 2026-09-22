import type { VbenFormSchema } from '#/adapter/form';
import type { VxeTableGridColumns } from '#/adapter/vxe-table';
import type { OperationExceptionApi } from '#/api';

import {
  EXCEPTION_SEVERITY_DICT,
  EXCEPTION_STATUS_DICT,
  EXCEPTION_TYPE_DICT,
} from '#/constants/dictionary';
import { formatDateTime } from '#/utils/format';

/** 列表筛选条件（后端只支持类型与状态） */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: EXCEPTION_TYPE_DICT.options(),
        placeholder: '全部类型',
      },
      fieldName: 'exception_type',
      label: '异常类型',
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: EXCEPTION_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/** 列表列定义 */
export function useColumns(
  resolveOwner: (id?: null | number) => string,
): VxeTableGridColumns {
  return [
    { field: 'exception_no', minWidth: 170, title: '异常编号' },
    {
      cellRender: {
        name: 'CellTag',
        options: EXCEPTION_TYPE_DICT.items,
      },
      field: 'exception_type',
      title: '类型',
      width: 100,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: EXCEPTION_SEVERITY_DICT.items,
      },
      field: 'severity',
      title: '严重级别',
      width: 100,
    },
    { field: 'description', minWidth: 240, title: '描述' },
    {
      field: 'owner_id',
      formatter: ({ cellValue }) => resolveOwner(cellValue),
      title: '负责人',
      width: 120,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: EXCEPTION_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    {
      formatter: ({ cellValue }: { cellValue?: null | string }) =>
        formatDateTime(cellValue),
      field: 'due_at',
      title: '截止时间',
      width: 160,
    },
    {
      formatter: ({ cellValue }: { cellValue?: null | string }) =>
        formatDateTime(cellValue),
      field: 'created_at',
      title: '登记时间',
      width: 160,
    },
    {
      align: 'center',
      field: 'operation',
      fixed: 'right',
      slots: { default: 'operation' },
      title: '操作',
      width: 90,
    },
  ];
}

/** 详情抽屉可复用的行类型别名 */
export type ExceptionRow = OperationExceptionApi.Exception;
