import { fetchAllPages } from '#/utils/pagination';
import type { VbenFormSchema } from '#/adapter/form';
import type { VxeTableGridColumns } from '#/adapter/vxe-table';
import type { InventoryApi } from '#/api';

import { getProductListApi } from '#/api';
import {
  INVENTORY_TRANSACTION_SOURCE_TYPE_DICT,
  INVENTORY_TRANSACTION_TYPE_DICT,
} from '#/constants/dictionary';
import { formatDateTime, formatQuantity } from '#/utils/format';

/** 列表筛选条件 */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => {
          const res = await fetchAllPages((page) => getProductListApi({ page, page_size: 100 }));
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
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: INVENTORY_TRANSACTION_TYPE_DICT.options(),
        placeholder: '全部类型',
      },
      fieldName: 'transaction_type',
      label: '流水类型',
    },
  ];
}

function formatTransactionType(row: InventoryApi.InventoryTransaction): string {
  if (
    row.source_type === 'TRANSFER_REQUEST' ||
    row.source_type === 'INVENTORY_TRANSFER'
  ) {
    if (
      row.transaction_type === 'INBOUND' ||
      row.transaction_type === 'TRANSFER_IN'
    ) {
      return '调拨入库';
    }
    if (
      row.transaction_type === 'OUTBOUND' ||
      row.transaction_type === 'TRANSFER_OUT'
    ) {
      return '调拨出库';
    }
  }
  return INVENTORY_TRANSACTION_TYPE_DICT.label(row.transaction_type);
}

/**
 * 列表列定义。
 *
 * 产品与仓库名称通过外部传入的解析函数翻译，避免表格里出现裸 ID。
 */
export function useColumns(
  resolveProduct: (id?: null | number) => string,
  resolveWarehouse: (id?: null | number) => string,
  resolveUnit: (id?: null | number) => string,
): VxeTableGridColumns {
  return [
    { field: 'transaction_no', minWidth: 190, title: '流水号' },
    {
      formatter: ({ row }: { row: InventoryApi.InventoryTransaction }) =>
        formatTransactionType(row),
      field: 'transaction_type',
      title: '类型',
      width: 110,
    },
    {
      field: 'product_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        resolveProduct(cellValue),
      minWidth: 160,
      title: '产品',
    },
    {
      field: 'warehouse_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        resolveWarehouse(cellValue),
      title: '仓库',
      width: 140,
    },
    {
      field: 'quantity',
      align: 'right',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatQuantity(cellValue),
      title: '数量',
      width: 120,
    },
    {
      field: 'unit_id',
      formatter: ({ cellValue }: { cellValue: any }) => resolveUnit(cellValue),
      title: '单位',
      width: 90,
    },
    {
      field: 'source_type',
      formatter: ({ cellValue }: { cellValue: any }) =>
        INVENTORY_TRANSACTION_SOURCE_TYPE_DICT.label(cellValue),
      title: '来源类型',
      width: 150,
    },
    {
      field: 'created_at',
      formatter: ({ cellValue }: { cellValue: any }) =>
        formatDateTime(cellValue),
      title: '发生时间',
      width: 170,
    },
  ];
}
