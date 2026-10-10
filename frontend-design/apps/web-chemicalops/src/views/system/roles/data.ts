import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { SystemRoleApi } from '#/api';

import { getPermissionListApi } from '#/api';
import { ENABLE_STATUS_DICT } from '#/constants/dictionary';

/** 权限下拉选项，按资源前缀分组 */
async function loadPermissionOptions() {
  const res = await getPermissionListApi({ page: 1, page_size: 100 });
  return res.items.map((item) => ({
    label: `${item.permission_name} (${item.permission_code})`,
    value: item.id,
  }));
}

/** 新增角色表单 */
export function useCreateFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { maxlength: 64 },
      fieldName: 'role_code',
      label: '角色编码',
      rules: 'required',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 64 },
      fieldName: 'role_name',
      label: '角色名称',
      rules: 'required',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        api: loadPermissionOptions,
        class: 'w-full',
        mode: 'multiple',
        placeholder: '请选择权限',
        showSearch: true,
      },
      fieldName: 'permission_ids',
      label: '权限',
    },
    {
      component: 'Textarea',
      componentProps: { maxlength: 500, rows: 2 },
      fieldName: 'description',
      label: '描述',
    },
  ];
}

/** 编辑角色表单，角色编码不可修改，权限留空表示不调整 */
export function useUpdateFormSchema(isSystemAdmin = false): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { disabled: true },
      fieldName: 'role_code',
      label: '角色编码',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 64 },
      fieldName: 'role_name',
      label: '角色名称',
      rules: 'required',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        api: loadPermissionOptions,
        class: 'w-full',
        disabled: isSystemAdmin,
        mode: 'multiple',
        placeholder: '留空表示不调整权限',
        showSearch: true,
      },
      fieldName: 'permission_ids',
      label: '权限',
    },
    {
      component: 'Textarea',
      componentProps: { maxlength: 500, rows: 2 },
      fieldName: 'description',
      label: '描述',
    },
    {
      component: 'Select',
      componentProps: {
        disabled: isSystemAdmin,
        options: ENABLE_STATUS_DICT.options(),
      },
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
      componentProps: { allowClear: true, placeholder: '请输入角色编码或名称' },
      fieldName: 'keyword',
      label: '关键字',
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
  onActionClick: OnActionClickFn<SystemRoleApi.SystemRole>,
): VxeTableGridColumns {
  return [
    { field: 'role_code', width: 200, title: '角色编码' },
    { field: 'role_name', minWidth: 160, title: '角色名称' },
    { field: 'description', minWidth: 200, title: '描述' },
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
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'role_name',
          nameTitle: '角色',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          { code: 'edit', auth: 'system.roles.write' },
          {
            code: 'delete',
            auth: 'system.roles.write',
            show: (row: SystemRoleApi.SystemRole) => row.role_code !== 'SYS_ADMIN',
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 140,
    },
  ];
}
