<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { PurchaseRequestApi } from '#/api';

import { onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';

import { Page, useVbenDrawer, useVbenModal } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getPurchaseRequestListApi, submitPurchaseRequestApi } from '#/api';
import { applyAiFiltersToList } from '#/utils/ai-list-filters';

import { useColumns, useGridFormSchema } from './data';
import ApproveModal from './modules/approve.vue';
import CancelModal from './modules/cancel.vue';
import DetailDrawer from './modules/detail.vue';
import Form from './modules/form.vue';

defineOptions({ name: 'PurchaseRequestList' });
const route = useRoute();

const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

const [Detail, detailApi] = useVbenDrawer({
  connectedComponent: DetailDrawer,
  destroyOnClose: true,
});

const [Approve, approveApi] = useVbenModal({
  connectedComponent: ApproveModal,
  destroyOnClose: true,
});

const [Cancel, cancelApi] = useVbenModal({
  connectedComponent: CancelModal,
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
          return await getPurchaseRequestListApi({
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
  } as VxeTableGridOptions<PurchaseRequestApi.PurchaseRequest>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<PurchaseRequestApi.PurchaseRequest>) {
  const payload = { id: row.id, requestNo: row.request_no ?? '' };
  switch (code) {
    case 'approve': {
      approveApi.setData({ ...payload, action: 'approve' }).open();
      break;
    }
    case 'cancel': {
      cancelApi.setData(payload).open();
      break;
    }
    case 'detail': {
      detailApi.setData(row).open();
      break;
    }
    case 'edit': {
      formDrawerApi.setData(row).open();
      break;
    }
    case 'reject': {
      approveApi.setData({ ...payload, action: 'reject' }).open();
      break;
    }
    case 'submit': {
      onSubmit(row);
      break;
    }
  }
}

function onSubmit(row: PurchaseRequestApi.PurchaseRequest) {
  Modal.confirm({
    content: `提交后将进入审批流程，期间不可编辑：${row.request_no}`,
    onOk: async () => {
      await submitPurchaseRequestApi(row.id);
      message.success('已提交审批');
      gridApi.query();
    },
    okText: '提交',
    title: '提交采购申请',
  });
}

onMounted(async () => {
  await applyAiFiltersToList(
    'purchase_requests',
    route.query.ai_filters,
    gridApi.formApi,
  );
  gridApi.query();
  openAiRecord(route.query.ai_record_id);
});

function openAiRecord(rawId: unknown) {
  const id = Number(rawId);
  if (!Number.isInteger(id) || id <= 0) return;
  detailApi.setData({ id } as PurchaseRequestApi.PurchaseRequest).open();
}

watch(
  () => route.query.ai_filters,
  async (rawQuery) => {
    if (await applyAiFiltersToList('purchase_requests', rawQuery, gridApi.formApi)) {
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
    <FormDrawer @success="gridApi.query()" />
    <Detail />
    <Approve @success="gridApi.query()" />
    <Cancel @success="gridApi.query()" />
    <Grid table-title="采购申请">
      <template #toolbar-tools>
        <Button type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新建采购申请
        </Button>
      </template>
    </Grid>
  </Page>
</template>
