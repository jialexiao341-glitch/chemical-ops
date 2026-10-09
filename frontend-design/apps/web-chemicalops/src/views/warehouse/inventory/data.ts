import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { InventoryApi } from '#/api';

import { getProductListApi, getWarehouseListApi } from '#/api';
import { INVENTORY_BALANCE_STATUS_DICT } from '#/constants/dictionary';
import { formatQuantity } from '#/utils/format';

/** 列表筛选条件 */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => {
          const res = await getProductListApi({ page: 1, page_size: 100 });
          return res.items.map((item) => ({
            label: item.product_name,
            value: item.id,
          }));
        },
        class: 'w-full',
        placeholder: '全部产品',
        showSearch: true,
      },
      fieldName: 'product_id',
      label: '产品',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => {
          const list = await getWarehouseListApi();
          return list.map((item) => ({
            label: item.warehouse_name,
            value: item.id,
          }));
        },
        class: 'w-full',
        placeholder: '全部仓库',
        showSearch: true,
      },
      fieldName: 'warehouse_id',
      label: '仓库',
    },
  ];
}

/**
 * 列表列定义。
 *
 * 可用量 = 库存数量 - 锁定量，让仓库人员直接看到可出库的数量。
 */
export function useColumns(
  onActionClick: OnActionClickFn<InventoryApi.InventoryBalance>,
  resolveProduct: (id?: null | number) => string,
  resolveWarehouse: (id?: null | number) => string,
  resolveUnit: (id?: null | number) => string,
): VxeTableGridColumns {
  return [
    {
      field: 'product_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        resolveProduct(cellValue),
      minWidth: 180,
      title: '产品',
    },
    {
      field: 'warehouse_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        resolveWarehouse(cellValue),
      title: '仓库',
      width: 140,
    },
    { field: 'batch_id', title: '批次 ID', width: 100 },
    {
      field: 'quantity',
      align: 'right',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatQuantity(cellValue),
      title: '库存数量',
      width: 120,
    },
    {
      field: 'locked_quantity',
      align: 'right',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatQuantity(cellValue),
      title: '锁定量',
      width: 110,
    },
    {
      align: 'right',
      field: 'available',
      formatter: ({ row }: { row: InventoryApi.InventoryBalance }) => {
        const total = Number(row.quantity ?? 0);
        const locked = Number(row.locked_quantity ?? 0);
        return formatQuantity(total - locked);
      },
      title: '可用量',
      width: 120,
    },
    {
      field: 'unit_id',
      formatter: ({ cellValue }: { cellValue: any }) => resolveUnit(cellValue),
      title: '单位',
      width: 90,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: INVENTORY_BALANCE_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 90,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'id',
          nameTitle: '库存批次',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        // 冻结与解冻共用一个入口，按当前状态在页面内分流
        options: [
          { code: 'return', text: '申请退货', auth: 'warehouse.inventory.return.write' },
          { code: 'batch-impact', text: '批次影响', auth: 'ai.workspace.read' },
          { code: 'replenishment', text: '消耗观察', auth: 'ai.workspace.read' },
          { code: 'location-advice', text: '库位提示', auth: 'ai.workspace.read' },
          {
            code: 'toggle-freeze',
            auth: 'warehouse.inventory.freeze.write',
            text: (row: InventoryApi.InventoryBalance) =>
              row.status === 'FROZEN' ? '解冻' : '冻结',
          },
          { code: 'logs', text: '变更记录' },
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
