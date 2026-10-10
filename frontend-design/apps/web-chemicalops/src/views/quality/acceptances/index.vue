<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { QualityAcceptanceApi } from '#/api';

import { onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';

import { useAccess } from '@vben/access';
import { Page, useVbenDrawer, useVbenModal } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getAcceptanceApi, getAcceptanceListApi } from '#/api';
import { applyAiFiltersToList } from '#/utils/ai-list-filters';

import { useColumns, useGridFormSchema } from './data';
import CreateModal from './modules/create.vue';
import ReportReviewDrawer from './modules/report-review.vue';
import ResultDrawer from './modules/result.vue';

defineOptions({ name: 'AcceptanceList' });
const route = useRoute();
const { hasAccessByCodes } = useAccess();
const canAssignAcceptances = hasAccessByCodes(['quality.acceptances.assign']);
const canWriteAcceptances = hasAccessByCodes(['quality.acceptances.write']);

const [Create, createApi] = useVbenModal({
  connectedComponent: CreateModal,
  destroyOnClose: true,
});

const [Result, resultApi] = useVbenDrawer({
  connectedComponent: ResultDrawer,
  destroyOnClose: true,
});

const [ReportReview, reportReviewApi] = useVbenDrawer({
  connectedComponent: ReportReviewDrawer,
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
  if (code === 'result' && canWriteAcceptances) {
    resultApi.setData(row).open();
  } else if (code === 'review') {
    reportReviewApi.setData(row).open();
  }
}

function continueToResult(record: QualityAcceptanceApi.Acceptance) {
  if (!canWriteAcceptances || (record.result && !['PENDING', 'REINSPECTION'].includes(record.result))) return;
  resultApi.setData(record).open();
}

onMounted(async () => {
  await applyAiFiltersToList(
    'quality_acceptances',
    route.query.ai_filters,
    gridApi.formApi,
  );
  gridApi.query();
  await openAiRecord(route.query.ai_record_id);
});

async function openAiRecord(rawId: unknown) {
  if (!canWriteAcceptances) return;
  const id = Number(rawId);
  if (!Number.isInteger(id) || id <= 0) return;
  try {
    const record = await getAcceptanceApi(id);
    if (!record.result || ['PENDING', 'REINSPECTION'].includes(record.result)) {
      resultApi.setData(record).open();
    }
  } catch {
    // API 层会展示权限或查询错误；不再打开一个不匹配的记录。
  }
}

watch(
  () => route.query.ai_filters,
  async (rawQuery) => {
    if (await applyAiFiltersToList('quality_acceptances', rawQuery, gridApi.formApi)) {
      gridApi.query();
    }
  },
);

watch(
  () => route.query.ai_record_id,
  (rawId) => {
    void openAiRecord(rawId);
  },
);
</script>

<template>
  <Page auto-content-height>
    <Create @success="gridApi.query()" />
    <Result @success="gridApi.query()" @review="(record: QualityAcceptanceApi.Acceptance) => reportReviewApi.setData(record).open()" />
    <ReportReview @continue="continueToResult" />
    <Grid table-title="质量验收">
      <template #toolbar-tools>
        <Button v-if="canAssignAcceptances" type="primary" @click="createApi.open()">
          <Plus class="size-5" />
          创建验收
        </Button>
      </template>
    </Grid>
  </Page>
</template>
