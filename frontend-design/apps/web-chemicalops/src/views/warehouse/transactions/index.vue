<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { InventoryApi } from '#/api';

import { onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getTransactionListApi } from '#/api';
import {
  getProductNameMap,
  getUnitNameMap,
  getWarehouseNameMap,
} from '#/utils/lookup';

import { useColumns, useGridFormSchema } from './data';

defineOptions({ name: 'InventoryTransaction' });

/** 名称解析函数，主数据加载完成后替换 */
const resolveProduct = ref<(id?: null | number) => string>(() => '-');
const resolveWarehouse = ref<(id?: null | number) => string>(() => '-');
const resolveUnit = ref<(id?: null | number) => string>(() => '-');

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns(
      (id) => resolveProduct.value(id),
      (id) => resolveWarehouse.value(id),
      (id) => resolveUnit.value(id),
    ),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getTransactionListApi({
            page: page.currentPage,
            page_size: page.pageSize,
            ...formValues,
          });
        },
      },
    },
    rowConfig: { keyField: 'id' },
    toolbarConfig: {
      custom: true,
      export: false,
      refresh: true,
      search: true,
      zoom: true,
    },
  } as VxeTableGridOptions<InventoryApi.InventoryTransaction>,
});

/** 主数据加载完成后刷新表格，让 ID 列显示为名称 */
function buildResolver(map: Map<number, string>) {
  return (id?: null | number) => {
    if (!id) {
      return '-';
    }
    return map.get(id) ?? `#${id}`;
  };
}

onMounted(async () => {
  const [products, warehouses, units] = await Promise.all([
    getProductNameMap(),
    getWarehouseNameMap(),
    getUnitNameMap(),
  ]);
  resolveProduct.value = buildResolver(products);
  resolveWarehouse.value = buildResolver(warehouses);
  resolveUnit.value = buildResolver(units);
  gridApi.query();
});
</script>

<template>
  <Page auto-content-height>
    <Grid table-title="库存流水" />
  </Page>
</template>
