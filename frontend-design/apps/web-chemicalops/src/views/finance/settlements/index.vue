<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { FinanceApi } from '#/api';

import { onMounted, ref } from 'vue';

import { Page, useVbenModal } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, Input, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  cancelSettlementApi,
  confirmSettlementApi,
  getSettlementListApi,
} from '#/api';
import { getSupplierNameMap } from '#/utils/lookup';

import { useColumns, useGridFormSchema } from './data';
import CreateModal from './modules/create.vue';

defineOptions({ name: 'SettlementList' });

const [Create, createApi] = useVbenModal({
  connectedComponent: CreateModal,
  destroyOnClose: true,
});

const resolveSupplier = ref<(id?: null | number) => string>(() => '-');

/** 取消弹窗（原因必填） */
const cancelVisible = ref(false);
const cancelReason = ref('');
const cancelRow = ref<FinanceApi.Settlement>();

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns((id) => resolveSupplier.value(id)),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getSettlementListApi({
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
  } as VxeTableGridOptions<FinanceApi.Settlement>,
});

function runConfirm(row: FinanceApi.Settlement) {
  Modal.confirm({
    content: `确认结算单 ${row.settlement_no}？确认后将关闭对应对账单，不可撤销。`,
    okText: '确认结算',
    onOk: async () => {
      await confirmSettlementApi(row.id);
      message.success('结算单已确认，对账单已关闭');
      gridApi.query();
    },
    title: '确认结算单',
  });
}

function openCancel(row: FinanceApi.Settlement) {
  cancelRow.value = row;
  cancelReason.value = '';
  cancelVisible.value = true;
}

async function onCancelConfirm() {
  if (!cancelReason.value.trim()) {
    message.warning('请填写取消原因');
    return;
  }
  if (!cancelRow.value) {
    return;
  }
  try {
    await cancelSettlementApi(cancelRow.value.id, cancelReason.value.trim());
    message.success('结算单已取消');
    cancelVisible.value = false;
    gridApi.query();
  } catch {
    // 请求层已弹出错误，保持弹窗打开
  }
}

onMounted(async () => {
  try {
    const suppliers = await getSupplierNameMap();
    resolveSupplier.value = (id) => {
      if (!id) {
        return '-';
      }
      return suppliers.get(id) ?? `#${id}`;
    };
  } catch {
    resolveSupplier.value = (id) => (id ? `#${id}` : '-');
  }
  gridApi.query();
});
</script>

<template>
  <Page auto-content-height>
    <Create @success="gridApi.query()" />
    <Grid table-title="采购结算">
      <template #toolbar-tools>
        <Button type="primary" @click="createApi.open()">
          <Plus class="size-5" />
          创建结算单
        </Button>
      </template>
      <template #operation="{ row }">
        <div class="flex flex-wrap justify-center gap-0">
          <Button
            v-if="row.status === 'DRAFT'"
            size="small"
            type="link"
            @click="runConfirm(row)"
          >
            确认结算
          </Button>
          <Button
            v-if="row.status === 'DRAFT'"
            danger
            size="small"
            type="link"
            @click="openCancel(row)"
          >
            取消
          </Button>
        </div>
      </template>
    </Grid>

    <!-- 取消弹窗（原因必填） -->
    <Modal
      v-model:open="cancelVisible"
      cancel-text="返回"
      ok-text="确认取消"
      title="取消结算单"
      @ok="onCancelConfirm"
    >
      <div class="py-2">
        <div class="mb-2 text-sm">
          取消原因 <span class="text-red-500">*</span>
        </div>
        <Input.TextArea
          v-model:value="cancelReason"
          :maxlength="1000"
          :rows="3"
          placeholder="请说明取消原因（必填）"
        />
      </div>
    </Modal>
  </Page>
</template>
