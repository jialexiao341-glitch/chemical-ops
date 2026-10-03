import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { ProductApi } from '#/api';

import { getChemicalListApi, getUnitListApi } from '#/api';
import { PRODUCT_STATUS_DICT } from '#/constants/dictionary';
import { trimDecimal } from '#/utils/format';

/** 新增/编辑产品表单 */
export function useFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { maxlength: 50 },
      fieldName: 'product_code',
      label: '产品编码',
      rules: 'required',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 100 },
      fieldName: 'product_name',
      label: '产品名称',
      rules: 'required',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => {
          const res = await getChemicalListApi({ page: 1, page_size: 100 });
          return res.items.map((item) => ({
            label: `${item.chemical_name}${item.cas_no ? ` (${item.cas_no})` : ''}`,
            value: item.id,
          }));
        },
        class: 'w-full',
        placeholder: '请选择化学品',
        showSearch: true,
      },
      fieldName: 'chemical_id',
      label: '所属化学品',
      rules: 'selectRequired',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 50 },
      fieldName: 'model',
      label: '规格型号',
    },
    {
      component: 'InputNumber',
      componentProps: { class: 'w-full', min: 0, precision: 6 },
      fieldName: 'purity_value',
      label: '纯度',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 20 },
      defaultValue: '%',
      fieldName: 'purity_unit',
      label: '纯度单位',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 100 },
      fieldName: 'packaging_spec',
      label: '包装规格',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => {
          const units = await getUnitListApi();
          return units.map((item) => ({
            label: `${item.unit_name} (${item.unit_code})`,
            value: item.id,
          }));
        },
        class: 'w-full',
        placeholder: '请选择计量单位',
        showSearch: true,
      },
      fieldName: 'unit_id',
      label: '计量单位',
      rules: 'selectRequired',
    },
    {
      component: 'InputNumber',
      componentProps: { class: 'w-full', min: 0, precision: 6, placeholder: '留空表示不监控低库存' },
      fieldName: 'safety_stock_quantity',
      label: '安全库存阈值（产品单位）',
    },
    {
      component: 'RadioGroup',
      componentProps: {
        buttonStyle: 'solid',
        options: PRODUCT_STATUS_DICT.options(),
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
        class: 'w-full',
        placeholder: '请输入产品编码或名称',
      },
      fieldName: 'keyword',
      label: '关键字',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => {
          const res = await getChemicalListApi({ page: 1, page_size: 100 });
          return res.items.map((item) => ({
            label: item.chemical_name,
            value: item.id,
          }));
        },
        class: 'w-full',
        placeholder: '全部化学品',
        showSearch: true,
      },
      fieldName: 'chemical_id',
      label: '化学品',
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        class: 'w-full',
        options: PRODUCT_STATUS_DICT.options(),
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
  onActionClick: OnActionClickFn<ProductApi.Product>,
  canManageProducts: boolean,
): VxeTableGridColumns {
  const columns: VxeTableGridColumns = [
    { field: 'product_code', width: 140, title: '产品编码' },
    { field: 'product_name', minWidth: 160, title: '产品名称' },
    { field: 'model', width: 140, title: '规格型号' },
    {
      field: 'purity_value',
      formatter: ({ cellValue }: { cellValue: any }) => trimDecimal(cellValue),
      title: '纯度',
      width: 90,
    },
    { field: 'packaging_spec', width: 140, title: '包装规格' },
    {
      field: 'safety_stock_quantity',
      formatter: ({ cellValue }: { cellValue: any }) =>
        cellValue == null ? '未设置' : trimDecimal(cellValue),
      title: '安全库存阈值',
      width: 130,
    },
    { field: 'version_no', title: '版本', width: 70 },
    {
      cellRender: {
        name: 'CellTag',
        options: PRODUCT_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 90,
    },
  ];

  if (canManageProducts) {
    columns.push({
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'product_name',
          nameTitle: '产品',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [{ code: 'standard', text: '检测标准' }, 'edit', 'delete'],
        props: { renderMode: 'menu' },
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 130,
    });
  }

  return columns;
}
