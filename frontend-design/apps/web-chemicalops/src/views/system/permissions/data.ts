import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { SystemPermissionApi } from '#/api';

import { formatDateTime } from '#/utils/format';

/** 权限类型选项，与后端 permission_type 取值保持一致 */
export const PERMISSION_TYPE_OPTIONS = [
  { label: '菜单', value: 'MENU' },
  { label: '按钮', value: 'BUTTON' },
  { label: '接口', value: 'API' },
  { label: '数据', value: 'DATA' },
];

/** 新增/编辑权限表单 */
export function useFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { maxlength: 100 },
      fieldName: 'permission_code',
      label: '权限编码',
      rules: 'required',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 100 },
      fieldName: 'permission_name',
      label: '权限名称',
      rules: 'required',
    },
    {
      component: 'Select',
      componentProps: {
        options: PERMISSION_TYPE_OPTIONS,
        placeholder: '请选择权限类型',
      },
      fieldName: 'permission_type',
      label: '权限类型',
      rules: 'selectRequired',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 64, placeholder: '例如 procurement.orders' },
      fieldName: 'resource',
      label: '资源',
      rules: 'required',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 32, placeholder: '例如 read / write' },
      fieldName: 'action',
      label: '动作',
      rules: 'required',
    },
    {
      component: 'Textarea',
      componentProps: { maxlength: 500, rows: 2 },
      fieldName: 'description',
      label: '描述',
    },
  ];
}

/** 列表筛选条件 */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { allowClear: true, placeholder: '请输入权限编码或名称' },
      fieldName: 'keyword',
      label: '关键字',
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: PERMISSION_TYPE_OPTIONS,
        placeholder: '全部类型',
      },
      fieldName: 'permission_type',
      label: '权限类型',
    },
  ];
}

/** 列表列定义 */
export function useColumns(
  onActionClick: OnActionClickFn<SystemPermissionApi.SystemPermission>,
): VxeTableGridColumns {
  return [
    { field: 'permission_code', minWidth: 240, title: '权限编码' },
    { field: 'permission_name', minWidth: 160, title: '权限名称' },
    {
      cellRender: {
        name: 'CellTag',
        options: PERMISSION_TYPE_OPTIONS,
      },
      field: 'permission_type',
      title: '类型',
      width: 90,
    },
    { field: 'resource', minWidth: 180, title: '资源' },
    { field: 'action', width: 100, title: '动作' },
    {
      field: 'updated_at',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatDateTime(cellValue),
      title: '更新时间',
      width: 170,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'permission_name',
          nameTitle: '权限',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          { code: 'edit', auth: 'system.permissions.write' },
          { code: 'delete', auth: 'system.permissions.write' },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 140,
    },
  ];
}
