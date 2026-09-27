<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { RfqApi } from '#/api';

import { onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getRfqListApi, sendRfqApi } from '#/api';

import { useColumns, useGridFormSchema } from './data';
import DetailDrawer from './modules/detail.vue';
import Form from './modules/form.vue';

defineOptions({ name: 'RfqList' });
const route = useRoute();

const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

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
          return await getRfqListApi({
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
  } as VxeTableGridOptions<RfqApi.Rfq>,
});

function onActionClick({ code, row }: OnActionClickParams<RfqApi.Rfq>) {
  switch (code) {
    case 'detail': {
      detailApi.setData(row).open();
      break;
    }
    case 'edit': {
      formDrawerApi.setData(row).open();
      break;
    }
    case 'send': {
      onSend(row);
      break;
    }
  }
}

function onSend(row: RfqApi.Rfq) {
  Modal.confirm({
    content: `发送后供应商即可报价，询价单不可再编辑：${row.rfq_no}`,
    onOk: async () => {
      await sendRfqApi(row.id);
      message.success('询价单已发送');
      gridApi.query();
    },
    okText: '发送',
    title: '发送询价单',
  });
}

function openAiRfq(rawId: unknown) {
  const id = Number(rawId);
  if (!Number.isInteger(id) || id <= 0) return;
  detailApi.setData({ id } as RfqApi.Rfq).open();
}

onMounted(() => openAiRfq(route.query.ai_record_id));

watch(
  () => route.query.ai_record_id,
  (rawId) => openAiRfq(rawId),
);
</script>

<template>
  <Page auto-content-height>
    <FormDrawer @success="gridApi.query()" />
    <Detail @success="gridApi.query()" />
    <Grid table-title="询价与报价">
      <template #toolbar-tools>
        <Button type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新建询价单
        </Button>
      </template>
    </Grid>
  </Page>
</template>
