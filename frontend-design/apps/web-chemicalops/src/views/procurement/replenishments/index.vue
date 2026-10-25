<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { ReplenishmentApi } from '#/api';

import { onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';

import { Page, useVbenDrawer } from '@vben/common-ui';

import { Button } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getReplenishmentListApi } from '#/api';

import { useColumns, useGridFormSchema } from './data';
import DetailDrawer from './modules/detail.vue';

defineOptions({ name: 'ReplenishmentList' });
const route = useRoute();

const [Detail, detailApi] = useVbenDrawer({
  connectedComponent: DetailDrawer,
  destroyOnClose: true,
});

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns(onActionClick),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getReplenishmentListApi({
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
  } as VxeTableGridOptions<ReplenishmentApi.Replenishment>,
});

function onActionClick({
  row,
}: OnActionClickParams<ReplenishmentApi.Replenishment>) {
  detailApi.setData({ id: row.id }).open();
}

function openAiRecord(rawId: unknown) {
  const id = Number(rawId);
  if (!Number.isInteger(id) || id <= 0) {
    return;
  }
  detailApi.setData({ id }).open();
}

onMounted(() => {
  openAiRecord(route.query.ai_record_id);
});

watch(
  () => route.query.ai_record_id,
  (rawId) => openAiRecord(rawId),
);
</script>

<template>
  <Page auto-content-height>
    <Detail @success="gridApi.query()" />
    <Grid table-title="补货申请">
      <template #toolbar-tools>
        <Button @click="gridApi.query()">刷新</Button>
      </template>
    </Grid>
  </Page>
</template>
