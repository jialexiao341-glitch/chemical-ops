<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { AgentApi } from '#/api';

import { computed, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { Button, Input, Modal, Select, message } from 'antdv-next';

import {
  cancelAgentTaskApi,
  continueAgentTaskApi,
  createAgentTaskApi,
  exportAgentTaskApi,
  getAgentTaskApi,
  getAgentTaskPageApi,
} from '#/api';
import AgentChatTask from '../workspace/agent-chat-task.vue';
import { acceptTask } from '../workspace/task-view';
import { retryQuestion, taskActionFeedback, taskActions } from './task-actions';

defineOptions({ name: 'AiTaskHistory' });

const status = ref<AgentApi.Task['status']>();
const inboxOnly = ref(true);
const selectedTask = ref<AgentApi.Task>();
const detailOpen = ref(false);
const selectedLoading = ref(false);
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

function search() { void gridApi.query(); }

function showInbox(inbox: boolean) {
  inboxOnly.value = inbox;
  status.value = undefined;
  void gridApi.query();
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
    <div class="flex h-full flex-col gap-3">
      <section class="rounded bg-card p-4">
        <div class="flex w-full flex-wrap items-center justify-between gap-3">
          <span class="font-medium">{{ inboxOnly ? '待补充或失败待处理的本人任务。' : '本人 AI 只读查询任务。' }}导出前会重新检查当前数据权限。</span>
          <div class="ml-auto flex items-center gap-2">
            <Button :type="inboxOnly ? 'primary' : 'default'" @click="showInbox(true)">Agent Inbox</Button>
            <Button :type="inboxOnly ? 'default' : 'primary'" @click="showInbox(false)">全部任务</Button>
            <template v-if="!inboxOnly">
              <Select v-model:value="status" :options="statusOptions" allow-clear placeholder="全部状态" class="w-40" />
              <Button @click="status = undefined; search()">重置</Button>
              <Button type="primary" @click="search">搜索</Button>
            </template>
          </div>
        </div>
      </section>
      <Grid :table-title="inboxOnly ? 'Agent Inbox · 待处理任务' : 'AI 任务记录'" />
    </div>
  </Page>
</template>
