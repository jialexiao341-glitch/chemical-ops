<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { InventoryApi } from '#/api';

import { onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { Page, useVbenDrawer, useVbenModal } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getBalanceListApi } from '#/api';
import { applyAiFiltersToList } from '#/utils/ai-list-filters';
import {
  getProductNameMap,
  getUnitNameMap,
  getWarehouseNameMap,
} from '#/utils/lookup';

import { useColumns, useGridFormSchema } from './data';
import FreezeModal from './modules/freeze.vue';
import InboundModal from './modules/inbound.vue';
import LogsDrawer from './modules/logs.vue';

defineOptions({ name: 'InventoryList' });
const route = useRoute();

function getAiInventoryFilters() {
  const raw = route.query.ai_filters;
  if (typeof raw !== 'string') return {};
  try {
    const payload = JSON.parse(raw);
    if (payload.dataset !== 'inventory') return {};
    const filters = payload.filters ?? {};
    const positiveId = (value: unknown) => {
      const id = Number(value);
      return Number.isInteger(id) && id > 0 ? id : undefined;
    };
    return {
      batch_id: positiveId(filters.batch_id),
      product_id: positiveId(filters.product_id),
      warehouse_id: positiveId(filters.warehouse_id),
    };
  } catch {
    return {};
  }
}

const [Freeze, freezeApi] = useVbenModal({
  connectedComponent: FreezeModal,
  destroyOnClose: true,
});

const [Inbound, inboundApi] = useVbenModal({
  connectedComponent: InboundModal,
  destroyOnClose: true,
});

const [Logs, logsApi] = useVbenDrawer({
  connectedComponent: LogsDrawer,
  destroyOnClose: true,
});

const resolveProduct = ref<(id?: null | number) => string>(() => '-');
const resolveWarehouse = ref<(id?: null | number) => string>(() => '-');
const resolveUnit = ref<(id?: null | number) => string>(() => '-');

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns(
      onActionClick,
      (id) => resolveProduct.value(id),
      (id) => resolveWarehouse.value(id),
      (id) => resolveUnit.value(id),
    ),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getBalanceListApi({
            page: page.currentPage,
            page_size: page.pageSize,
            batch_id: getAiInventoryFilters().batch_id,
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
  } as VxeTableGridOptions<InventoryApi.InventoryBalance>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<InventoryApi.InventoryBalance>) {
  switch (code) {
    case 'logs': {
      logsApi.setData(row.id).open();
      break;
    }
    case 'toggle-freeze': {
      freezeApi
        .setData({
          action: row.status === 'FROZEN' ? 'unfreeze' : 'freeze',
          balance: row,
          productName: resolveProduct.value(row.product_id),
        })
        .open();
      break;
    }
  }
}

function buildResolver(map: Map<number, string>) {
  return (id?: null | number) => {
    if (!id) {
      return '-';
    }
    return map.get(id) ?? `#${id}`;
  };
}

function onRefresh() {
  gridApi.query();
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
  await applyAiFiltersToList('inventory', route.query.ai_filters, gridApi.formApi);
  const sourceFilters = getAiInventoryFilters();
  await gridApi.formApi.setValues({
    ...(sourceFilters.product_id ? { product_id: sourceFilters.product_id } : {}),
    ...(sourceFilters.warehouse_id ? { warehouse_id: sourceFilters.warehouse_id } : {}),
  });
  gridApi.query();
});

watch(
  () => route.query.ai_filters,
  async (rawQuery) => {
    if (await applyAiFiltersToList('inventory', rawQuery, gridApi.formApi)) {
      const sourceFilters = getAiInventoryFilters();
      await gridApi.formApi.setValues({
        ...(sourceFilters.product_id ? { product_id: sourceFilters.product_id } : {}),
        ...(sourceFilters.warehouse_id ? { warehouse_id: sourceFilters.warehouse_id } : {}),
      });
      gridApi.query();
    }
  },
);
</script>

<template>
  <Page auto-content-height>
    <Freeze @success="onRefresh" />
    <Inbound @success="onRefresh" />
    <Logs />
    <Grid table-title="库存余额">
      <template #toolbar-tools>
        <Button type="primary" @click="inboundApi.open()">
          <Plus class="size-5" />
          库存入库
        </Button>
      </template>
    </Grid>
  </Page>
</template>
