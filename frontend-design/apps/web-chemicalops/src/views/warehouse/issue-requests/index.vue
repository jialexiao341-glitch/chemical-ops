<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { IssueRequestApi } from '#/api';

import { ref } from 'vue';

import { useAccess } from '@vben/access';
import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';
import { useUserStore } from '@vben/stores';

import { Button, Input, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  approveIssueApi,
  cancelIssueApi,
  executeIssueApi,
  getIssueListApi,
  rejectIssueApi,
  submitIssueApi,
} from '#/api';

import { useColumns, useGridFormSchema } from './data';
import DetailDrawer from './modules/detail.vue';
import Form from './modules/form.vue';

defineOptions({ name: 'IssueRequestList' });
const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();
const canWriteIssueRequests = hasAccessByCodes(['warehouse.inventory.issue.write']);
const isTechnicalRole = useUserStore().userInfo?.roles?.includes('TECHNICAL') ?? false;

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
    columns: useColumns(onActionClick, userStore.userInfo?.userId),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getIssueListApi({
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
  } as VxeTableGridOptions<IssueRequestApi.IssueRequest>,
});

// 驳回弹窗（必须填原因）
const rejectVisible = ref(false);
const rejectReason = ref('');
const rejectRow = ref<IssueRequestApi.IssueRequest>();

function openReject(row: IssueRequestApi.IssueRequest) {
  rejectRow.value = row;
  rejectReason.value = '';
  rejectVisible.value = true;
}

async function onRejectConfirm() {
  if (!rejectReason.value.trim()) {
    message.warning('请填写驳回原因');
    return;
  }
  if (!rejectRow.value) {
    return;
  }
  try {
    await rejectIssueApi(rejectRow.value.id, rejectReason.value.trim());
    message.success('已驳回');
    rejectVisible.value = false;
    gridApi.query();
  } catch {
    // 请求层已弹出错误，保持弹窗打开
  }
}

function run(
  action: () => Promise<unknown>,
  confirm: { content: string; okText: string; title: string },
) {
  Modal.confirm({
    content: confirm.content,
    okText: confirm.okText,
    onOk: async () => {
      await action();
      message.success('操作成功');
      gridApi.query();
    },
    title: confirm.title,
  });
}

function onActionClick({ code, row }: { code: string; row: IssueRequestApi.IssueRequest }) {
  if (code === 'detail') detailApi.setData(row).open();
  else if (code === 'edit') formDrawerApi.setData(row).open();
  else if (code === 'submit') run(() => submitIssueApi(row.id), { content: `提交后进入审批流程：${row.issue_no}`, okText: '提交', title: '提交领用申请' });
  else if (code === 'approve') run(() => approveIssueApi(row.id), { content: `确认审批通过 ${row.issue_no}？`, okText: '审批通过', title: '审批领用申请' });
  else if (code === 'reject') openReject(row);
  else if (code === 'execute') run(() => executeIssueApi(row.id), { content: `确认按明细执行出库？执行后库存将减少：${row.issue_no}`, okText: '执行出库', title: '执行领用出库' });
  else if (code === 'cancel') run(() => cancelIssueApi(row.id), { content: `确认取消 ${row.issue_no}？取消后不可恢复。`, okText: '取消', title: '取消领用申请' });
}
</script>

<template>
  <Page auto-content-height>
    <FormDrawer @success="gridApi.query()" />
    <Detail />
    <Grid :table-title="isTechnicalRole ? '我的领用申请' : '库存领用'">
      <template #toolbar-tools>
        <Button v-if="canWriteIssueRequests" type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新建领用申请
        </Button>
      </template>

    </Grid>

    <!-- 驳回弹窗 -->
    <Modal
      v-model:open="rejectVisible"
      cancel-text="取消"
      ok-text="确认驳回"
      title="驳回领用申请"
      @ok="onRejectConfirm"
    >
      <div class="py-2">
        <div class="mb-2 text-sm">
          驳回原因 <span class="text-red-500">*</span>
        </div>
        <Input.TextArea
          v-model:value="rejectReason"
          :maxlength="1000"
          :rows="3"
          placeholder="请说明驳回原因（必填）"
        />
      </div>
    </Modal>
  </Page>
</template>
