<script lang="ts" setup>
import type { PurchaseRequestApi } from '#/api';

import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenDrawer } from '@vben/common-ui';

import {
  Descriptions,
  DescriptionsItem,
  Empty,
  Spin,
  Steps,
  Table,
  Tag,
  Button,
  Modal,
  message,
} from 'antdv-next';
import type { StepItem } from 'antdv-next';

import { createActionProposalApi, confirmActionProposalApi, getPurchaseRequestApi } from '#/api';
import { canConfirmActionProposal } from '#/views/ai/workspace/action-proposal-policy';
import { clearPageCopilotContext, setPageCopilotContext } from '#/utils/page-copilot-context';
import {
  PRIORITY_DICT,
  PURCHASE_REQUEST_STATUS_DICT,
} from '#/constants/dictionary';
import { formatAmount, formatDate, formatDateTime, formatQuantity } from '#/utils/format';
import { getUnitNameMap } from '#/utils/lookup';

const detail = ref<PurchaseRequestApi.PurchaseRequest>();
const { hasAccessByCodes } = useAccess();
const canSubmit = computed(() => hasAccessByCodes(['procurement.requests.write']) && ['DRAFT', 'REJECTED'].includes(detail.value?.status ?? ''));
const loading = ref(false);
const unitMap = ref<Map<number, string>>(new Map());
let requestGeneration = 0;

const [Drawer, drawerApi] = useVbenDrawer<null | PurchaseRequestApi.PurchaseRequest>({
  footer: false,
  async onOpenChange(isOpen) {
    if (!isOpen) {
      requestGeneration += 1;
      if (detail.value) clearPageCopilotContext('purchase_request', detail.value.id);
      detail.value = undefined;
      loading.value = false;
      return;
    }
    const generation = ++requestGeneration;
    const data = drawerApi.getData();
    if (detail.value) clearPageCopilotContext('purchase_request', detail.value.id);
    detail.value = undefined;
    if (!data?.id) {
      return;
    }
    loading.value = true;
    try {
      const [request, units] = await Promise.all([
        getPurchaseRequestApi(data.id),
        getUnitNameMap(),
      ]);
      if (generation !== requestGeneration) return;
      detail.value = request;
      setPageCopilotContext({
        objectType: 'purchase_request',
        objectId: request.id,
        question: '这份申请后续采购流程走到哪里了？',
      });
      unitMap.value = units;
    } finally {
      if (generation === requestGeneration) loading.value = false;
    }
  },
});

const itemColumns = [
  { key: 'line_no', title: '行号', width: 70 },
  { key: 'requested_name', title: '物料名称', minWidth: 180 },
  { key: 'quantity', title: '数量', width: 120, align: 'right' as const },
  { key: 'unit_id', title: '单位', width: 90 },
  { key: 'budget_price', title: '预算单价', width: 120, align: 'right' as const },
  { key: 'expected_date', title: '期望到货', width: 120 },
  { key: 'status', title: '明细状态', width: 110 },
];

/** 审批时间线：已发生的审批节点 */
const approvalSteps = computed<StepItem[]>(() =>
  (detail.value?.approvals ?? []).map((item) => ({
    description: item.opinion
      ? `${item.opinion}（${formatDateTime(item.acted_at)}）`
      : formatDateTime(item.acted_at),
    status: item.action === 'REJECT' ? 'error' : 'finish',
    title: `${item.node_name ?? item.node_code ?? '审批'} · ${item.action ?? ''}`,
  })),
);

function unitName(id?: null | number) {
  if (!id) {
    return '-';
  }
  return unitMap.value.get(id) ?? `#${id}`;
}

async function proposeSubmit() {
  const request = detail.value;
  if (!request || !canSubmit.value) return;
  const proposal = await createActionProposalApi('purchase_request.submit', { request_id: request.id }, makeIdempotencyKey());
  if (!canConfirmActionProposal(proposal, proposal.preview_version, false)) {
    message.warning(proposal.blockers.join('；') || '当前申请不能提交，请检查后重试。');
    return;
  }
  Modal.confirm({
    title: '检查并提交采购申请',
    content: `申请 ${request.request_no} 将进入审批中。${proposal.warnings.join('；')}`,
    okText: '确认提交',
    onOk: async () => {
      await confirmActionProposalApi<PurchaseRequestApi.PurchaseRequest>(proposal.confirmation_id, proposal.preview_version);
      detail.value = await getPurchaseRequestApi(request.id);
      message.success('采购申请已提交审批');
    },
  });
}

function makeIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
</script>

<template>
  <Drawer :title="`采购申请 ${detail?.request_no ?? ''}`" class="w-[900px] max-w-[100vw]">
    <Spin :spinning="loading">
      <Empty v-if="!detail && !loading" description="未找到该采购申请" />
      <div v-else-if="detail" class="space-y-6">
        <div v-if="canSubmit" class="flex justify-end">
          <Button type="primary" @click="proposeSubmit">检查并提交</Button>
        </div>
        <Descriptions bordered :column="2" size="small">
          <DescriptionsItem label="申请编号">
            {{ detail.request_no }}
          </DescriptionsItem>
          <DescriptionsItem label="状态">
            <Tag :color="PURCHASE_REQUEST_STATUS_DICT.color(detail.status)">
              {{ PURCHASE_REQUEST_STATUS_DICT.label(detail.status) }}
            </Tag>
          </DescriptionsItem>
          <DescriptionsItem label="优先级">
            <Tag :color="PRIORITY_DICT.color(detail.priority)">
              {{ PRIORITY_DICT.label(detail.priority) }}
            </Tag>
          </DescriptionsItem>
          <DescriptionsItem label="申请部门">
            {{ detail.department_id ?? '-' }}
          </DescriptionsItem>
          <DescriptionsItem label="预算金额">
            {{ formatAmount(detail.budget_amount) }}
            {{ detail.currency_code ?? '' }}
          </DescriptionsItem>
          <DescriptionsItem label="期望到货">
            {{ formatDate(detail.expected_date) }}
          </DescriptionsItem>
          <DescriptionsItem label="提交时间">
            {{ formatDateTime(detail.submitted_at) }}
          </DescriptionsItem>
          <DescriptionsItem label="审批时间">
            {{ formatDateTime(detail.approved_at) }}
          </DescriptionsItem>
          <DescriptionsItem :span="2" label="采购用途">
            {{ detail.purpose }}
          </DescriptionsItem>
          <DescriptionsItem
            v-if="detail.cancel_reason"
            :span="2"
            label="取消原因"
          >
            {{ detail.cancel_reason }}
          </DescriptionsItem>
        </Descriptions>

        <div>
          <div class="mb-3 font-medium">采购明细</div>
          <Table
            :columns="itemColumns"
            :data-source="detail.items ?? []"
            :pagination="false"
            row-key="id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'quantity'">
                {{ formatQuantity(record.quantity) }}
              </template>
              <template v-else-if="column.key === 'unit_id'">
                {{ unitName(record.unit_id) }}
              </template>
              <template v-else-if="column.key === 'budget_price'">
                {{ record.budget_price ? formatAmount(record.budget_price) : '-' }}
              </template>
              <template v-else-if="column.key === 'expected_date'">
                {{ formatDate(record.expected_date) }}
              </template>
            </template>
          </Table>
        </div>

        <div v-if="approvalSteps.length > 0">
          <div class="mb-3 font-medium">审批记录</div>
          <Steps
            :items="approvalSteps"
            direction="vertical"
            size="small"
          />
        </div>
      </div>
    </Spin>
  </Drawer>
</template>
