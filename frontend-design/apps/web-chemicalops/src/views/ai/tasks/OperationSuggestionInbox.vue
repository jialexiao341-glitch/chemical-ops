<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { OperationSuggestion } from '#/api/ai';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAccess } from '@vben/access';
import { Button, Modal, Select, message } from 'antdv-next';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getOperationSuggestionApi, getOperationSuggestionsApi, handleOperationSuggestionApi } from '#/api/ai';
import { requestClient } from '#/api/request';
import { notifyNotificationChanged } from '#/api/core/notification';

defineOptions({ name: 'OperationSuggestionInbox' });
const { hasAccessByCodes } = useAccess();
const router = useRouter();
const status = ref<string>();
const selected = ref<OperationSuggestion>();
const open = ref(false);
const busy = ref(false);
const scanning = ref(false);
interface AlertRun { status: string; started_at: string; result_json: null | Record<string, number>; }
interface AlertStatus { scheduler_enabled: boolean; scheduler_running: boolean; interval_seconds: number; last_run: AlertRun | null; }
const alertStatus = ref<AlertStatus>();
const statusText = computed(() => {
  const state = alertStatus.value;
  if (!state) return '扫描状态暂不可用';
  const scheduler = state.scheduler_running ? '本实例定时扫描已启用' : state.scheduler_enabled ? '本实例定时扫描未运行' : '定时扫描已关闭';
  if (!state.last_run) return `${scheduler} · 尚无运行记录`;
  const run = state.last_run;
  const result = run.status === 'SUCCEEDED' ? '成功' : run.status === 'FAILED' ? '失败' : '运行中';
  const created = Object.entries(run.result_json || {}).filter(([key]) => key.endsWith('_created_count')).reduce((sum, [, value]) => sum + value, 0);
  const details = run.status === 'SUCCEEDED' ? `，新增 ${created} 条异常` : '';
  return `${scheduler} · 最近扫描 ${run.started_at.replace('T', ' ').slice(0, 19)} · ${result}${details}`;
});
async function refreshAlertStatus() {
  try { alertStatus.value = await requestClient.get<AlertStatus>('/jobs/alert-scan/status'); }
  catch { alertStatus.value = undefined; }
}
async function scanAlerts() {
  if (scanning.value) return;
  scanning.value = true;
  try {
    await requestClient.post('/jobs/alert-scan');
    message.success('扫描完成');
    notifyNotificationChanged();
    await gridApi.query();
  } catch { message.error('扫描未全部完成，部分提醒可能已生成，请稍后重试'); }
  finally { await refreshAlertStatus(); scanning.value = false; }
}
onMounted(refreshAlertStatus);
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
    <section class="rounded bg-card p-4 flex flex-wrap items-center justify-between gap-3">
      <span class="text-sm text-muted-foreground" role="status">{{ statusText }}</span>
      <div class="ml-auto flex items-center gap-2"><Button v-if="hasAccessByCodes(['operations.exceptions.write'])" :loading="scanning" @click="scanAlerts">立即扫描</Button><Select v-model:value="status" :options="options" allow-clear placeholder="全部状态" class="w-40" /><Button @click="status = undefined; gridApi.query()">重置</Button><Button type="primary" @click="gridApi.query()">搜索</Button></div>
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
