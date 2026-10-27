<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { OperationExceptionApi } from '#/api';
import { ref } from 'vue';
import { useVbenDrawer } from '@vben/common-ui';
import { Button, Select, message } from 'antdv-next';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getExceptionApi, getMyOperationTaskApi, getMyOperationTasksApi } from '#/api';
import { TASK_STATUS_DICT, PRIORITY_DICT } from '#/constants/dictionary';
import { formatDateTime } from '#/utils/format';
import DetailDrawer from '#/views/operations/exceptions/modules/detail.vue';

defineOptions({ name: 'MyOperationTasks' });
const status = ref('ACTIVE');
const options = [
  { label: '待处理', value: 'ACTIVE' }, { label: '全部状态', value: 'ALL' },
  { label: '待开始', value: 'OPEN' }, { label: '处理中', value: 'PROCESSING' },
  { label: '已完成', value: 'COMPLETED' }, { label: '已取消', value: 'CANCELLED' },
];
const [Detail, detailApi] = useVbenDrawer({ connectedComponent: DetailDrawer, destroyOnClose: true });
const columns = [
  { field: 'exception_no', title: '异常编号', minWidth: 180 },
  { field: 'title', title: '任务', minWidth: 240, showOverflow: true },
  { field: 'priority', title: '优先级', width: 110, formatter: ({ cellValue }: { cellValue: string }) => PRIORITY_DICT.label(cellValue) },
  { field: 'status', title: '状态', width: 110, formatter: ({ cellValue }: { cellValue: string }) => TASK_STATUS_DICT.label(cellValue) },
  { field: 'due_at', title: '截止时间', minWidth: 170, formatter: ({ cellValue }: { cellValue?: string }) => cellValue ? formatDateTime(cellValue) : '—' },
  { field: 'operation', title: '操作', width: 100, fixed: 'right', align: 'center', cellRender: { name: 'CellOperation', attrs: { onClick: ({ row }: { row: OperationExceptionApi.MyTask }) => openTask(row) }, options: [{ code: 'view', text: '查看' }], props: { renderMode: 'menu' } } },
];
const [Grid, gridApi] = useVbenVxeGrid({ gridOptions: {
  columns, height: 'auto', rowConfig: { keyField: 'id' },
  proxyConfig: { ajax: { query: async ({ page }) => getMyOperationTasksApi(page.currentPage, page.pageSize, status.value) } },
  toolbarConfig: { custom: true, export: false, refresh: true, search: false, zoom: true },
} as VxeTableGridOptions<OperationExceptionApi.MyTask> });
async function openTask(row: OperationExceptionApi.MyTask) {
  try {
    const task = await getMyOperationTaskApi(row.id);
    const exception = await getExceptionApi(task.exception_id);
    detailApi.setData({ ...exception, focus_task_id: task.id }).open();
  } catch { message.error('任务不可访问或已改派，请刷新列表'); void gridApi.query(); }
}
</script>
<template>
  <div class="flex h-full flex-col gap-3">
    <section class="rounded bg-card p-4 flex items-center justify-between gap-3">
      <span class="font-medium">分配给当前账号的异常处理任务。</span>
      <div class="flex items-center gap-2"><Select v-model:value="status" :options="options" class="w-40" /><Button type="primary" @click="gridApi.query()">搜索</Button></div>
    </section>
    <Detail @success="gridApi.query()" />
    <Grid table-title="分配给我" />
  </div>
</template>
