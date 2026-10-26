<script lang="ts" setup>
import type { PurchaseOrderApi } from '#/api';

import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page, useVbenModal } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { useUserStore } from '@vben/stores';
import { ArrowLeft } from '@vben/icons';

import {
  Button,
  Card,
  Descriptions,
  DescriptionsItem,
  Empty,
  Modal,
  Spin,
  Steps,
  Table,
  Tag,
  Timeline,
  message,
} from 'antdv-next';
import type { StepItem } from 'antdv-next';

import {
  getPurchaseOrderApi,
  placePurchaseOrderApi,
  submitPurchaseOrderApi,
  sendDeliveryFollowupApi,
} from '#/api';
import {
  LINE_STATUS_DICT,
  PURCHASE_ORDER_STATUS_DICT,
} from '#/constants/dictionary';
import {
  formatAmount,
  formatDate,
  formatDateTime,
  formatQuantity,
} from '#/utils/format';
import { getSupplierNameMap, getUnitNameMap } from '#/utils/lookup';

import ApproveModal from './modules/approve.vue';
import CancelModal from './modules/cancel.vue';
import BusinessInsightDrawer from '#/views/ai/workspace/modules/business-insight-drawer.vue';
import { clearPageCopilotContext, setPageCopilotContext } from '#/utils/page-copilot-context';
import { paymentTermsSnapshotLabel } from './item-display';
import ActionProposalDetail from '#/views/ai/tasks/ActionProposalDetail.vue';
import { cancelActionProposalApi, confirmActionProposalApi, createActionProposalApi, getActionProposalApi, reviseActionProposalApi } from '#/api/ai';
import { canPrepareFollowup, useFollowupProposal } from './followup-proposal';
import { canSendFollowup, useFollowupSend } from './followup-send';
import FollowupHistory from './modules/followup-history.vue';

defineOptions({ name: 'PurchaseOrderDetail' });

const route = useRoute();
const router = useRouter();
const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();

const order = ref<PurchaseOrderApi.PurchaseOrder>();
const insightDrawer = ref<{ open: (kind: string, id: number) => void }>();
const loading = ref(false);
const acting = ref(false);
const followupHistory = ref<InstanceType<typeof FollowupHistory>>();
const followupSend = useFollowupSend(sendDeliveryFollowupApi);
const sentFollowupIds = ref(new Set<string>());
const canSendSavedFollowup = computed(() => canSendFollowup(followup.proposal.value, canFollowup.value) &&
  !sentFollowupIds.value.has(followup.proposal.value?.confirmation_id || ''));
const followup = useFollowupProposal({
  prepare: (orderId, key) => createActionProposalApi('deliveries.followup_draft', { order_id: orderId }, key),
  get: getActionProposalApi,
  revise: reviseActionProposalApi,
  confirm: confirmActionProposalApi,
  cancel: cancelActionProposalApi,
});
const canFollowup = computed(() => canPrepareFollowup(
  order.value?.status,
  hasAccessByCodes(['procurement.orders.read']),
  hasAccessByCodes(['procurement.orders.write']),
  hasAccessByCodes(['ai.workspace.read']),
));

async function prepareFollowup() {
  if (order.value && canFollowup.value) await followup.prepare(order.value.id);
}

async function confirmFollowup() {
  if (await followup.confirm()) message.success('催办草稿已保存，尚未向供应商发送');
}
function sendSavedFollowup() {
  const current = followup.proposal.value;
  const currentOrder = order.value;
  if (!current || !currentOrder || !canSendSavedFollowup.value || followupSend.busy.value) return;
  Modal.confirm({
    title: `向 ${resolveSupplier.value(currentOrder.supplier_id)} 发送催办`,
    content: h('div', { class: 'whitespace-pre-wrap break-words' }, String(current.diff.find((item) => item.field === 'followup_message')?.after || '')),
    okText: '确认发送至供应商门户',
    async onOk() {
      try {
        if (await followupSend.send(currentOrder.id, current.confirmation_id, current.preview_version)) {
          sentFollowupIds.value.add(current.confirmation_id);
          message.success('催办已发送至供应商门户');
          followup.open.value = false;
          await followupHistory.value?.open(currentOrder.id);
        }
      } catch {
        await followup.refresh();
        throw new Error('发送未确认成功，请核对最新状态后重试');
      }
    },
  });
}
let viewActive = false;
const resolveSupplier = ref<(id?: null | number) => string>(() => '-');
const resolveUnit = ref<(id?: null | number) => string>(() => '-');

const [Approve, approveApi] = useVbenModal({
  connectedComponent: ApproveModal,
  destroyOnClose: true,
});

const [Cancel, cancelApi] = useVbenModal({
  connectedComponent: CancelModal,
  destroyOnClose: true,
});

/** 订单主流程节点，用于展示执行进度 */
const FLOW_NODES = [
  { key: 'DRAFT', title: '草稿' },
  { key: 'APPROVING', title: '审批中' },
  { key: 'APPROVED', title: '已批准' },
  { key: 'ORDERED', title: '已下单' },
  { key: 'COMPLETED', title: '已完成' },
];

const currentStep = computed(() => {
  const status = order.value?.status ?? 'DRAFT';
  // 部分到货视同已下单之后、完成之前
  const normalized = status === 'PARTIAL' ? 'ORDERED' : status;
  const index = FLOW_NODES.findIndex((node) => node.key === normalized);
  return index < 0 ? 0 : index;
});

const steps = computed<StepItem[]>(() =>
  FLOW_NODES.map((node, index) => ({
    description:
      index === currentStep.value && order.value?.status === 'PARTIAL'
        ? '部分到货'
        : undefined,
    status:
      index < currentStep.value
        ? 'finish'
        : index === currentStep.value
          ? 'process'
          : 'wait',
    title: node.title,
  })),
);

/** 事件轨迹转成时间线 */
const timelineItems = computed(() =>
  [...(order.value?.events ?? [])].reverse().map((event) => ({
    children: `${event.event_type}${
      event.from_status
        ? ` · ${PURCHASE_ORDER_STATUS_DICT.label(event.from_status)} → ${PURCHASE_ORDER_STATUS_DICT.label(event.to_status ?? '')}`
        : ''
    }${event.event_note ? ` · ${event.event_note}` : ''}（${formatDateTime(event.event_time)}）`,
  })),
);

const itemColumns = [
  { key: 'line_no', title: '行号', width: 70 },
  { key: 'product_name_snapshot', title: '物料', minWidth: 180 },
  { key: 'supplier_model_snapshot', title: '供应商型号', width: 150 },
  {
    key: 'order_quantity',
    title: '订购数量',
    width: 120,
    align: 'right' as const,
  },
  { key: 'unit_id', title: '单位', width: 90 },
  {
    key: 'received_quantity',
    title: '已收数量',
    width: 120,
    align: 'right' as const,
  },
  { key: 'unit_price', title: '单价', width: 130, align: 'right' as const },
  { key: 'payment_terms_snapshot', title: '付款条件快照', minWidth: 180 },
  { key: 'planned_arrival_date', title: '计划到货', width: 120 },
  { key: 'status', title: '明细状态', width: 110 },
];

function itemCellValue(
  record: PurchaseOrderApi.OrderItem,
  key?: number | string,
) {
  if (key == null) {
    return '-';
  }
  return (record as unknown as Record<string, unknown>)[String(key)] ?? '-';
}

async function load() {
  const id = Number(route.params.id);
  if (!id) {
    return;
  }
  loading.value = true;
  try {
    const [detail, suppliers, units] = await Promise.all([
      getPurchaseOrderApi(id),
      getSupplierNameMap(),
      getUnitNameMap(),
    ]);
    if (!viewActive) return;
    order.value = detail;
    setPageCopilotContext({
      objectType: 'purchase_order',
      objectId: detail.id,
      question: '这单当前进展和卡点是什么？',
    });
    resolveSupplier.value = (sid) =>
      sid ? (suppliers.get(sid) ?? `#${sid}`) : '-';
    resolveUnit.value = (uid) => (uid ? (units.get(uid) ?? `#${uid}`) : '-');
  } finally {
    loading.value = false;
  }
}

/** 提交、下单这类无参数操作统一走这里，成功后刷新详情 */
async function runAction(action: () => Promise<any>, successText: string) {
  acting.value = true;
  try {
    await action();
    message.success(successText);
    await load();
  } catch {
    // 请求层已统一弹出后端返回的中文错误；不吞掉异常会导致未捕获的 Promise 拒绝。
  } finally {
    acting.value = false;
  }
}

const orderPayload = computed(() => ({
  id: order.value?.id ?? 0,
  operatorId: order.value?.buyer_id ?? 0,
  poNo: order.value?.po_no ?? '',
}));

async function openFollowupFromRoute() {
  if (!order.value) return;
  if (route.query.followup) await followupHistory.value?.open(order.value.id);
  if (typeof route.query.followup_proposal === 'string' && canFollowup.value) {
    await followup.resume(order.value.id, route.query.followup_proposal);
  }
}
watch(() => [route.query.followup, route.query.followup_proposal], openFollowupFromRoute);
onMounted(async () => {
  viewActive = true;
  await load();
  await openFollowupFromRoute();
});
onBeforeUnmount(() => {
  viewActive = false;
  if (order.value) clearPageCopilotContext('purchase_order', order.value.id);
});
</script>

<template>
  <Page auto-content-height>
    <BusinessInsightDrawer ref="insightDrawer" />
    <Approve @success="load" />
    <Cancel @success="load" />
    <FollowupHistory ref="followupHistory" />
    <Modal v-model:open="followup.open.value" title="交期跟进与催办草稿" :footer="null" width="760px" :closable="!followup.busy.value && !followupSend.busy.value" :mask-closable="!followup.busy.value && !followupSend.busy.value" :keyboard="!followup.busy.value && !followupSend.busy.value">
      <div v-if="followup.busy.value" role="status" aria-live="polite" class="py-4 text-center text-muted-foreground">正在读取最新提案状态…</div>
      <ActionProposalDetail
        v-else-if="followup.proposal.value"
        :proposal="followup.proposal.value"
        :busy="followup.busy.value"
        @cancel="followup.cancel"
        @confirm="confirmFollowup"
        @revise="followup.revise"
      />
      <div v-else-if="followup.error.value" role="alert" class="py-4 text-center text-sm text-muted-foreground">草稿准备或操作未完成，请核对订单状态与权限后刷新；原预览不能继续使用。</div>
      <div class="mt-2 flex justify-end gap-2"><Button :disabled="followup.busy.value || followupSend.busy.value" @click="followup.refresh">刷新状态</Button><Button v-if="canSendSavedFollowup" type="primary" :loading="followupSend.busy.value" :disabled="followup.busy.value" @click="sendSavedFollowup">发送至供应商门户</Button></div>
    </Modal>
    <Spin :spinning="loading">
      <Empty v-if="!order && !loading" description="未找到该采购订单" />
      <div v-else-if="order" class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <Button size="small" type="text" @click="router.back()">
              <ArrowLeft class="size-4" />
              返回
            </Button>
            <span class="text-lg font-semibold">{{ order.po_no }}</span>
            <Tag :color="PURCHASE_ORDER_STATUS_DICT.color(order.status)">
              {{ PURCHASE_ORDER_STATUS_DICT.label(order.status) }}
            </Tag>
          </div>
          <div class="flex flex-wrap gap-2">
            <Button v-if="canFollowup" :loading="followup.busy.value" @click="prepareFollowup">交期跟进</Button>
            <Button v-if="hasAccessByCodes(['procurement.orders.read'])" @click="followupHistory?.open(order.id)">催办记录</Button>
            <Button
              v-if="order.id && hasAccessByCodes(['finance.reconciliations.read']) && hasAccessByCodes(['ai.workspace.read'])"
              @click="insightDrawer?.open('finance-difference', order.id)"
            >
              核对财务差异
            </Button>
            <Button
              v-if="order.status === 'DRAFT' && hasAccessByCodes(['procurement.orders.write'])"
              :loading="acting"
              type="primary"
              @click="
                runAction(() => submitPurchaseOrderApi(order!.id), '已提交审批')
              "
            >
              提交审批
            </Button>
            <Button
              v-if="order.status === 'APPROVING' && hasAccessByCodes(['procurement.orders.approve'])"
              :disabled="String(order.buyer_id) === String(userStore.userInfo?.userId)"
              :title="String(order.buyer_id) === String(userStore.userInfo?.userId) ? '不能审批本人经办的订单' : undefined"
              :loading="acting"
              type="primary"
              @click="
                approveApi.setData({ ...orderPayload, action: 'approve' }).open()
              "
            >
              审批通过
            </Button>
            <Button
              v-if="order.status === 'APPROVING' && hasAccessByCodes(['procurement.orders.approve'])"
              :disabled="String(order.buyer_id) === String(userStore.userInfo?.userId)"
              :title="String(order.buyer_id) === String(userStore.userInfo?.userId) ? '不能审批本人经办的订单' : undefined"
              :loading="acting"
              danger
              @click="
                approveApi.setData({ ...orderPayload, action: 'reject' }).open()
              "
            >
              驳回
            </Button>
            <Button
              v-if="order.status === 'APPROVED' && hasAccessByCodes(['procurement.orders.write'])"
              :loading="acting"
              type="primary"
              @click="
                runAction(() => placePurchaseOrderApi(order!.id), '已正式下单')
              "
            >
              正式下单
            </Button>
            <Button
              v-if="['APPROVED', 'APPROVING', 'DRAFT'].includes(order.status) && hasAccessByCodes(['procurement.orders.write'])"
              :loading="acting"
              danger
              @click="cancelApi.setData(orderPayload).open()"
            >
              取消订单
            </Button>
          </div>
        </div>

        <Card title="执行进度">
          <Steps :current="currentStep" :items="steps" />
        </Card>

        <div class="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Card class="xl:col-span-2" title="基本信息">
            <Descriptions bordered :column="2" size="small">
              <DescriptionsItem label="订单编号">
                {{ order.po_no }}
              </DescriptionsItem>
              <DescriptionsItem label="供应商">
                {{ resolveSupplier(order.supplier_id) }}
              </DescriptionsItem>
              <DescriptionsItem label="订单金额">
                {{ formatAmount(order.order_amount) }}
                {{ order.currency_code ?? '' }}
              </DescriptionsItem>
              <DescriptionsItem label="下单日期">
                {{ formatDate(order.order_date) }}
              </DescriptionsItem>
              <DescriptionsItem label="期望到货">
                {{ formatDate(order.expected_arrival_date) }}
              </DescriptionsItem>
              <DescriptionsItem label="供应商确认">
                {{ formatDateTime(order.supplier_confirmed_at) }}
              </DescriptionsItem>
              <DescriptionsItem label="来源采购申请">
                {{ order.source_request_id ?? '-' }}
              </DescriptionsItem>
              <DescriptionsItem label="来源报价">
                {{ order.source_quote_id ?? '-' }}
              </DescriptionsItem>
              <DescriptionsItem :span="2" label="收货地址">
                {{ order.delivery_address || '-' }}
              </DescriptionsItem>
              <DescriptionsItem :span="2" label="备注">
                {{ order.note || '-' }}
              </DescriptionsItem>
              <DescriptionsItem
                v-if="order.cancel_reason"
                :span="2"
                label="取消原因"
              >
                {{ order.cancel_reason }}
              </DescriptionsItem>
            </Descriptions>
          </Card>

          <Card title="订单事件">
            <Empty v-if="timelineItems.length === 0" description="暂无事件记录" />
            <Timeline v-else :items="timelineItems" />
          </Card>
        </div>

        <Card :title="`物料清单（${order.items?.length ?? 0}）`">
          <Table
            :columns="itemColumns"
            :data-source="order.items ?? []"
            :pagination="false"
            :scroll="{ x: 1400 }"
            row-key="id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'order_quantity'">
                {{ formatQuantity(record.order_quantity) }}
              </template>
              <template v-else-if="column.key === 'received_quantity'">
                {{ formatQuantity(record.received_quantity) }}
              </template>
              <template v-else-if="column.key === 'unit_id'">
                {{ resolveUnit(record.unit_id) }}
              </template>
              <template v-else-if="column.key === 'unit_price'">
                {{ formatAmount(record.unit_price, 6) }}
              </template>
              <template v-else-if="column.key === 'payment_terms_snapshot'">
                <span :class="record.payment_terms_snapshot?.trim() ? '' : 'text-muted-foreground'">
                  {{ paymentTermsSnapshotLabel(record.payment_terms_snapshot) }}
                </span>
              </template>
              <template v-else-if="column.key === 'planned_arrival_date'">
                {{ formatDate(record.planned_arrival_date) }}
              </template>
              <template v-else-if="column.key === 'status'">
                <Tag :color="LINE_STATUS_DICT.color(record.status)">
                  {{ LINE_STATUS_DICT.label(record.status) }}
                </Tag>
              </template>
              <template v-else>
                {{ itemCellValue(record, column.key) }}
              </template>
            </template>
          </Table>
        </Card>
      </div>
    </Spin>
  </Page>
</template>
