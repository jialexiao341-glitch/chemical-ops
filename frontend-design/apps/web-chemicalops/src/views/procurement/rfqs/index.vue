<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { RfqApi } from '#/api';

import { onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';

import { useAccess } from '@vben/access';
import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { confirmActionProposalApi, createActionProposalApi, getRfqListApi } from '#/api';
import { canConfirmActionProposal } from '#/views/ai/workspace/action-proposal-policy';

import { useColumns, useGridFormSchema } from './data';
import DetailDrawer from './modules/detail.vue';
import Form from './modules/form.vue';

defineOptions({ name: 'RfqList' });
const route = useRoute();
const { hasAccessByCodes } = useAccess();
const canWriteRfqs = hasAccessByCodes(['procurement.rfqs.write']);

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
  void createRfqSendProposal(row);
}

async function createRfqSendProposal(row: RfqApi.Rfq) {
  try {
    const proposal = await createActionProposalApi('rfq.send', { rfq_id: row.id }, makeIdempotencyKey());
    if (!canConfirmActionProposal(proposal, proposal.preview_version, false)) {
      message.warning(proposal.blockers.join('；') || '当前询价单不能发送，请检查后重试。');
      return;
    }
    Modal.confirm({
      content: `确认将询价单 ${row.rfq_no} 发送给已邀请供应商？发送后供应商即可报价，询价单不可再编辑。`,
      onOk: async () => {
        await confirmActionProposalApi(proposal.confirmation_id, proposal.preview_version);
        message.success('询价单已发送');
        gridApi.query();
      },
      okText: '确认发送',
      title: '检查并发送询价单',
    });
  } catch {
    // 请求层已展示后端错误；用户可检查状态后重新发起。
  }
}

function makeIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
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
        <Button v-if="canWriteRfqs" type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新建询价单
        </Button>
      </template>
    </Grid>
  </Page>
</template>
