<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { InventoryApi } from '#/api';

import { onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getExpiryAlertsApi } from '#/api';
import { getProductNameMap, getWarehouseNameMap } from '#/utils/lookup';

import { useColumns } from './data';

defineOptions({ name: 'ExpiryAlert' });

const resolveProduct = ref<(id?: null | number) => string>(() => '-');
const resolveWarehouse = ref<(id?: null | number) => string>(() => '-');

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: [
      {
        component: 'Select',
        componentProps: {
          options: [
            { label: '30 天', value: 30 },
            { label: '60 天', value: 60 },
            { label: '90 天', value: 90 },
          ],
        },
        defaultValue: 30,
        fieldName: 'days',
        label: '预警窗口',
      },
    ],
  },
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
        query: async (_, formValues) => {
          // 同一批次可分布在不同仓库/库位，行标识必须包含库存位置。
          const items = (await getExpiryAlertsApi(Number(formValues.days ?? 30))).map((item) => ({
            ...item,
            row_key: `${item.batch_id}:${item.warehouse_id}:${item.location_id}`,
          }));
          return { items, total: items.length };
        },
      },
    },
    rowConfig: { keyField: 'row_key' },
    toolbarConfig: {
      custom: true,
      export: false,
      refresh: true,
      search: true,
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
    <Grid table-title="库存有效期预警" />
  </Page>
</template>
