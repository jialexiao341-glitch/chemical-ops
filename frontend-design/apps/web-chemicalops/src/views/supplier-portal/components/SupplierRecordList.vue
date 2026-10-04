<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';

import { nextTick, ref, watch } from 'vue';
import { Page } from '@vben/common-ui';
import { IconifyIcon } from '@vben/icons';
import { Button, Dropdown, message } from 'antdv-next';
import { useVbenVxeGrid } from '#/adapter/vxe-table';

const props = defineProps<{
  title: string;
  subtitle: string;
  columns: any[];
  rows: any[];
  total: number;
  loading?: boolean;
  page: number;
  pageSize: number;
  keyword: string;
  status: string;
  statusOptions: { label: string; value: string }[];
  scrollX?: number;
  fetchRecords: () => Promise<void>;
}>();

const emit = defineEmits<{
  (event: 'update:keyword', value: string): void;
  (event: 'update:status', value: string): void;
  (event: 'update:page', value: number): void;
  (event: 'update:pageSize', value: number): void;
  (event: 'selection-change', keys: number[]): void;
}>();

const batchOpen = ref(false);
const menuRowId = ref<number>();
const initialStatus = props.status;
const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: [
      {
        component: 'Input', fieldName: 'keyword', label: '关键字',
        defaultValue: props.keyword,
        componentProps: { allowClear: true, class: 'w-full', placeholder: '请输入单据编号或关键词' },
      },
      {
        component: 'Select', fieldName: 'status', label: '状态',
        defaultValue: initialStatus,
        componentProps: { allowClear: true, class: 'w-full', options: props.statusOptions, placeholder: '全部状态' },
      },
    ],
  },
  gridOptions: {
    columns: getColumns(props.columns),
    fit: true,
    height: 'auto',
    keepSource: true,
    pagerConfig: { pageSize: props.pageSize, pageSizes: [10, 20, 30, 50, 100] },
    proxyConfig: {
      ajax: {
        query: async ({ page }, values) => {
          menuRowId.value = undefined;
          emit('update:page', page.currentPage);
          emit('update:pageSize', page.pageSize);
          emit('update:keyword', String(values.keyword ?? ''));
          emit('update:status', String(values.status ?? ''));
          await nextTick();
          await props.fetchRecords();
          await nextTick();
          return { items: props.rows, total: props.total };
        },
      },
    },
    rowConfig: { keyField: 'id' },
    toolbarConfig: { custom: true, export: false, refresh: true, search: true, zoom: true },
  } as VxeTableGridOptions,
  gridEvents: {
    checkboxChange: notifySelection,
    checkboxAll: notifySelection,
  },
});

function notifySelection() {
  emit('selection-change', gridApi.grid.getCheckboxRecords().map((row: { id: number }) => row.id));
}
function clearSelection() {
  batchOpen.value = false;
  gridApi.grid.clearCheckboxRow();
  notifySelection();
}
function exportSelection() {
  batchOpen.value = false;
  const rows = gridApi.grid.getCheckboxRecords();
  if (!rows.length) { message.warning('请先勾选记录'); return; }
  const columns = props.columns.filter((column) => column.key !== '__action');
  const escapeCell = (value: unknown) => {
    let text = String(value ?? '');
    if (/^[=+@-]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const lines = [columns.map((column) => escapeCell(column.title)).join(','),
    ...rows.map((row: Record<string, unknown>) => columns.map((column) => escapeCell(column.key === 'item_count' ? (row.items as unknown[] | undefined)?.length : row[column.key])).join(','))];
  const url = URL.createObjectURL(new Blob(['\uFEFF', lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${props.title}.csv`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// 写入弹窗保存后更新已显示数据，不额外发起一次查询。
watch(() => props.rows, (rows) => { void gridApi.grid?.loadData(rows); });
watch(() => props.total, (total) => gridApi.setGridOptions({ pagerConfig: { total } }));
watch(() => props.loading, (loading) => gridApi.setLoading(Boolean(loading)));
watch(() => props.columns, (columns) => gridApi.setGridOptions({ columns: getColumns(columns) }));

function getColumns(columns: typeof props.columns): VxeTableGridOptions['columns'] {
  return [{ type: 'checkbox', width: 48, align: 'center' }, ...columns.map((column) => ({
    field: column.key, title: column.title,
    width: column.key === '__action' ? column.width : undefined,
    minWidth: column.key === '__action' ? undefined : column.width,
    align: column.align ?? 'center',
    fixed: column.key === '__action' ? 'right' as const : undefined, slots: { default: 'supplier-cell' },
  }))];
}
</script>

<template>
  <Page auto-content-height>
    <Grid :table-title="title">
      <template #toolbar-tools>
        <Dropdown :open="batchOpen" :trigger="['click']" placement="bottomRight" @open-change="batchOpen = $event">
          <Button class="inline-flex items-center gap-2">批量操作 <IconifyIcon class="size-4 text-slate-500" icon="lucide:chevron-down" /></Button>
          <template #popupRender>
            <div class="supplier-record-menu">
              <button type="button" @click="exportSelection">导出所选</button>
              <button type="button" @click="clearSelection">清除勾选</button>
            </div>
          </template>
        </Dropdown>
        <slot name="toolbar" />
      </template>
      <template #supplier-cell="{ column, row }">
        <Dropdown v-if="column.field === '__action'" :open="menuRowId === row.id" :trigger="['click']" placement="bottomRight" @open-change="menuRowId = $event ? row.id : undefined">
          <Button size="small" type="link"><IconifyIcon class="size-5" icon="ant-design:more-outlined" />更多</Button>
          <template #popupRender>
            <div class="supplier-record-menu supplier-record-actions" @click="menuRowId = undefined">
              <slot name="bodyCell" :column="{ key: column.field }" :record="row" />
            </div>
          </template>
        </Dropdown>
        <slot v-else name="bodyCell" :column="{ key: column.field }" :record="row" />
      </template>
    </Grid>
  </Page>
</template>

<style scoped>
.supplier-record-menu { min-width: 154px; padding: 5px; border: 1px solid hsl(var(--border)); border-radius: 9px; background: hsl(var(--background)); box-shadow: 0 10px 28px #0f27401f; }
.supplier-record-menu > button { display: block; width: 100%; padding: 8px 11px; border: 0; border-radius: 5px; background: transparent; color: hsl(var(--foreground)); text-align: left; font-size: 14px; line-height: 20px; cursor: pointer; }
.supplier-record-menu > button:hover { background: hsl(var(--muted)); }
.supplier-record-actions :deep(.ant-btn) { display: flex; width: 100%; justify-content: flex-start; height: auto; padding: 8px 11px; }
.supplier-record-actions :deep(.flex) { flex-direction: column; }
</style>
