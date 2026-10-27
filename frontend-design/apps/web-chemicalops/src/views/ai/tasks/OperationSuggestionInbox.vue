<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { OperationSuggestion } from '#/api/ai';
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAccess } from '@vben/access';
import { Button, Modal, Select, message } from 'antdv-next';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getOperationSuggestionApi, getOperationSuggestionsApi, handleOperationSuggestionApi } from '#/api/ai';

defineOptions({ name: 'OperationSuggestionInbox' });
const { hasAccessByCodes } = useAccess();
const router = useRouter();
const status = ref<string>();
const selected = ref<OperationSuggestion>();
const open = ref(false);
const busy = ref(false);
const labels: Record<OperationSuggestion['status'], string> = { OPEN: '待处理', IGNORED: '已忽略', CLOSED: '已关闭', HANDED_OFF: '已转人工' };
const options = Object.entries(labels).map(([value, label]) => ({ value, label }));
const columns = [
  { field: 'exception_no', title: '异常编号', minWidth: 180 },
  { field: 'title', title: '建议', minWidth: 220 },
  { field: 'status', title: '状态', width: 120, formatter: ({ cellValue }: { cellValue: OperationSuggestion['status'] }) => labels[cellValue] },
  { field: 'created_at', title: '创建时间', minWidth: 180 },
  { field: 'operation', title: '操作', width: 100, fixed: 'right', align: 'center', cellRender: { name: 'CellOperation', attrs: { onClick: ({ row }: { row: OperationSuggestion }) => view(row) }, options: [{ code: 'view', text: '查看' }], props: { renderMode: 'menu' } } },
];
const [Grid, gridApi] = useVbenVxeGrid({ gridOptions: {
  columns, height: 'auto', rowConfig: { keyField: 'id' },
  proxyConfig: { ajax: { query: async ({ page }) => getOperationSuggestionsApi(page.currentPage, page.pageSize, status.value) } },
  toolbarConfig: { custom: true, export: false, refresh: true, search: false, zoom: true },
} as VxeTableGridOptions<OperationSuggestion> });
async function view(row: OperationSuggestion) {
  selected.value = undefined; open.value = true; busy.value = true;
  try { selected.value = await getOperationSuggestionApi(row.id); }
  catch { message.error('建议详情读取失败'); }
  finally { busy.value = false; }
}
async function handle(action: 'ignore' | 'close' | 'handoff') {
  if (!selected.value || busy.value) return;
  busy.value = true;
  try { selected.value = await handleOperationSuggestionApi(selected.value.id, action); message.success('建议状态已更新'); void gridApi.query(); }
  catch { message.error('操作失败，请刷新后重试'); }
  finally { busy.value = false; }
}
</script>
<template>
  <div class="flex h-full flex-col gap-3">
    <section class="rounded bg-card p-4 flex items-center justify-between gap-3">
      <span class="font-medium">按当前异常权限查看和处理运营建议。</span>
      <div class="flex items-center gap-2"><Select v-model:value="status" :options="options" allow-clear placeholder="全部状态" class="w-40" /><Button @click="status = undefined; gridApi.query()">重置</Button><Button type="primary" @click="gridApi.query()">搜索</Button></div>
    </section>
    <Grid table-title="Agent Inbox · 运营建议" />
    <Modal v-model:open="open" title="运营建议详情" :footer="null" width="760px">
      <div v-if="busy && !selected" role="status">正在读取建议…</div>
      <template v-else-if="selected">
        <div class="space-y-3"><p>异常编号：<Button type="link" @click="router.push({ path: '/operations/exceptions', query: { exception_id: selected.exception_id } })">{{ selected.exception_no }}</Button></p><p>建议：{{ selected.title }}</p><p>状态：{{ labels[selected.status] }}（异常状态：{{ selected.exception_status }}）</p><p class="whitespace-pre-wrap">{{ selected.content }}</p><p v-if="selected.task_id">人工处理任务编号：{{ selected.task_id }}</p></div>
        <div v-if="selected.status === 'OPEN'" class="mt-4"><Button @click="router.push({ path: '/ai/workspace', query: { prompt: selected.instruction } })">让 Agent 处理</Button></div>
        <div v-if="selected.status === 'OPEN' && hasAccessByCodes(['operations.exceptions.write'])" class="mt-4 flex justify-end gap-2 border-t border-border pt-4"><Button :disabled="busy" @click="handle('ignore')">忽略</Button><Button :disabled="busy" @click="handle('close')">关闭</Button><Button v-if="!(['CLOSED', 'CANCELLED'].includes(selected.exception_status))" type="primary" :loading="busy" @click="handle('handoff')">转人工处理</Button></div>
      </template>
    </Modal>
  </div>
</template>
