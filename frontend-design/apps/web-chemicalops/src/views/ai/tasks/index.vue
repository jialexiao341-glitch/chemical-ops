<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { AgentApi } from '#/api';

import { ref } from 'vue';

import { Page } from '@vben/common-ui';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { Button, Modal, Select, message } from 'antdv-next';

import { exportAgentTaskApi, getAgentTaskPageApi } from '#/api';
import AgentChatTask from '../workspace/agent-chat-task.vue';

defineOptions({ name: 'AiTaskHistory' });

const status = ref<AgentApi.Task['status']>();
const selectedTask = ref<AgentApi.Task>();
const detailOpen = ref(false);
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
          const result = await getAgentTaskPageApi(page.currentPage, page.pageSize, status.value);
          return { items: result.items, total: result.total };
        },
      },
    },
    rowConfig: { keyField: 'id' },
    toolbarConfig: { custom: true, export: false, refresh: true, search: false, zoom: true },
  } as VxeTableGridOptions<AgentApi.Task>,
});

function search() { void gridApi.query(); }

async function onActionClick({ code, row }: { code: string; row: AgentApi.Task }) {
  if (code === 'view') {
    selectedTask.value = row;
    detailOpen.value = true;
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
    <Modal v-model:open="detailOpen" title="AI 任务结果" :footer="null" width="760px">
      <AgentChatTask v-if="selectedTask" :task="selectedTask" :busy="false" :show-actions="false" />
    </Modal>
    <div class="flex h-full flex-col gap-3">
      <section class="rounded bg-card p-4">
        <div class="flex w-full flex-wrap items-center justify-between gap-3">
          <span class="font-medium">本人 AI 只读查询任务；导出前会重新检查当前数据权限。</span>
          <div class="ml-auto flex items-center gap-2">
            <Select v-model:value="status" :options="statusOptions" allow-clear placeholder="全部状态" class="w-40" />
            <Button @click="status = undefined; search()">重置</Button>
            <Button type="primary" @click="search">搜索</Button>
          </div>
        </div>
      </section>
      <Grid table-title="AI 任务记录" />
    </div>
  </Page>
</template>
