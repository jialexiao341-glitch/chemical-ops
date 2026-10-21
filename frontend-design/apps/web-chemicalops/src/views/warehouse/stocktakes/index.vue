<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { StocktakeApi } from '#/api';

import { onMounted, ref } from 'vue';

import { useAccess } from '@vben/access';
import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';
import { useUserStore } from '@vben/stores';

import { Button, message, Modal } from 'antdv-next';

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

import ReasonModal from '#/components/reason-modal/index.vue';

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
const rejectRow = ref<StocktakeApi.StocktakeRequest>();

function openReject(row: StocktakeApi.StocktakeRequest) {
  rejectRow.value = row;
  rejectVisible.value = true;
}

async function onRejectConfirm(reason: string) {
  if (!rejectRow.value) throw new Error('未选择记录');
  await rejectStocktakeApi(rejectRow.value.id, reason);
  message.success('已驳回');
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

    <ReasonModal v-model:open="rejectVisible" title="驳回盘点申请" label="驳回原因" ok-text="确认驳回" :submit="onRejectConfirm" @success="gridApi.query()" />
  </Page>
</template>
