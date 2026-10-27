<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { OperationExceptionApi } from '#/api';

import { onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page, useVbenDrawer } from '@vben/common-ui';

import { Button, message } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getExceptionApi, getExceptionAssigneeOptionsApi, getExceptionListApi, getMyOperationTaskApi, resolveOperationTaskNotificationApi } from '#/api';
import { parseProposalNotificationId } from '#/utils/proposal-notification';
import { applyAiFiltersToList } from '#/utils/ai-list-filters';

import { useColumns, useGridFormSchema } from './data';
import DetailDrawer from './modules/detail.vue';

defineOptions({ name: 'OperationExceptionList' });
const route = useRoute();
const router = useRouter();

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

let taskNotificationVersion = 0;
watch(() => route.query.task_notification, async (value) => {
  const version = ++taskNotificationVersion;
  const id = parseProposalNotificationId(value);
  if (id === undefined) return;
  try {
    const reference = await resolveOperationTaskNotificationApi(id);
    const task = await getMyOperationTaskApi(reference.task_id);
    if (task.exception_id !== reference.exception_id) throw new Error('任务关联已变化');
    const exception = await getExceptionApi(task.exception_id);
    if (version === taskNotificationVersion) detailApi.setData({ ...exception, focus_task_id: task.id }).open();
  } catch {
    if (version === taskNotificationVersion) message.error('任务不可访问或已改派');
  } finally {
    if (version === taskNotificationVersion && route.query.task_notification === value) {
      const query = { ...route.query }; delete query.task_notification;
      void router.replace({ query });
    }
  }
}, { immediate: true });

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
