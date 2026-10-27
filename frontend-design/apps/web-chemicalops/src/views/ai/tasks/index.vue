<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { AgentApi, AiApi } from '#/api';

import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import dayjs from 'dayjs';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { Button, Input, Modal, Select, message } from 'antdv-next';

import {
  cancelAgentTaskApi,
  continueAgentTaskApi,
  createAgentTaskApi,
  exportAgentTaskApi,
  getAgentTaskApi,
  getAgentTaskPageApi,
  cancelActionProposalApi,
  confirmActionProposalApi,
  getActionProposalApi,
  getActionProposalPageApi,
  reviseActionProposalApi,
  resolveProposalNotificationApi,
} from '#/api';
import AgentChatTask from '../workspace/agent-chat-task.vue';
import { acceptTask } from '../workspace/task-view';
import { retryQuestion, taskActionFeedback, taskActions } from './task-actions';
import ActionProposalDetail from './ActionProposalDetail.vue';
import { parseProposalNotificationId } from '#/utils/proposal-notification';
import OperationSuggestionInbox from './OperationSuggestionInbox.vue';

defineOptions({ name: 'AiTaskHistory' });

const router = useRouter();
const route = useRoute();
const { hasAccessByCodes } = useAccess();

const status = ref<AgentApi.Task['status']>();
const inboxOnly = ref(true);
const showProposals = ref(false);
const showSuggestions = ref(useRoute().query.inbox === 'suggestions' && hasAccessByCodes(['operations.exceptions.read']));
const proposalInboxOnly = ref(true);
const selectedTask = ref<AgentApi.Task>();
const selectedProposal = ref<AiApi.ActionProposalRead>();
const selectedProposalId = ref<string>();
const detailOpen = ref(false);
const proposalDetailOpen = ref(false);
const selectedLoading = ref(false);
const proposalLoading = ref(false);
const proposalBusy = ref(false);
const busyTaskId = ref<string>();
const followUpQuestion = ref('');
const selectedBusy = computed(() => Boolean(selectedTask.value && busyTaskId.value === selectedTask.value.id));
const statusOptions = [
  { label: '运行中', value: 'RUNNING' },
  { label: '等待补充', value: 'WAITING_INPUT' },
  { label: '已完成', value: 'SUCCEEDED' },
  { label: '失败', value: 'FAILED' },
  { label: '已取消', value: 'CANCELLED' },
];
const statusLabels: Record<AgentApi.Task['status'], string> = {
  CANCELLED: '已取消', FAILED: '失败', RUNNING: '运行中',
  SUCCEEDED: '已完成', WAITING_INPUT: '等待补充',
};

const columns = [
  { field: 'id', title: '任务编号', minWidth: 190 },
  { field: 'status', title: '状态', width: 110, formatter: ({ cellValue }: { cellValue: AgentApi.Task['status'] }) => statusLabels[cellValue] },
  { field: 'messages', title: '查询内容', minWidth: 240, formatter: ({ cellValue }: { cellValue: string[] }) => cellValue?.at(-1) || '—' },
  { field: 'reply', title: '结果摘要', minWidth: 280, showOverflow: true },
  { field: 'trace', title: '步骤', width: 80, formatter: ({ cellValue }: { cellValue: unknown[] }) => String(cellValue?.length || 0) },
  {
    align: 'center',
    cellRender: {
      attrs: { onClick: onActionClick },
      name: 'CellOperation',
      options: [
        { code: 'view', text: '查看' },
        { code: 'export', text: '导出 CSV', auth: 'ai.workspace.read' },
        { code: 'continue', text: '继续查询', show: (row: AgentApi.Task) => taskActions(row.status).includes('continue'), disabled: () => Boolean(busyTaskId.value) },
        { code: 'cancel', text: '取消任务', danger: true, show: (row: AgentApi.Task) => taskActions(row.status).includes('cancel'), disabled: () => Boolean(busyTaskId.value) },
        { code: 'retry', text: '重新查询', show: (row: AgentApi.Task) => taskActions(row.status).includes('retry') && Boolean(retryQuestion(row)), disabled: () => Boolean(busyTaskId.value) },
      ],
      props: { renderMode: 'menu' },
    },
    field: 'operation', fixed: 'right', title: '操作', width: 100,
  },
];

const proposalStatusLabels: Record<AiApi.ActionProposalRead['status'], string> = {
  CANCELLED: '已取消', EXECUTED: '已执行', EXPIRED: '已过期', INVALIDATED: '资源已变化', PENDING: '待确认',
};
const proposalActionLabels: Record<string, string> = {
  'purchase_request.update_draft': '修改采购申请',
  'purchase_request.submit': '提交采购申请',
  'rfq.create_draft': '询价草稿',
  'rfq.send': '发送询价',
  'rfq.select_quote': '确认中选报价',
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

const [Grid, gridApi] = useVbenVxeGrid({
  gridOptions: {
    columns,
    height: 'auto',
    proxyConfig: {
      ajax: {
        query: async ({ page }) => {
          const result = await getAgentTaskPageApi(page.currentPage, page.pageSize, status.value, inboxOnly.value);
          return { items: result.items, total: result.total };
        },
      },
    },
    rowConfig: { keyField: 'id' },
    toolbarConfig: { custom: true, export: false, refresh: true, search: false, zoom: true },
  } as VxeTableGridOptions<AgentApi.Task>,
});

const [ProposalGrid, proposalGridApi] = useVbenVxeGrid({
  gridOptions: {
    columns: proposalColumns,
    height: 'auto',
    proxyConfig: {
      ajax: {
        query: async ({ page }) => {
          const result = await getActionProposalPageApi(page.currentPage, page.pageSize, proposalInboxOnly.value);
          return { items: result.items, total: result.total };
        },
      },
    },
    rowConfig: { keyField: 'confirmation_id' },
    toolbarConfig: { custom: true, export: false, refresh: true, search: false, zoom: true },
  } as VxeTableGridOptions<AiApi.ActionProposalRead>,
});

function search() { void gridApi.query(); }

function showInbox(inbox: boolean) {
  inboxOnly.value = inbox;
  showSuggestions.value = false;
  showProposals.value = false;
  status.value = undefined;
  void gridApi.query();
}

function showProposalInbox(inbox: boolean) {
  showSuggestions.value = false;
  showProposals.value = true;
  proposalInboxOnly.value = inbox;
  void proposalGridApi.query();
}

async function refreshTask(taskId: string) {
  try {
    const latest = await getAgentTaskApi(taskId);
    if (selectedTask.value?.id === taskId && acceptTask(selectedTask.value, latest)) selectedTask.value = latest;
  } catch {
    message.error('任务状态无法读取，请刷新列表后重试');
  }
}

async function openTask(row: AgentApi.Task) {
  selectedTask.value = row;
  followUpQuestion.value = '';
  detailOpen.value = true;
  selectedLoading.value = true;
  try {
    const latest = await getAgentTaskApi(row.id);
    if (acceptTask(selectedTask.value, latest)) selectedTask.value = latest;
  } catch {
    message.error('任务详情无法读取，请刷新列表后重试');
  } finally {
    if (selectedTask.value?.id === row.id) selectedLoading.value = false;
  }
}

async function refreshSelectedTask() {
  const task = selectedTask.value;
  if (!task || selectedLoading.value || selectedBusy.value) return;
  selectedLoading.value = true;
  await refreshTask(task.id);
  selectedLoading.value = false;
}

async function withTaskBusy(task: AgentApi.Task, operation: () => Promise<AgentApi.Task>, action: 'continue' | 'cancel') {
  if (busyTaskId.value) return;
  busyTaskId.value = task.id;
  try {
    const latest = await operation();
    if (acceptTask(selectedTask.value, latest)) selectedTask.value = latest;
    message.info(taskActionFeedback(action, latest.status));
    void gridApi.query();
  } catch {
    message.error('任务操作未完成，正在重新读取服务端状态');
    await refreshTask(task.id);
    void gridApi.query();
  } finally {
    busyTaskId.value = undefined;
  }
}

function continueTask(data: AgentApi.Continue) {
  const task = selectedTask.value;
  if (!task || !taskActions(task.status).includes('continue') || busyTaskId.value) return;
  void withTaskBusy(task, () => continueAgentTaskApi(task.id, data), 'continue');
  followUpQuestion.value = '';
}

function continueWithText() {
  const task = selectedTask.value;
  const question = followUpQuestion.value.trim();
  if (!task || task.status !== 'WAITING_INPUT' || !question) return;
  continueTask({ question, revision: task.revision });
}

function cancelTask(task: AgentApi.Task) {
  if (!taskActions(task.status).includes('cancel')) return;
  Modal.confirm({
    title: '取消 Agent 任务',
    content: `确认取消任务 ${task.id}？`,
    okText: '取消任务',
    cancelText: '继续运行',
    onOk: () => withTaskBusy(task, () => cancelAgentTaskApi(task.id), 'cancel'),
  });
}

function retryTask(task: AgentApi.Task) {
  const question = retryQuestion(task);
  if (!taskActions(task.status).includes('retry') || !question) return;
  Modal.confirm({
    title: '重新发起查询',
    content: '将使用首次查询内容创建一个新任务，不会复制原任务的结果或执行步骤。',
    okText: '创建新任务',
    cancelText: '返回',
    onOk: async () => {
      if (busyTaskId.value) return;
      busyTaskId.value = task.id;
      try {
        const created = await createAgentTaskApi(question);
        message.success(`已创建新任务 ${created.id}`);
        void gridApi.query();
      } catch {
        message.error('新任务创建失败，请核对查询条件后重试');
      } finally {
        busyTaskId.value = undefined;
      }
    },
  });
}

async function onActionClick({ code, row }: { code: string; row: AgentApi.Task }) {
  if (code === 'view') {
    await openTask(row);
    return;
  }
  if (code === 'continue') {
    await openTask(row);
    return;
  }
  if (code === 'cancel') {
    cancelTask(row);
    return;
  }
  if (code === 'retry') {
    retryTask(row);
    return;
  }
  if (code !== 'export') return;
  try {
    const blob = await exportAgentTaskApi(row.id);
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `agent-task-${row.id}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  } catch {
    message.error('任务结果已不可访问或导出失败，请刷新后重试');
  }
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
    showProposalInbox(true);
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
    <Modal v-model:open="detailOpen" title="AI 任务结果与操作" :footer="null" width="760px">
      <div v-if="selectedLoading" role="status" aria-live="polite" class="py-4 text-center text-muted-foreground">正在读取最新任务状态…</div>
      <template v-else-if="selectedTask">
        <AgentChatTask :task="selectedTask" :busy="selectedBusy" :show-actions="true" @continue="continueTask" />
        <div v-if="selectedTask.status === 'WAITING_INPUT'" class="mt-4 border-t border-border pt-4">
          <Input.TextArea v-model:value="followUpQuestion" :rows="3" :maxlength="1000" :disabled="selectedBusy" placeholder="补充查询条件，继续当前任务" />
          <div class="mt-3 flex justify-end">
            <Button type="primary" :disabled="!followUpQuestion.trim() || selectedBusy" :loading="selectedBusy" @click="continueWithText">继续查询</Button>
          </div>
        </div>
        <div v-else-if="selectedTask.status === 'RUNNING'" class="mt-4 flex justify-end gap-2 border-t border-border pt-4">
          <Button :disabled="selectedBusy" @click="refreshSelectedTask">刷新状态</Button>
          <Button danger :loading="selectedBusy" :disabled="selectedBusy" @click="cancelTask(selectedTask)">取消任务</Button>
        </div>
        <div v-else-if="selectedTask.status === 'FAILED' && retryQuestion(selectedTask)" class="mt-4 flex justify-end border-t border-border pt-4">
          <Button :loading="selectedBusy" :disabled="selectedBusy" @click="retryTask(selectedTask)">重新查询</Button>
        </div>
      </template>
    </Modal>
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
          <span class="font-medium">{{ showSuggestions ? '按权限处理异常运营建议。' : showProposals ? (proposalInboxOnly ? '本人待确认及已失效的采购动作提案。' : '本人采购动作提案记录。') : inboxOnly ? '待补充或失败待处理的本人任务。' : '本人 AI 只读查询任务。' }}<template v-if="!showProposals && !showSuggestions">导出前会重新检查当前数据权限。</template></span>
          <div class="ml-auto flex items-center gap-2">
            <Button v-if="hasAccessByCodes(['operations.exceptions.read'])" :type="showSuggestions ? 'primary' : 'default'" @click="showSuggestions = true; showProposals = false">运营建议</Button>
            <Button :type="!showSuggestions && !showProposals && inboxOnly ? 'primary' : 'default'" @click="showInbox(true)">Agent Inbox · 任务</Button>
            <Button :type="showProposals && proposalInboxOnly ? 'primary' : 'default'" @click="showProposalInbox(true)">待确认提案</Button>
            <Button :type="!showSuggestions && !showProposals && !inboxOnly ? 'primary' : 'default'" @click="showInbox(false)">全部任务</Button>
            <Button :type="showProposals && !proposalInboxOnly ? 'primary' : 'default'" @click="showProposalInbox(false)">全部提案</Button>
            <template v-if="!showSuggestions && !showProposals && !inboxOnly">
              <Select v-model:value="status" :options="statusOptions" allow-clear placeholder="全部状态" class="w-40" />
              <Button @click="status = undefined; search()">重置</Button>
              <Button type="primary" @click="search">搜索</Button>
            </template>
          </div>
        </div>
      </section>
      <OperationSuggestionInbox v-if="showSuggestions" />
      <Grid v-else-if="!showProposals" :table-title="inboxOnly ? 'Agent Inbox · 待处理任务' : 'AI 任务记录'" />
      <ProposalGrid v-else :table-title="proposalInboxOnly ? 'Agent Inbox · 待确认提案' : '动作提案记录'" />
    </div>
  </Page>
</template>
