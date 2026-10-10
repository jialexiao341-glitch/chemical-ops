<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { FinanceApi } from '#/api';

import { onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { useAccess } from '@vben/access';
import { Page, useVbenModal } from '@vben/common-ui';
import { Plus } from '@vben/icons';
import { useUserStore } from '@vben/stores';

import { Button, Input, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  approvePaymentApi,
  getPaymentListApi,
  markPaymentPaidApi,
  rejectPaymentApi,
} from '#/api';
import { getSupplierNameMap } from '#/utils/lookup';

import { useColumns, useGridFormSchema } from './data';
import CreateModal from './modules/create.vue';
import FinanceSourceDetail from '#/views/ai/workspace/modules/finance-source-detail.vue';

defineOptions({ name: 'PaymentList' });
const route = useRoute();
const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();
const canWritePayments = hasAccessByCodes(['finance.payments.write']);
const canApprovePayments = hasAccessByCodes(['finance.payments.approve']);
const financeSourceDetail = ref<InstanceType<typeof FinanceSourceDetail>>();

const [Create, createApi] = useVbenModal({
  connectedComponent: CreateModal,
  destroyOnClose: true,
});

const resolveSupplier = ref<(id?: null | number) => string>(() => '-');

/** 驳回弹窗（原因必填） */
const rejectVisible = ref(false);
const rejectReason = ref('');
const rejectRow = ref<FinanceApi.Payment>();

/** 登记付款弹窗（外部流水号必填） */
const paidVisible = ref(false);
const paidRef = ref('');
const paidNote = ref('');
const paidRow = ref<FinanceApi.Payment>();

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
          return await getPaymentListApi({
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
  } as VxeTableGridOptions<FinanceApi.Payment>,
});

function runApprove(row: FinanceApi.Payment) {
  Modal.confirm({
    content: `确认审批通过付款 ${row.payment_no}（${row.amount} ${row.currency_code}）？`,
    okText: '审批通过',
    onOk: async () => {
      if (!hasAccessByCodes(['finance.payments.approve'])) return;
      await approvePaymentApi(row.id);
      message.success('付款申请已批准');
      gridApi.query();
    },
    title: '审批付款申请',
  });
}

function openReject(row: FinanceApi.Payment) {
  rejectRow.value = row;
  rejectReason.value = '';
  rejectVisible.value = true;
}

async function onRejectConfirm() {
  if (!hasAccessByCodes(['finance.payments.approve'])) return;
  if (!rejectReason.value.trim()) {
    message.warning('请填写驳回原因');
    return;
  }
  if (!rejectRow.value) {
    return;
  }
  try {
    await rejectPaymentApi(rejectRow.value.id, rejectReason.value.trim());
    message.success('付款申请已驳回');
    rejectVisible.value = false;
    gridApi.query();
  } catch {
    // 请求层已弹出错误，保持弹窗打开
  }
}

function openPaid(row: FinanceApi.Payment) {
  paidRow.value = row;
  paidRef.value = '';
  paidNote.value = '';
  paidVisible.value = true;
}

async function onPaidConfirm() {
  if (!hasAccessByCodes(['finance.payments.write'])) return;
  if (!paidRef.value.trim()) {
    message.warning('请填写外部流水号');
    return;
  }
  if (!paidRow.value) {
    return;
  }
  try {
    await markPaymentPaidApi(paidRow.value.id, {
      note: paidNote.value.trim() || undefined,
      transaction_ref: paidRef.value.trim(),
    });
    message.success('已登记付款结果');
    paidVisible.value = false;
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
  openAiPayment(route.query.ai_record_id, route.query.ai_record_type);
});

function openAiPayment(rawId: unknown, rawType: unknown) {
  const id = Number(rawId);
  if (rawType !== 'payments' || !Number.isInteger(id) || id <= 0) return;
  financeSourceDetail.value?.open({ id, kind: 'payments' });
}

watch(
  () => [route.query.ai_record_id, route.query.ai_record_type],
  ([id, kind]) => openAiPayment(id, kind),
);
</script>

<template>
  <Page auto-content-height>
    <FinanceSourceDetail ref="financeSourceDetail" />
    <Create @success="gridApi.query()" />
    <Grid table-title="付款管理">
      <template #toolbar-tools>
        <Button v-if="canWritePayments" type="primary" @click="createApi.open()">
          <Plus class="size-5" />
          发起付款
        </Button>
      </template>
      <template #operation="{ row }">
        <div class="flex flex-wrap justify-center gap-0">
          <Button
            v-if="canApprovePayments"
            :disabled="row.status !== 'REQUESTED' || String(row.requested_by) === String(userStore.userInfo?.userId)"
            :title="String(row.requested_by) === String(userStore.userInfo?.userId) ? '本人经办记录须由他人审批或复核' : row.status !== 'REQUESTED' ? '当前状态不可审批或复核' : undefined"
            size="small"
            type="link"
            @click="runApprove(row)"
          >
            审批通过
          </Button>
          <Button
            v-if="canApprovePayments"
            :disabled="row.status !== 'REQUESTED' || String(row.requested_by) === String(userStore.userInfo?.userId)"
            :title="String(row.requested_by) === String(userStore.userInfo?.userId) ? '本人经办记录须由他人审批或复核' : row.status !== 'REQUESTED' ? '当前状态不可审批或复核' : undefined"
            danger
            size="small"
            type="link"
            @click="openReject(row)"
          >
            驳回
          </Button>
          <Button
            v-if="canWritePayments"
            :disabled="row.status !== 'APPROVED'"
            :title="row.status !== 'APPROVED' ? '当前状态不支持此操作' : undefined"
            size="small"
            type="link"
            @click="openPaid(row)"
          >
            登记付款
          </Button>
        </div>
      </template>
    </Grid>

    <!-- 驳回弹窗（原因必填） -->
    <Modal
      v-model:open="rejectVisible"
      :ok-button-props="{ disabled: !hasAccessByCodes(['finance.payments.approve']) }"
      cancel-text="取消"
      ok-text="确认驳回"
      title="驳回付款申请"
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

    <!-- 登记付款弹窗（流水号必填） -->
    <Modal
      v-model:open="paidVisible"
      :ok-button-props="{ disabled: !hasAccessByCodes(['finance.payments.write']) }"
      cancel-text="取消"
      ok-text="确认登记"
      title="登记人工核对的付款结果"
      @ok="onPaidConfirm"
    >
      <div class="space-y-3 py-2">
        <div class="text-sm text-amber-700">
          此操作只记录人工核对的流水信息，不会连接银行或发送支付指令；未取得银行回执前不要登记为已付款。
        </div>
        <div>
          <div class="mb-1 text-sm">
            外部流水号 <span class="text-red-500">*</span>
          </div>
          <Input
            v-model:value="paidRef"
            :maxlength="128"
            placeholder="银行流水号或交易凭证号"
          />
        </div>
        <div>
          <div class="mb-1 text-sm">备注</div>
          <Input.TextArea
            v-model:value="paidNote"
            :maxlength="1000"
            :rows="2"
            placeholder="备注（选填）"
          />
        </div>
      </div>
    </Modal>
  </Page>
</template>
