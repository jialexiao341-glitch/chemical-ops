<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { FinanceApi } from '#/api';

import { onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { Page, useVbenModal, useVbenDrawer } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { Plus } from '@vben/icons';
import { useUserStore } from '@vben/stores';

import { Button, Input, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  getInvoiceListApi,
  rejectInvoiceApi,
  submitInvoiceApi,
  verifyInvoiceApi,
  voidInvoiceApi,
} from '#/api';
import { getSupplierNameMap } from '#/utils/lookup';

import { useColumns, useGridFormSchema } from './data';
import CreateModal from './modules/create.vue';
import MatchDrawer from './modules/matches.vue';
import FinanceSourceDetail from '#/views/ai/workspace/modules/finance-source-detail.vue';

defineOptions({ name: 'InvoiceList' });
const route = useRoute();
const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();
const [Matches, matchesApi] = useVbenDrawer({ connectedComponent: MatchDrawer, destroyOnClose: true });
const financeSourceDetail = ref<InstanceType<typeof FinanceSourceDetail>>();

const [Create, createApi] = useVbenModal({
  connectedComponent: CreateModal,
  destroyOnClose: true,
});

const resolveSupplier = ref<(id?: null | number) => string>(() => '-');

/** 驳回弹窗（原因必填） */
const rejectVisible = ref(false);
const rejectReason = ref('');
const rejectRow = ref<FinanceApi.Invoice>();
const voiding = ref(false);

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns((id) => resolveSupplier.value(id), onActionClick, userStore.userInfo?.userId),
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

function onActionClick({ code, row }: { code: string; row: FinanceApi.Invoice }) {
  if (code === 'detail') {
    financeSourceDetail.value?.open({ id: row.id, kind: 'invoices' });
  } else if (code === 'matches') {
    matchesApi.setData(row.id).open();
  } else if (code === 'void') {
    openVoid(row);
  } else if (code === 'submit') {
    runSubmit(row);
  } else if (code === 'verify') {
    runVerify(row);
  } else if (code === 'reject') {
    openReject(row);
  }
}

function runSubmit(row: FinanceApi.Invoice) {
  Modal.confirm({
    content: `提交发票 ${row.invoice_no} 进入核验？`,
    okText: '提交核验',
    onOk: async () => {
      if (!hasAccessByCodes(['finance.invoices.write'])) return;
      await submitInvoiceApi(row.id);
      message.success('已提交核验');
      gridApi.query();
    },
    title: '提交发票核验',
  });
}

function runVerify(row: FinanceApi.Invoice) {
  Modal.confirm({
    content: `确认对发票 ${row.invoice_no} 完成人工复核？复核后的发票金额可被付款引用；此操作不代表已向税务平台验真。`,
    okText: '确认人工复核',
    onOk: async () => {
      if (!hasAccessByCodes(['finance.invoices.verify'])) return;
      await verifyInvoiceApi(row.id);
      message.success('发票已完成人工复核');
      gridApi.query();
    },
    title: '人工复核发票',
  });
}

function openReject(row: FinanceApi.Invoice) {
  voiding.value = false;
  rejectRow.value = row;
  rejectReason.value = '';
  rejectVisible.value = true;
}

function openVoid(row: FinanceApi.Invoice) {
  openReject(row);
  voiding.value = true;
}

async function onRejectConfirm() {
  if (!hasAccessByCodes([voiding.value ? 'finance.invoices.write' : 'finance.invoices.verify'])) return;
  if (!rejectReason.value.trim()) {
    message.warning('请填写原因');
    return;
  }
  if (!rejectRow.value) {
    return;
  }
  try {
    if (voiding.value) await voidInvoiceApi(rejectRow.value.id, rejectReason.value.trim());
    else await rejectInvoiceApi(rejectRow.value.id, rejectReason.value.trim());
    message.success(voiding.value ? '发票已作废，匹配额度已释放' : '发票已驳回');
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
  openAiInvoice(route.query.ai_record_id, route.query.ai_record_type);
});

function openAiInvoice(rawId: unknown, rawType: unknown) {
  const id = Number(rawId);
  if (rawType !== 'invoices' || !Number.isInteger(id) || id <= 0) return;
  financeSourceDetail.value?.open({ id, kind: 'invoices' });
}

watch(
  () => [route.query.ai_record_id, route.query.ai_record_type],
  ([id, kind]) => openAiInvoice(id, kind),
);
</script>

<template>
  <Page auto-content-height>
    <FinanceSourceDetail ref="financeSourceDetail" />
    <Create @success="gridApi.query()" />
    <Matches @success="gridApi.query()" />
    <Grid table-title="供应商发票">
      <template #toolbar-tools>
        <Button v-if="hasAccessByCodes(['finance.invoices.write'])" type="primary" @click="createApi.open()">
          <Plus class="size-5" />
          录入发票
        </Button>
      </template>
    </Grid>

    <!-- 驳回弹窗（原因必填） -->
    <Modal
      v-model:open="rejectVisible"
      :ok-button-props="{ disabled: !hasAccessByCodes([voiding ? 'finance.invoices.write' : 'finance.invoices.verify']) }"
      cancel-text="取消"
      :ok-text="voiding ? '确认作废' : '确认驳回'"
      :title="voiding ? '作废发票' : '驳回发票'"
      @ok="onRejectConfirm"
    >
      <div class="py-2">
        <div class="mb-2 text-sm">
          {{ voiding ? '作废原因' : '驳回原因' }} <span class="text-red-500">*</span>
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
