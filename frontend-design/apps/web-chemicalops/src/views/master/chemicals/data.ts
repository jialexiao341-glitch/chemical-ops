import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { ChemicalApi } from '#/api';

import { ENABLE_STATUS_DICT } from '#/constants/dictionary';
import { formatDateTime, trimDecimal } from '#/utils/format';

/** 新增/编辑化学品表单 */
export function useFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { maxlength: 100 },
      fieldName: 'chemical_name',
      label: '化学品名称',
      rules: 'required',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 100 },
      fieldName: 'english_name',
      label: '英文名称',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 50 },
      fieldName: 'cas_no',
      label: 'CAS 号',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 100 },
      fieldName: 'chemical_formula',
      label: '分子式',
    },
    {
      component: 'InputNumber',
      componentProps: { class: 'w-full', min: 0, precision: 6 },
      fieldName: 'molecular_weight',
      label: '分子量',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 50 },
      fieldName: 'hazard_class',
      label: '危险类别',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 200 },
      fieldName: 'alias_text',
      label: '别名',
    },
    {
      component: 'Textarea',
      componentProps: { maxlength: 500, rows: 3 },
      fieldName: 'source_text',
      label: '资料来源',
    },
    {
      component: 'RadioGroup',
      componentProps: {
        buttonStyle: 'solid',
        options: ENABLE_STATUS_DICT.options(),
        optionType: 'button',
      },
      defaultValue: 'ACTIVE',
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/** 列表筛选条件 */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { allowClear: true, placeholder: '请输入化学品名称' },
      fieldName: 'keyword',
      label: '化学品名称',
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: ENABLE_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      defaultValue: 'ACTIVE',
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/** 列表列定义 */
export function useColumns(
  onActionClick: OnActionClickFn<ChemicalApi.Chemical>,
  canViewMsdsImpact: boolean,
): VxeTableGridColumns {
  return [
    {
      field: 'chemical_name',
      minWidth: 160,
      title: '化学品名称',
    },
    {
      field: 'english_name',
      minWidth: 140,
      title: '英文名称',
    },
    {
      field: 'cas_no',
      width: 120,
      title: 'CAS 号',
    },
    {
      field: 'chemical_formula',
      width: 120,
      title: '分子式',
    },
    {
      field: 'molecular_weight',
      align: 'right',
      // 后端 DECIMAL(18,6) 会返回 106.160000，这里去掉无意义的末尾 0
      formatter: ({ cellValue }: { cellValue: any }) => trimDecimal(cellValue),
      width: 110,
      title: '分子量',
    },
    {
      field: 'hazard_class',
      width: 120,
      title: '危险类别',
    },
    {
      cellRender: {
        name: 'CellTag',
        options: ENABLE_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 90,
    },
    {
      field: 'updated_at',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatDateTime(cellValue),
      title: '更新时间',
      width: 180,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'chemical_name',
          nameTitle: '化学品',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'msds-change',
            text: 'MSDS版本核对',
            show: () => canViewMsdsImpact,
          },
          'edit',
          'delete',
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
