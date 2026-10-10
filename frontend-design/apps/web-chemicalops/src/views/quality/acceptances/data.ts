import type { VbenFormSchema } from '#/adapter/form';
import type {
  OnActionClickFn,
  VxeTableGridColumns,
} from '#/adapter/vxe-table';
import type { QualityAcceptanceApi } from '#/api';

import { ACCEPTANCE_RESULT_DICT } from '#/constants/dictionary';
import { formatDateTime } from '#/utils/format';

/** 列表筛选条件 */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: ACCEPTANCE_RESULT_DICT.options(),
        placeholder: '全部结果',
      },
      fieldName: 'result',
      label: '验收结果',
    },
  ];
}

/** 列表列定义 */
export function useColumns(
  onActionClick: OnActionClickFn<QualityAcceptanceApi.Acceptance>,
): VxeTableGridColumns {
  return [
    { field: 'acceptance_no', minWidth: 190, title: '验收单号' },
    { field: 'delivery_id', title: '到货单 ID', width: 120 },
    {
      field: 'result',
      formatter: ({ cellValue }: { cellValue: any }) =>
        ACCEPTANCE_RESULT_DICT.label(cellValue),
      title: '验收结果',
      width: 110,
    },
    {
      field: 'certificate_complete',
      formatter: ({ cellValue }: { cellValue: any }) =>
        cellValue ? '齐全' : '不齐全',
      title: '单证',
      width: 100,
    },
    {
      field: 'inspection_time',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatDateTime(cellValue),
      title: '检验时间',
      width: 170,
    },
    { field: 'conclusion', minWidth: 200, title: '结论' },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'acceptance_no',
          nameTitle: '验收单',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'review',
            text: '核对报告',
            auth: 'quality.acceptances.read',
          },
          {
            code: 'result',
            text: '录入结果',
            auth: 'quality.acceptances.write',
            // PENDING（刚创建）和 REINSPECTION（复检中）可录入；
            // 已出最终结果（PASSED/PARTIAL/FAILED）的不允许直接改判
            disabled: (row: QualityAcceptanceApi.Acceptance) =>
              !!row.result && !['PENDING', 'REINSPECTION'].includes(row.result),
            title: (row: QualityAcceptanceApi.Acceptance) =>
              !!row.result && !['PENDING', 'REINSPECTION'].includes(row.result) ? '已完成验收，需先发起复检' : undefined,
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 210,
    },
  ];
}
