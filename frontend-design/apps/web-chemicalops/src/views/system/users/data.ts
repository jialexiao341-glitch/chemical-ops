import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { SystemUserApi } from '#/api';

import { getDepartmentListApi, getRoleListApi } from '#/api';
import { USER_STATUS_DICT } from '#/constants/dictionary';
import { formatDateTime } from '#/utils/format';

/** 新增用户表单 */
export function useCreateFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { maxlength: 64 },
      fieldName: 'username',
      label: '账号名',
      rules: 'required',
    },
    {
      component: 'VbenInputPassword',
      componentProps: { maxlength: 128, placeholder: '请输入初始密码' },
      fieldName: 'password',
      label: '初始密码',
      rules: 'required',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 64 },
      fieldName: 'display_name',
      label: '显示姓名',
      rules: 'required',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => {
          const res = await getDepartmentListApi({ page: 1, page_size: 100 });
          return res.items.map((item) => ({
            label: item.department_name,
            value: item.id,
          }));
        },
        class: 'w-full',
        placeholder: '请选择部门',
        showSearch: true,
      },
      fieldName: 'department_id',
      label: '所属部门',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        api: async () => {
          const res = await getRoleListApi({ page: 1, page_size: 100 });
          return res.items.map((item) => ({
            label: item.role_name,
            value: item.id,
          }));
        },
        class: 'w-full',
        mode: 'multiple',
        placeholder: '请选择角色',
        showSearch: true,
      },
      fieldName: 'role_ids',
      label: '角色',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 128 },
      fieldName: 'email',
      label: '邮箱',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 32 },
      fieldName: 'phone',
      label: '手机号',
    },
  ];
}

/** 编辑用户表单，账号名不可修改，密码留空表示不改 */
export function useUpdateFormSchema(isCurrentUser = false): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { disabled: true },
      fieldName: 'username',
      label: '账号名',
    },
    {
      component: 'VbenInputPassword',
      componentProps: { placeholder: '留空表示不修改密码' },
      fieldName: 'password',
      label: '重置密码',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 64 },
      fieldName: 'display_name',
      label: '显示姓名',
      rules: 'required',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => {
          const res = await getDepartmentListApi({ page: 1, page_size: 100 });
          return res.items.map((item) => ({
            label: item.department_name,
            value: item.id,
          }));
        },
        class: 'w-full',
        placeholder: '请选择部门',
        showSearch: true,
      },
      fieldName: 'department_id',
      label: '所属部门',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        api: async () => {
          const res = await getRoleListApi({ page: 1, page_size: 100 });
          return res.items.map((item) => ({
            label: item.role_name,
            value: item.id,
          }));
        },
        class: 'w-full',
        disabled: isCurrentUser,
        mode: 'multiple',
        placeholder: '请选择角色',
        showSearch: true,
      },
      fieldName: 'role_ids',
      label: '角色',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 128 },
      fieldName: 'email',
      label: '邮箱',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 32 },
      fieldName: 'phone',
      label: '手机号',
    },
    {
      component: 'Select',
      componentProps: {
        disabled: isCurrentUser,
        options: USER_STATUS_DICT.options().filter((item) => !['PENDING', 'REJECTED'].includes(item.value)),
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
      componentProps: { allowClear: true, placeholder: '请输入账号名或姓名' },
      fieldName: 'keyword',
      label: '关键字',
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: USER_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/** 列表列定义 */
export function useColumns(
  onActionClick: OnActionClickFn<SystemUserApi.SystemUser>,
  currentUserId: number,
  isAdmin = false,
): VxeTableGridColumns {
  return [
    { field: 'username', width: 160, title: '账号名' },
    { field: 'display_name', minWidth: 140, title: '显示姓名' },
    { field: 'role_names', minWidth: 170, title: '角色身份', formatter: ({ row }: { row: SystemUserApi.SystemUser }) => row.role_names?.join('、') || '未分配角色' },
    { field: 'email', minWidth: 180, title: '邮箱' },
    { field: 'phone', width: 140, title: '手机号' },
    {
      cellRender: {
        name: 'CellTag',
        options: USER_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 90,
    },
    {
      field: 'created_at',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatDateTime(cellValue),
      title: '创建时间',
      width: 170,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'display_name',
          nameTitle: '用户',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          { code: 'edit', auth: 'system.users.write', show: (row: SystemUserApi.SystemUser) => !['PENDING', 'REJECTED'].includes(row.status) },
          { code: 'review-registration', text: '审核注册', show: (row: SystemUserApi.SystemUser) => isAdmin && row.status === 'PENDING' },
          { code: 'department-scope', text: '部门授权', show: (row: SystemUserApi.SystemUser) => isAdmin && !row.role_codes?.includes('SYS_ADMIN') && !['PENDING', 'REJECTED'].includes(row.status) },
          {
            code: 'bind-supplier',
            auth: 'system.users.write',
            text: '绑定供应商',
            show: (row: SystemUserApi.SystemUser) => row.role_codes?.length === 1 && row.role_codes[0] === 'SUPPLIER_PORTAL',
            disabled: (row: SystemUserApi.SystemUser) => row.status !== 'ACTIVE',
          },
          {
            code: 'delete',
            auth: 'system.users.write',
            show: (row: SystemUserApi.SystemUser) => !['PENDING', 'REJECTED'].includes(row.status),
            disabled: (row: SystemUserApi.SystemUser) => row.id === currentUserId,
            text: (row: SystemUserApi.SystemUser) =>
              row.id === currentUserId ? '不能停用当前账号' : '停用',
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 250,
    },
  ];
}
