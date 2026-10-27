<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { OperationExceptionApi } from '#/api';

import { onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { Page, useVbenDrawer } from '@vben/common-ui';

import { Button } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getExceptionApi, getExceptionAssigneeOptionsApi, getExceptionListApi } from '#/api';
import { applyAiFiltersToList } from '#/utils/ai-list-filters';

import { useColumns, useGridFormSchema } from './data';
import DetailDrawer from './modules/detail.vue';

defineOptions({ name: 'OperationExceptionList' });
const route = useRoute();

const [Detail, detailApi] = useVbenDrawer({
  connectedComponent: DetailDrawer,
  destroyOnClose: true,
});

const resolveOwner = ref<(id?: null | number) => string>(() => '-');

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns((id) => resolveOwner.value(id)),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getExceptionListApi({
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
  } as VxeTableGridOptions<OperationExceptionApi.Exception>,
});

function onActionClick({
  row,
}: OnActionClickParams<OperationExceptionApi.Exception>) {
  detailApi.setData(row).open();
}

onMounted(async () => {
  const linkedId = Number(route.query.exception_id);
  if (Number.isSafeInteger(linkedId) && linkedId > 0) {
    try { detailApi.setData(await getExceptionApi(linkedId)).open(); } catch { /* 原接口已执行权限校验 */ }
  }
  // 负责人 ID → 姓名（失败时降级显示 #ID）
  try {
    const users = await getExceptionAssigneeOptionsApi();
    const map = new Map(users.map((item) => [item.id, item.display_name || item.username]));
    resolveOwner.value = (id) => {
      if (!id) {
        return '-';
      }
      return map.get(id) ?? `#${id}`;
    };
  } catch {
    resolveOwner.value = (id) => (id ? `#${id}` : '-');
  }
  await applyAiFiltersToList(
    'exceptions',
    route.query.ai_filters,
    gridApi.formApi,
  );
  gridApi.query();
});

watch(
  () => route.query.ai_filters,
  async (rawQuery) => {
    if (await applyAiFiltersToList('exceptions', rawQuery, gridApi.formApi)) {
      gridApi.query();
    }
  },
);
</script>

<template>
  <Page auto-content-height>
    <Detail @success="gridApi.query()" />
    <Grid table-title="运营异常">
      <template #toolbar-tools>
        <Button @click="gridApi.query()">刷新</Button>
      </template>
      <template #operation="{ row }">
        <Button size="small" type="link" @click="onActionClick({ row } as any)">
          详情
        </Button>
      </template>
    </Grid>
  </Page>
</template>
