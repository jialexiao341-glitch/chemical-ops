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
const canApproveStocktakes = hasAccessByCodes(['warehouse.inventory.stocktake.approve']);

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
    columns: useColumns((id) => resolveWarehouse.value(id)),
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
      <template #operation="{ row }">
        <div class="flex flex-wrap justify-center gap-0">
          <Button
            v-if="canWriteStocktakes"
            :disabled="!['DRAFT', 'REJECTED'].includes(row.status)"
            :title="!['DRAFT', 'REJECTED'].includes(row.status) ? '仅草稿或已驳回申请可操作' : undefined"
            size="small"
            type="link"
            @click="formDrawerApi.setData(row).open()"
          >
            编辑
          </Button>
          <Button size="small" type="link" @click="detailApi.setData(row).open()">
            详情
          </Button>
          <Button
            v-if="canWriteStocktakes"
            :disabled="!['DRAFT', 'REJECTED'].includes(row.status)"
            :title="!['DRAFT', 'REJECTED'].includes(row.status) ? '仅草稿或已驳回申请可操作' : undefined"
            size="small"
            type="link"
            @click="
              run(() => submitStocktakeApi(row.id), {
                content: `提交后进入审批流程：${row.stocktake_no}`,
                okText: '提交',
                title: '提交盘点申请',
              })
            "
          >
            提交
          </Button>
          <Button
            v-if="canApproveStocktakes"
            :disabled="row.status !== 'SUBMITTED' || String(row.applicant_id) === String(userStore.userInfo?.userId)"
            :title="String(row.applicant_id) === String(userStore.userInfo?.userId) ? '本人经办记录须由他人审批' : row.status !== 'SUBMITTED' ? '仅待审批申请可审批或驳回' : undefined"
            size="small"
            type="link"
            @click="
              run(() => approveStocktakeApi(row.id), {
                content: `确认审批通过 ${row.stocktake_no}？`,
                okText: '审批通过',
                title: '审批盘点申请',
              })
            "
          >
            审批通过
          </Button>
          <Button
            v-if="canApproveStocktakes"
            :disabled="row.status !== 'SUBMITTED' || String(row.applicant_id) === String(userStore.userInfo?.userId)"
            :title="String(row.applicant_id) === String(userStore.userInfo?.userId) ? '本人经办记录须由他人审批' : row.status !== 'SUBMITTED' ? '仅待审批申请可审批或驳回' : undefined"
            danger
            size="small"
            type="link"
            @click="openReject(row)"
          >
            驳回
          </Button>
          <Button
            v-if="canWriteStocktakes"
            :disabled="row.status !== 'APPROVED'"
            :title="row.status !== 'APPROVED' ? '仅已审批申请可执行盘点' : undefined"
            size="small"
            type="link"
            @click="
              run(() => executeStocktakeApi(row.id), {
                content: `确认按实盘数量执行差异调整？库存将按差额增减：${row.stocktake_no}`,
                okText: '执行盘点',
                title: '执行盘点调整',
              })
            "
          >
            执行盘点
          </Button>
          <Button
            v-if="canWriteStocktakes"
            :disabled="!['DRAFT', 'REJECTED'].includes(row.status)"
            :title="!['DRAFT', 'REJECTED'].includes(row.status) ? '仅草稿或已驳回申请可操作' : undefined"
            danger
            size="small"
            type="link"
            @click="
              run(() => cancelStocktakeApi(row.id), {
                content: `确认取消 ${row.stocktake_no}？取消后不可恢复。`,
                okText: '取消',
                title: '取消盘点申请',
              })
            "
          >
            取消
          </Button>
        </div>
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
