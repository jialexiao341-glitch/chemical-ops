<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { InventoryApi } from '#/api';

import { onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Segmented } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getExpiryAlertsApi } from '#/api';
import { getProductNameMap, getWarehouseNameMap } from '#/utils/lookup';

import { useColumns } from './data';

defineOptions({ name: 'ExpiryAlert' });

/** 查询窗口，单位天 */
const windowDays = ref(30);

const resolveProduct = ref<(id?: null | number) => string>(() => '-');
const resolveWarehouse = ref<(id?: null | number) => string>(() => '-');

const [Grid, gridApi] = useVbenVxeGrid({
  gridOptions: {
    columns: useColumns(
      (id) => resolveProduct.value(id),
      (id) => resolveWarehouse.value(id),
    ),
    height: 'auto',
    keepSource: true,
    pagerConfig: { enabled: false },
    proxyConfig: {
      ajax: {
        // 该接口一次性返回全部预警批次，不分页
        query: async () => {
          const items = await getExpiryAlertsApi(windowDays.value);
          return { items, total: items.length };
        },
      },
    },
    rowConfig: { keyField: 'batch_id' },
    toolbarConfig: {
      custom: true,
      export: false,
      refresh: true,
      search: false,
      zoom: true,
    },
  } as VxeTableGridOptions<InventoryApi.ExpiryAlert>,
});

function buildResolver(map: Map<number, string>) {
  return (id?: null | number) => {
    if (!id) {
      return '-';
    }
    return map.get(id) ?? `#${id}`;
  };
}

function onWindowChange(value: number | string) {
  windowDays.value = Number(value);
  gridApi.query();
}

onMounted(async () => {
  const [products, warehouses] = await Promise.all([
    getProductNameMap(),
    getWarehouseNameMap(),
  ]);
  resolveProduct.value = buildResolver(products);
  resolveWarehouse.value = buildResolver(warehouses);
  gridApi.query();
});
</script>

<template>
  <Page auto-content-height>
    <Grid table-title="库存有效期预警">
      <template #toolbar-actions>
        <div class="flex items-center gap-3">
          <span class="text-muted-foreground text-sm">预警窗口</span>
          <Segmented
            :options="[
              { label: '30 天', value: 30 },
              { label: '60 天', value: 60 },
              { label: '90 天', value: 90 },
            ]"
            :value="windowDays"
            @change="onWindowChange"
          />
        </div>
      </template>
    </Grid>
  </Page>
</template>
