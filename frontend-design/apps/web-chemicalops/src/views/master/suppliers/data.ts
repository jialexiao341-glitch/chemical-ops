import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { SupplierApi } from '#/api';

import { SUPPLIER_STATUS_DICT } from '#/constants/dictionary';

/** 新增/编辑供应商表单 */
export function useFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { maxlength: 50 },
      fieldName: 'supplier_code',
      label: '供应商编码',
      rules: 'required',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 200 },
      fieldName: 'supplier_name',
      label: '供应商名称',
      rules: 'required',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 18 },
      fieldName: 'unified_credit_code',
      label: '统一社会信用代码',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 2 },
      defaultValue: 'CN',
      fieldName: 'country_code',
      label: '国家代码',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 50 },
      fieldName: 'region',
      label: '所在地区',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 200 },
      fieldName: 'cooperation_level',
      label: '合作等级',
    },
    {
      component: 'InputNumber',
      componentProps: { class: 'w-full', min: 0 },
      fieldName: 'default_lead_days',
      label: '默认交货天数',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 100 },
      fieldName: 'payment_terms',
      label: '付款条件',
    },
    {
      component: 'Textarea',
      componentProps: { maxlength: 500, rows: 2 },
      fieldName: 'address',
      label: '地址',
    },
    {
      component: 'Textarea',
      componentProps: { maxlength: 500, rows: 2 },
      fieldName: 'business_scope',
      label: '经营范围',
    },
    {
      component: 'Textarea',
      componentProps: { maxlength: 500, rows: 2 },
      fieldName: 'note',
      label: '备注',
    },
    {
      component: 'RadioGroup',
      componentProps: {
        buttonStyle: 'solid',
        options: SUPPLIER_STATUS_DICT.options(),
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
      componentProps: {
        allowClear: true,
        class: 'w-64',
        placeholder: '请输入供应商名称或编码',
      },
      fieldName: 'keyword',
      label: '关键字',
    },
    {
      component: 'Input',
      componentProps: {
        allowClear: true,
        class: 'w-72',
        placeholder: '请输入地区',
      },
      fieldName: 'region',
      label: '地区',
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        class: 'w-52',
        options: SUPPLIER_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/** 列表列定义 */
export function useColumns(
  onActionClick: OnActionClickFn<SupplierApi.Supplier>,
): VxeTableGridColumns {
  return [
    { field: 'supplier_code', width: 140, title: '供应商编码' },
    { field: 'supplier_name', minWidth: 200, title: '供应商名称' },
    { field: 'region', width: 120, title: '地区' },
    { field: 'cooperation_level', width: 110, title: '合作等级' },
    { field: 'payment_terms', width: 130, title: '付款条件' },
    {
      field: 'default_lead_days',
      title: '交货天数',
      width: 100,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: SUPPLIER_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'supplier_name',
          nameTitle: '供应商',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: ['edit', 'delete'],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 140,
    },
  ];
}
