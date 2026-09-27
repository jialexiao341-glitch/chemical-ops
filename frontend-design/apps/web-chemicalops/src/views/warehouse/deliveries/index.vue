<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { DeliveryApi } from '#/api';

import { onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { Page, useVbenDrawer, useVbenModal } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getDeliveryListApi } from '#/api';
import { getSupplierNameMap } from '#/utils/lookup';
import { applyAiFiltersToList } from '#/utils/ai-list-filters';

import { useColumns, useGridFormSchema } from './data';
import CreateModal from './modules/create.vue';
import DetailDrawer from './modules/detail.vue';
import ReceiveModal from './modules/receive.vue';

defineOptions({ name: 'DeliveryList' });
const route = useRoute();

const [Create, createApi] = useVbenModal({
  connectedComponent: CreateModal,
  destroyOnClose: true,
});

const [Receive, receiveApi] = useVbenModal({
  connectedComponent: ReceiveModal,
  destroyOnClose: true,
});

const [Detail, detailApi] = useVbenDrawer({
  connectedComponent: DetailDrawer,
  destroyOnClose: true,
});

const resolveSupplier = ref<(id?: null | number) => string>(() => '-');

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns(onActionClick, (id) => resolveSupplier.value(id)),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getDeliveryListApi({
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
  } as VxeTableGridOptions<DeliveryApi.Delivery>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<DeliveryApi.Delivery>) {
  if (code === 'receive') {
    receiveApi.setData(row).open();
  }
}

onMounted(async () => {
  const suppliers = await getSupplierNameMap();
  resolveSupplier.value = (id) => {
    if (!id) {
      return '-';
    }
    return suppliers.get(id) ?? `#${id}`;
  };
  await applyAiFiltersToList(
    'deliveries',
    route.query.ai_filters,
    gridApi.formApi,
  );
  gridApi.query();
  openAiRecord(route.query.ai_record_id);
});

function openAiRecord(rawId: unknown) {
  const id = Number(rawId);
  if (!Number.isInteger(id) || id <= 0) return;
  detailApi.setData({ id } as DeliveryApi.Delivery).open();
}

watch(
  () => route.query.ai_filters,
  async (rawQuery) => {
    if (await applyAiFiltersToList('deliveries', rawQuery, gridApi.formApi)) {
      gridApi.query();
    }
  },
);

watch(
  () => route.query.ai_record_id,
  (rawId) => openAiRecord(rawId),
);
</script>

<template>
  <Page auto-content-height>
    <Create @success="gridApi.query()" />
    <Detail />
    <Receive @success="gridApi.query()" />
    <Grid table-title="到货与收货">
      <template #toolbar-tools>
        <Button type="primary" @click="createApi.open()">
          <Plus class="size-5" />
          登记到货计划
        </Button>
      </template>
    </Grid>
  </Page>
</template>
