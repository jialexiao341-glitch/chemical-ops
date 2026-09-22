<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { FinanceApi } from '#/api';

import { onMounted, ref } from 'vue';

import { Page, useVbenModal } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, Input, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  getInvoiceListApi,
  rejectInvoiceApi,
  submitInvoiceApi,
  verifyInvoiceApi,
} from '#/api';
import { getSupplierNameMap } from '#/utils/lookup';

import { useColumns, useGridFormSchema } from './data';
import CreateModal from './modules/create.vue';

defineOptions({ name: 'InvoiceList' });

const [Create, createApi] = useVbenModal({
  connectedComponent: CreateModal,
  destroyOnClose: true,
});

const resolveSupplier = ref<(id?: null | number) => string>(() => '-');

/** 驳回弹窗（原因必填） */
const rejectVisible = ref(false);
const rejectReason = ref('');
const rejectRow = ref<FinanceApi.Invoice>();

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
          return await getInvoiceListApi({
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
  } as VxeTableGridOptions<FinanceApi.Invoice>,
});

function runSubmit(row: FinanceApi.Invoice) {
  Modal.confirm({
    content: `提交发票 ${row.invoice_no} 进入核验？`,
    okText: '提交核验',
    onOk: async () => {
      await submitInvoiceApi(row.id);
      message.success('已提交核验');
      gridApi.query();
    },
    title: '提交发票核验',
  });
}

function runVerify(row: FinanceApi.Invoice) {
  Modal.confirm({
    content: `确认核验通过发票 ${row.invoice_no}？核验后的发票金额可被付款引用。`,
    okText: '核验通过',
    onOk: async () => {
      await verifyInvoiceApi(row.id);
      message.success('发票已核验');
      gridApi.query();
    },
    title: '核验发票',
  });
}

function openReject(row: FinanceApi.Invoice) {
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
    await rejectInvoiceApi(rejectRow.value.id, rejectReason.value.trim());
    message.success('发票已驳回');
    rejectVisible.value = false;
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
    <Grid table-title="供应商发票">
      <template #toolbar-tools>
        <Button type="primary" @click="createApi.open()">
          <Plus class="size-5" />
          录入发票
        </Button>
      </template>
      <template #operation="{ row }">
        <div class="flex flex-wrap justify-center gap-0">
          <Button
            v-if="['DRAFT', 'REJECTED'].includes(row.status)"
            size="small"
            type="link"
            @click="runSubmit(row)"
          >
            提交核验
          </Button>
          <Button
            v-if="row.status === 'SUBMITTED'"
            size="small"
            type="link"
            @click="runVerify(row)"
          >
            核验
          </Button>
          <Button
            v-if="row.status === 'SUBMITTED'"
            danger
            size="small"
            type="link"
            @click="openReject(row)"
          >
            驳回
          </Button>
        </div>
      </template>
    </Grid>

    <!-- 驳回弹窗（原因必填） -->
    <Modal
      v-model:open="rejectVisible"
      cancel-text="取消"
      ok-text="确认驳回"
      title="驳回发票"
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
