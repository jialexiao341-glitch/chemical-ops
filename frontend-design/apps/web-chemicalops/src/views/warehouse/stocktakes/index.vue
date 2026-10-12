<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { StocktakeApi } from '#/api';

import { onMounted, ref } from 'vue';

import { useAccess } from '@vben/access';
import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';
import { useUserStore } from '@vben/stores';

import { Button, Input, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  approveStocktakeApi,
  cancelStocktakeApi,
  executeStocktakeApi,
  getStocktakeListApi,
  getWarehouseListApi,
  rejectStocktakeApi,
  submitStocktakeApi,
} from '#/api';

import { useColumns, useGridFormSchema } from './data';
import DetailDrawer from './modules/detail.vue';
import Form from './modules/form.vue';

defineOptions({ name: 'StocktakeList' });
const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();
const canWriteStocktakes = hasAccessByCodes(['warehouse.inventory.stocktake.write']);

const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

const [Detail, detailApi] = useVbenDrawer({
  connectedComponent: DetailDrawer,
  destroyOnClose: true,
});

const resolveWarehouse = ref<(id?: null | number) => string>(() => '-');

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns((id) => resolveWarehouse.value(id), onActionClick, userStore.userInfo?.userId),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getStocktakeListApi({
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
  } as VxeTableGridOptions<StocktakeApi.StocktakeRequest>,
});

const rejectVisible = ref(false);
const rejectReason = ref('');
const rejectRow = ref<StocktakeApi.StocktakeRequest>();

function openReject(row: StocktakeApi.StocktakeRequest) {
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
    await rejectStocktakeApi(rejectRow.value.id, rejectReason.value.trim());
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

function onActionClick({ code, row }: { code: string; row: StocktakeApi.StocktakeRequest }) {
  if (code === 'detail') {
    detailApi.setData(row).open();
  } else if (code === 'edit') {
    formDrawerApi.setData(row).open();
  } else if (code === 'submit') {
    run(() => submitStocktakeApi(row.id), {
      content: `提交后进入审批流程：${row.stocktake_no}`,
      okText: '提交',
      title: '提交盘点申请',
    });
  } else if (code === 'approve') {
    run(() => approveStocktakeApi(row.id), {
      content: `确认审批通过 ${row.stocktake_no}？`,
      okText: '审批通过',
      title: '审批盘点申请',
    });
  } else if (code === 'reject') {
    openReject(row);
  } else if (code === 'execute') {
    run(() => executeStocktakeApi(row.id), {
      content: `确认按实盘数量执行差异调整？库存将按差额增减：${row.stocktake_no}`,
      okText: '执行盘点',
      title: '执行盘点调整',
    });
  } else if (code === 'cancel') {
    run(() => cancelStocktakeApi(row.id), {
      content: `确认取消 ${row.stocktake_no}？取消后不可恢复。`,
      okText: '取消',
      title: '取消盘点申请',
    });
  }
}

onMounted(async () => {
  const warehouses = await getWarehouseListApi();
  const map = new Map(warehouses.map((item) => [item.id, item.warehouse_name]));
  resolveWarehouse.value = (id) =>
    !id ? '-' : (map.get(id) ?? `#${id}`);
  gridApi.query();
});
</script>

<template>
  <Page auto-content-height>
    <FormDrawer @success="gridApi.query()" />
    <Detail />
    <Grid table-title="库存盘点">
      <template #toolbar-tools>
        <Button v-if="canWriteStocktakes" type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新建盘点申请
        </Button>
      </template>
    </Grid>

    <Modal
      v-model:open="rejectVisible"
      cancel-text="取消"
      ok-text="确认驳回"
      title="驳回盘点申请"
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
