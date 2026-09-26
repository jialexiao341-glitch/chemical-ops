import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { SystemDepartmentApi } from '#/api';

import { getDepartmentListApi } from '#/api';
import { ENABLE_STATUS_DICT } from '#/constants/dictionary';

/** 部门下拉选项，排除自身避免形成自引用 */
async function loadDepartmentOptions(excludeId?: number) {
  const res = await getDepartmentListApi({ page: 1, page_size: 100 });
  return res.items
    .filter((item) => item.id !== excludeId)
    .map((item) => ({
      label: `${item.department_name} (${item.department_code})`,
      value: item.id,
    }));
}

/** 新增部门表单 */
export function useCreateFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { maxlength: 64 },
      fieldName: 'department_code',
      label: '部门编码',
      rules: 'required',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 100 },
      fieldName: 'department_name',
      label: '部门名称',
      rules: 'required',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: () => loadDepartmentOptions(),
        class: 'w-full',
        placeholder: '不选则为顶级部门',
        showSearch: true,
      },
      fieldName: 'parent_id',
      label: '上级部门',
    },
    {
      component: 'InputNumber',
      componentProps: { class: 'w-full', min: 1 },
      fieldName: 'manager_id',
      label: '负责人用户 ID',
    },
  ];
}

/** 编辑部门表单，部门编码不可修改 */
export function useUpdateFormSchema(currentId: () => number | undefined) {
  return (): VbenFormSchema[] => [
    {
      component: 'Input',
      componentProps: { disabled: true },
      fieldName: 'department_code',
      label: '部门编码',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 100 },
      fieldName: 'department_name',
      label: '部门名称',
      rules: 'required',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: () => loadDepartmentOptions(currentId()),
        class: 'w-full',
        placeholder: '不选则为顶级部门',
        showSearch: true,
      },
      fieldName: 'parent_id',
      label: '上级部门',
    },
    {
      component: 'InputNumber',
      componentProps: { class: 'w-full', min: 1 },
      fieldName: 'manager_id',
      label: '负责人用户 ID',
    },
    {
      component: 'Select',
      componentProps: { options: ENABLE_STATUS_DICT.options() },
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
      componentProps: { allowClear: true, placeholder: '请输入部门编码或名称' },
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
  onActionClick: OnActionClickFn<SystemDepartmentApi.SystemDepartment>,
): VxeTableGridColumns {
  return [
    { field: 'department_code', width: 180, title: '部门编码' },
    { field: 'department_name', minWidth: 180, title: '部门名称' },
    {
      field: 'parent_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        cellValue ? String(cellValue) : '顶级部门',
      title: '上级部门 ID',
      width: 130,
    },
    {
      field: 'manager_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        cellValue ? String(cellValue) : '-',
      title: '负责人 ID',
      width: 110,
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
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'department_name',
          nameTitle: '部门',
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
