<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { QualityAcceptanceApi } from '#/api';

import { Page, useVbenDrawer, useVbenModal } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getAcceptanceListApi } from '#/api';

import { useColumns, useGridFormSchema } from './data';
import CreateModal from './modules/create.vue';
import ResultDrawer from './modules/result.vue';

defineOptions({ name: 'AcceptanceList' });

const [Create, createApi] = useVbenModal({
  connectedComponent: CreateModal,
  destroyOnClose: true,
});

const [Result, resultApi] = useVbenDrawer({
  connectedComponent: ResultDrawer,
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
          return await getAcceptanceListApi({
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
  } as VxeTableGridOptions<QualityAcceptanceApi.Acceptance>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<QualityAcceptanceApi.Acceptance>) {
  if (code === 'result') {
    resultApi.setData(row).open();
  }
}
</script>

<template>
  <Page auto-content-height>
    <Create @success="gridApi.query()" />
    <Result @success="gridApi.query()" />
    <Grid table-title="质量验收">
      <template #toolbar-tools>
        <Button type="primary" @click="createApi.open()">
          <Plus class="size-5" />
          创建验收
        </Button>
      </template>
    </Grid>
  </Page>
</template>
