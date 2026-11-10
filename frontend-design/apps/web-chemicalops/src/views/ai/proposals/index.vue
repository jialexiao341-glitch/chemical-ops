<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { AiApi } from '#/api';

import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import dayjs from 'dayjs';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { Button, Modal, Select, message } from 'antdv-next';

import {
  cancelActionProposalApi,
  confirmActionProposalApi,
  getActionProposalApi,
  getActionProposalPageApi,
  resolveProposalNotificationApi,
  reviseActionProposalApi,
} from '#/api';
import { parseProposalNotificationId } from '#/utils/proposal-notification';
import ActionProposalDetail from '../tasks/ActionProposalDetail.vue';

defineOptions({ name: 'AiProposals' });

const router = useRouter();
const route = useRoute();
const { hasAccessByCodes } = useAccess();

type ProposalScope = 'all' | 'inbox';
const scope = ref<ProposalScope>('inbox');
const selectedProposal = ref<AiApi.ActionProposalRead>();
const selectedProposalId = ref<string>();
const proposalDetailOpen = ref(false);
const proposalLoading = ref(false);
const proposalBusy = ref(false);
const inboxOnly = computed(() => scope.value === 'inbox');
const scopeOptions = [
  { label: '待确认', value: 'inbox' },
  { label: '全部提案', value: 'all' },
];

const proposalStatusLabels: Record<AiApi.ActionProposalRead['status'], string> = {
  CANCELLED: '已取消', EXECUTED: '已执行', EXPIRED: '已过期', INVALIDATED: '资源已变化', PENDING: '待确认',
};
const proposalActionLabels: Record<string, string> = {
  'deliveries.followup_draft': '保存交期催办草稿',
  'exceptions.create_task': '创建异常处理任务',
  'inventory.create_replenishment': '创建补货申请',
  'purchase_order.create_draft': '生成采购订单草稿',
  'purchase_order.submit': '提交采购订单审批',
  'purchase_request.create_draft': '新建采购申请草稿',
  'purchase_request.submit': '提交采购申请',
  'purchase_request.update_draft': '修改采购申请',
  'rfq.create_draft': '询价草稿',
  'rfq.select_quote': '确认中选报价',
  'rfq.send': '发送询价',
};
const proposalColumns = [
  { field: 'confirmation_id', title: '提案编号', minWidth: 190 },
  { field: 'action_type', title: '提案类型', minWidth: 150, formatter: ({ cellValue }: { cellValue: string }) => proposalActionLabels[cellValue] || cellValue },
  { field: 'business_reference', title: '单据编号', minWidth: 160, formatter: ({ cellValue }: { cellValue?: string }) => cellValue || '—' },
  { field: 'status', title: '状态', width: 170, formatter: ({ cellValue, row }: { cellValue: AiApi.ActionProposalRead['status']; row: AiApi.ActionProposalRead }) => row.availability === 'PERMISSION_REVOKED' ? `${proposalStatusLabels[cellValue]} · 权限已失效` : row.availability === 'RESOURCE_UNAVAILABLE' ? '资源不可访问' : proposalStatusLabels[cellValue] },
  { field: 'expires_at', title: '过期时间', width: 180, formatter: ({ cellValue }: { cellValue: string }) => dayjs(cellValue).format('YYYY-MM-DD HH:mm') },
  {
    align: 'center',
    cellRender: {
      attrs: { onClick: onProposalActionClick },
      name: 'CellOperation',
      options: [{ code: 'view', text: '查看' }],
      props: { renderMode: 'menu' },
    },
    field: 'operation', fixed: 'right', title: '操作', width: 90,
  },
];

const [ProposalGrid, proposalGridApi] = useVbenVxeGrid({
  gridOptions: {
    columns: proposalColumns,
    height: 'auto',
    proxyConfig: {
      ajax: {
        query: async ({ page }) => {
          const result = await getActionProposalPageApi(page.currentPage, page.pageSize, inboxOnly.value);
          return { items: result.items, total: result.total };
        },
      },
    },
    rowConfig: { keyField: 'confirmation_id' },
    toolbarConfig: { custom: true, export: false, refresh: true, search: false, zoom: true },
  } as VxeTableGridOptions<AiApi.ActionProposalRead>,
});

function search() { void proposalGridApi.query(); }

function reset() {
  scope.value = 'inbox';
  void proposalGridApi.query();
}

async function openProposal(row: AiApi.ActionProposalRead) {
  selectedProposalId.value = row.confirmation_id;
  selectedProposal.value = undefined;
  proposalDetailOpen.value = true;
  await loadProposal(row.confirmation_id);
}

let proposalLoadVersion = 0;
async function loadProposal(confirmationId: string) {
  const version = ++proposalLoadVersion;
  proposalLoading.value = true;
  try {
    const result = await getActionProposalApi(confirmationId);
    if (version === proposalLoadVersion) selectedProposal.value = result;
  } catch {
    if (version === proposalLoadVersion) {
      selectedProposal.value = undefined;
      message.error('提案详情无法读取，请刷新列表后重试');
    }
  } finally {
    if (version === proposalLoadVersion) proposalLoading.value = false;
  }
}

async function onProposalActionClick({ code, row }: { code: string; row: AiApi.ActionProposalRead }) {
  if (code === 'view') await openProposal(row);
}

async function refreshProposal() {
  if (!selectedProposalId.value || proposalBusy.value || proposalLoading.value) return;
  await loadProposal(selectedProposalId.value);
  void proposalGridApi.query();
}

async function reviseProposal(payload: Record<string, unknown>) {
  const proposal = selectedProposal.value;
  if (!proposal?.requires_user_confirmation || proposalBusy.value) return;
  proposalBusy.value = true;
  try {
    await reviseActionProposalApi(proposal.confirmation_id, proposal.preview_version, payload);
    selectedProposal.value = await getActionProposalApi(proposal.confirmation_id);
    message.success('已保存新的提案预览，请重新核对');
    void proposalGridApi.query();
  } catch {
    message.error('提案修改未完成，正在重新读取服务端状态');
    selectedProposal.value = undefined;
    await loadProposal(proposal.confirmation_id);
  } finally {
    proposalBusy.value = false;
  }
}

function confirmProposal() {
  const proposal = selectedProposal.value;
  if (!proposal?.requires_user_confirmation || proposalBusy.value) return;
  Modal.confirm({
    title: '确认执行提案',
    content: `确认执行提案 ${proposal.confirmation_id} 的当前预览版本 ${proposal.preview_version}？`,
    okText: '确认执行',
    cancelText: '返回核对',
    onOk: async () => {
      proposalBusy.value = true;
      try {
        const result = await confirmActionProposalApi<{ id?: number; po_no?: string }>(
          proposal.confirmation_id,
          proposal.preview_version,
        );
        selectedProposal.value = await getActionProposalApi(proposal.confirmation_id);
        if (proposal.action_type === 'purchase_order.create_draft' && result.po_no) {
          message.success(`采购订单草稿 ${result.po_no} 已生成`);
          if (result.id && hasAccessByCodes(['procurement.orders.read'])) {
            await router.push({ name: 'PurchaseOrderDetail', params: { id: result.id } });
          }
        } else {
          message.success('已按确认的预览执行动作');
        }
        void proposalGridApi.query();
      } catch {
        message.error('提案状态或权限已变化，正在重新读取服务端状态');
        selectedProposal.value = undefined;
        await loadProposal(proposal.confirmation_id);
      } finally {
        proposalBusy.value = false;
      }
    },
  });
}

function cancelProposal() {
  const proposal = selectedProposal.value;
  if (!proposal?.requires_user_confirmation || proposalBusy.value) return;
  Modal.confirm({
    title: '取消动作提案',
    content: `确认取消提案 ${proposal.confirmation_id}？`,
    okText: '取消提案',
    cancelText: '返回',
    onOk: async () => {
      proposalBusy.value = true;
      try {
        await cancelActionProposalApi(proposal.confirmation_id, proposal.preview_version);
        selectedProposal.value = await getActionProposalApi(proposal.confirmation_id);
        message.success('提案已取消');
        void proposalGridApi.query();
      } catch {
        message.error('提案状态或权限已变化，正在重新读取服务端状态');
        selectedProposal.value = undefined;
        await loadProposal(proposal.confirmation_id);
      } finally {
        proposalBusy.value = false;
      }
    },
  });
}

let notificationRouteVersion = 0;
watch(() => route.query.proposal_notification, async (value) => {
  const version = ++notificationRouteVersion;
  const notificationId = parseProposalNotificationId(value);
  if (notificationId === undefined) return;
  try {
    const result = await resolveProposalNotificationApi(notificationId);
    if (version !== notificationRouteVersion) return;
    selectedProposalId.value = result.confirmation_id;
    selectedProposal.value = undefined;
    proposalDetailOpen.value = true;
    await loadProposal(result.confirmation_id);
  } catch {
    if (version === notificationRouteVersion) message.error('提案通知不可访问，请检查当前账号权限');
  } finally {
    if (version === notificationRouteVersion && route.query.proposal_notification === value) {
      const query = { ...route.query };
      delete query.proposal_notification;
      void router.replace({ query });
    }
  }
}, { immediate: true });
</script>

<template>
  <Page auto-content-height>
    <Modal v-model:open="proposalDetailOpen" title="动作提案详情与确认" :footer="null" width="760px">
      <div v-if="proposalLoading" role="status" aria-live="polite" class="py-4 text-center text-muted-foreground">正在读取最新提案状态…</div>
      <ActionProposalDetail
        v-else-if="selectedProposal"
        :proposal="selectedProposal"
        :busy="proposalBusy"
        @cancel="cancelProposal"
        @confirm="confirmProposal"
        @revise="reviseProposal"
      />
      <div v-else-if="!proposalLoading" role="alert" class="py-4 text-center text-sm text-muted-foreground">提案详情读取失败，请刷新状态后重试。</div>
      <div class="mt-2 flex justify-end"><Button :disabled="proposalLoading || proposalBusy" @click="refreshProposal">刷新状态</Button></div>
    </Modal>
    <div class="flex h-full flex-col gap-3">
      <section class="rounded bg-card p-4">
        <div class="flex w-full flex-wrap items-center justify-between gap-3">
          <span class="text-sm text-muted-foreground">仅展示本人可确认的写操作提案；执行前会重新校验权限、资源与预览版本。</span>
          <div class="ml-auto flex items-center gap-2">
            <Select v-model:value="scope" :options="scopeOptions" class="w-36" />
            <Button @click="reset">重置</Button>
            <Button type="primary" @click="search">搜索</Button>
          </div>
        </div>
      </section>
      <ProposalGrid :table-title="inboxOnly ? '待确认提案' : '全部提案'" />
    </div>
  </Page>
</template>
