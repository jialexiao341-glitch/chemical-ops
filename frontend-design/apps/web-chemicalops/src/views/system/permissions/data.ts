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

const RESOURCE_LABELS: Record<string, string> = {
  'ai.workspace': '人工智能工作台',
  dashboard: '运营仪表盘',
  'finance.invoices': '供应商发票',
  'finance.payments': '付款管理',
  'finance.reconciliations': '财务对账',
  'finance.settlements': '采购结算',
  'master.chemicals': '化学品',
  'master.products': '产品',
  'master.suppliers': '供应商',
  'operations.exceptions': '运营异常',
  'procurement.orders': '采购订单',
  'procurement.requests': '采购申请',
  'procurement.rfqs': '采购询价',
  'quality.acceptances': '质量验收',
  'supplier.portal': '供应商门户',
  'supplier.portal.delivery': '供应商交期更新',
  'supplier.portal.quality': '供应商质量资料',
  'supplier.portal.reconciliation': '供应商对账',
  'supplier.portal.rfq': '供应商询价',
  'supplier.portal.shipment': '供应商发货通知',
  'system.files': '文件管理',
  'system.departments': '部门管理',
  'system.notifications': '站内通知',
  'system.permissions': '权限管理',
  'system.roles': '角色管理',
  'system.users': '用户管理',
  'warehouse.deliveries': '到货管理',
  'warehouse.inventory': '库存管理',
  'warehouse.inventory.balances': '库存余额',
  'warehouse.inventory.cost': '库存成本',
  'warehouse.inventory.expiry': '库存有效期预警',
  'warehouse.inventory.freeze': '库存冻结',
  'warehouse.inventory.issue': '库存领用',
  'warehouse.inventory.issues': '库存领用',
  'warehouse.inventory.return': '供应商退货',
  'warehouse.inventory.stocktake': '库存盘点',
  'warehouse.inventory.stocktakes': '库存盘点',
  'warehouse.inventory.transactions': '库存流水',
  'warehouse.inventory.transfer': '库存调拨',
  'warehouse.inventory.transfers': '库存调拨',
  'procurement.replenishment': '供应商补货',
};

const ACTION_LABELS: Record<string, string> = {
  approve: '审批',
  award: '定标',
  assign: '指派',
  attach: '关联',
  cancel: '取消',
  compare: '比较',
  confirm: '确认',
  delete: '删除',
  deactivate: '停用',
  download: '下载',
  export: '导出',
  execute: '执行',
  freeze: '冻结',
  import: '导入',
  manage: '管理',
  message: '留言',
  quote: '报价',
  read: '读取',
  respond: '响应',
  review: '复核',
  submit: '提交',
  update: '更新',
  void: '作废',
  write: '写入',
};

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
    {
      field: 'resource',
      formatter: ({ cellValue }: { cellValue: string }) =>
        RESOURCE_LABELS[cellValue] ?? cellValue,
      minWidth: 180,
      title: '资源',
    },
    {
      field: 'action',
      formatter: ({ cellValue }: { cellValue: string }) =>
        ACTION_LABELS[cellValue] ?? cellValue,
      title: '操作类型',
      width: 100,
    },
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
