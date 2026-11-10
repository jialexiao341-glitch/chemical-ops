<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { AiApi, PurchaseOrderApi } from '#/api';

import { computed, onActivated, onDeactivated, onMounted, onBeforeUnmount, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page, useVbenModal } from '@vben/common-ui';
import { useAccess } from '@vben/access';

import { Button, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  getPurchaseOrderListApi,
  placePurchaseOrderApi,
  submitPurchaseOrderApi,
} from '#/api';
import { createActionProposalBatchApi } from '#/api/ai';
import { getSupplierNameMap } from '#/utils/lookup';
import { applyAiFiltersToList } from '#/utils/ai-list-filters';
import { clearOrderListCopilotContext, setOrderListCopilotContext } from '#/utils/page-copilot-context';

import { useColumns, useGridFormSchema } from './data';
import ApproveModal from './modules/approve.vue';
import CancelModal from './modules/cancel.vue';
import EditModal from './modules/edit.vue';

defineOptions({ name: 'PurchaseOrderList' });
const route = useRoute();
const { hasAccessByCodes } = useAccess();
let lastListFilters: { keyword?: string; status?: string } = {};
let listActive = true;
let listQueryVersion = 0;
onActivated(() => { listActive = true; setOrderListCopilotContext(lastListFilters); });
onDeactivated(() => { listActive = false; clearOrderListCopilotContext(); });
onBeforeUnmount(() => { listActive = false; clearOrderListCopilotContext(); });

const router = useRouter();

const [Approve, approveApi] = useVbenModal({
  connectedComponent: ApproveModal,
  destroyOnClose: true,
});

const [Cancel, cancelApi] = useVbenModal({
  connectedComponent: CancelModal,
  destroyOnClose: true,
});

const [Edit, editApi] = useVbenModal({
  connectedComponent: EditModal,
  destroyOnClose: true,
});

const resolveSupplier = ref<(id?: null | number) => string>(() => '-');
const batchVisible = ref(false);
const batchBusy = ref(false);
const batchResult = ref<AiApi.ActionProposalBatchResult>();
const batchEligible = ref<PurchaseOrderApi.PurchaseOrder[]>([]);
const batchFailures = computed(() => (batchResult.value?.failed ?? []).map((item) => ({
  ...item,
  poNo: batchEligible.value[item.index]?.po_no ?? `第 ${item.index + 1} 条`,
})));

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: [
      { type: 'checkbox' as const, width: 48, align: 'center' as const },
      ...(useColumns(onActionClick, (id) => resolveSupplier.value(id)) as unknown as Record<string, unknown>[]),
    ],
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          const queryVersion = ++listQueryVersion;
          const result = await getPurchaseOrderListApi({
            page: page.currentPage,
            page_size: page.pageSize,
            ...formValues,
          });
          if (queryVersion === listQueryVersion) {
            lastListFilters = { keyword: formValues.keyword || undefined, status: formValues.status || undefined };
            if (listActive) setOrderListCopilotContext(lastListFilters);
          }
          return result;
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
  } as VxeTableGridOptions<PurchaseOrderApi.PurchaseOrder>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<PurchaseOrderApi.PurchaseOrder>) {
  const payload = { id: row.id, operatorId: row.buyer_id, poNo: row.po_no };
  switch (code) {
    case 'edit': {
      editApi.setData({ id: row.id, poNo: row.po_no, order: row }).open();
      break;
    }
    case 'approve': {
      approveApi.setData({ ...payload, action: 'approve' }).open();
      break;
    }
    case 'cancel': {
      cancelApi.setData(payload).open();
      break;
    }
    case 'detail': {
      router.push({
        name: 'PurchaseOrderDetail',
        params: { id: row.id },
      });
      break;
    }
    case 'place': {
      onPlace(row);
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

function onSubmit(row: PurchaseOrderApi.PurchaseOrder) {
  Modal.confirm({
    content: `提交后订单进入审批流程：${row.po_no}`,
    onOk: async () => {
      await submitPurchaseOrderApi(row.id);
      message.success('已提交审批');
      gridApi.query();
    },
    okText: '提交',
    title: '提交采购订单审批',
  });
}

/** 正式下单，后端会回写采购申请明细的已采购数量 */
function onPlace(row: PurchaseOrderApi.PurchaseOrder) {
  Modal.confirm({
    content: `正式下单后订单进入执行状态，并回写采购申请的已采购数量：${row.po_no}`,
    onOk: async () => {
      await placePurchaseOrderApi(row.id);
      message.success('已正式下单');
      gridApi.query();
    },
    okText: '确认下单',
    title: '正式下单',
  });
}

async function createBatchFollowups() {
  const selected = gridApi.grid.getCheckboxRecords() as PurchaseOrderApi.PurchaseOrder[];
  const eligible = selected.filter((row) => row.status === 'ORDERED' || row.status === 'PARTIAL');
  if (!eligible.length) {
    message.warning('请选择已下单或部分到货的订单');
    return;
  }
  batchBusy.value = true;
  try {
    const stamp = Date.now().toString(36);
    const result = await createActionProposalBatchApi(
      eligible.map((row) => ({
        action_type: 'deliveries.followup_draft',
        payload: { order_id: row.id },
        idempotency_key: `followup-batch-${stamp}-${row.id}`,
      })),
    );
    batchResult.value = result;
    batchEligible.value = eligible;
    batchVisible.value = true;
    if (result.created.length) message.success(`已生成 ${result.created.length} 条催办草稿`);
    if (result.failed.length) message.warning(`${result.failed.length} 条未生成，请查看原因`);
    gridApi.grid.clearCheckboxRow();
  } finally {
    batchBusy.value = false;
  }
}

function goToProposals() {
  batchVisible.value = false;
  router.push({ name: 'AiProposals' });
}

onMounted(async () => {
  const suppliers = await getSupplierNameMap();
  resolveSupplier.value = (id) => {
    if (!id) {
      return '-';
    }
    return suppliers.get(id) ?? `#${id}`;
  };
  await applyAiFiltersToList(
    'purchase_orders',
    route.query.ai_filters,
    gridApi.formApi,
  );
  gridApi.query();
});

watch(
  () => route.query.ai_filters,
  async (rawQuery) => {
    if (await applyAiFiltersToList('purchase_orders', rawQuery, gridApi.formApi)) {
      gridApi.query();
    }
  },
);
</script>

<template>
  <Page auto-content-height>
    <Approve @success="gridApi.query()" />
    <Cancel @success="gridApi.query()" />
    <Edit @success="gridApi.query()" />
    <Grid table-title="采购订单">
      <template #toolbar-tools>
        <Button
          v-if="hasAccessByCodes(['procurement.orders.write'])"
          :loading="batchBusy"
          @click="createBatchFollowups"
        >
          批量生成催办草稿
        </Button>
      </template>
      <template #po_no="{ row }">
        <Button
          size="small"
          type="link"
          @click="
            router.push({ name: 'PurchaseOrderDetail', params: { id: row.id } })
          "
        >
          {{ row.po_no }}
        </Button>
      </template>
    </Grid>
    <Modal
      v-model:open="batchVisible"
      :footer="null"
      title="批量生成交期催办草稿"
      width="680"
    >
      <div class="space-y-3 py-2 text-sm">
        <p>
          成功 {{ batchResult?.created.length ?? 0 }} 条，失败
          {{ batchResult?.failed.length ?? 0 }} 条。
        </p>
        <ul
          v-if="batchResult?.created.length"
          class="max-h-60 space-y-1 overflow-auto"
        >
          <li v-for="item in batchResult?.created ?? []" :key="item.confirmation_id">
            订单 #{{ item.resource_id }} · 待确认
          </li>
        </ul>
        <div v-if="batchFailures.length" class="text-red-500">
          <p v-for="item in batchFailures" :key="item.index">
            {{ item.poNo }}：{{ item.error }}
          </p>
        </div>
        <p class="text-muted-foreground">
          草稿尚未保存；请到待确认提案逐条核对并确认。
        </p>
        <div class="flex justify-end gap-2">
          <Button @click="batchVisible = false">关闭</Button>
          <Button type="primary" @click="goToProposals">
            去待确认提案逐条确认
          </Button>
        </div>
      </div>
    </Modal>
  </Page>
</template>
