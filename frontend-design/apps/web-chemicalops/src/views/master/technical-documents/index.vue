<script lang="ts" setup>
import { fetchAllPages } from '#/utils/pagination';
import type { OnActionClickParams, VxeTableGridOptions } from '#/adapter/vxe-table';
import type { TechnicalDocumentSource } from '#/api';

import { computed, onMounted, ref } from 'vue';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getChemicalListApi, getTechnicalDocumentsApi, startTechnicalDocumentFetchApi, startTechnicalDocumentIngestApi } from '#/api';

import { Button, Select, message } from 'antdv-next';
import { formatDateTime } from '#/utils/format';

import PreviewDrawerContent from './modules/preview.vue';
import TaskRunsDrawer from './modules/task-runs-drawer.vue';
import { filterDirectory } from './directory';

defineOptions({ name: 'TechnicalDocuments' });

type ChemicalRecord = Awaited<ReturnType<typeof getChemicalListApi>>['items'][number];

const chemicals = ref<ChemicalRecord[]>([]);
const chemicalsLoading = ref(false);
const selectedCas = ref<string>();
const casNo = computed(() => selectedCas.value || '');
const directorySources = ref<TechnicalDocumentSource[]>([]);
const chemicalOptions = computed(() => {
  const options = new Map<string, { label: string; value: string }>();
  for (const chemical of chemicals.value) {
    const cas = chemical.cas_no?.trim();
    if (cas) options.set(cas, { label: [chemical.chemical_name, chemical.english_name, cas, chemical.alias_text].filter(Boolean).join(' · '), value: cas });
  }
  for (const source of directorySources.value) {
    const title = source.name_zh || source.title || '';
    const name = /^(?:material )?safety data sheet$|^technical data sheet$/i.test(title.trim()) ? '' : title;
    const previous = options.get(source.cas_no);
    if (!previous || (previous.label === source.cas_no && name)) {
      options.set(source.cas_no, { label: [name, source.cas_no].filter(Boolean).join(' · '), value: source.cas_no });
    }
  }
  return [...options.values()];
});
const docTypes = ref<string[]>(['msds', 'tds']);
const documentTypeOptions = [
  { label: 'MSDS', value: 'msds' },
  { label: 'TDS', value: 'tds' },
];
const busy = ref(false);
const { hasAccessByCodes } = useAccess();
const canReadTechnicalDocuments = hasAccessByCodes(['master.chemicals.read']);
const canWriteTechnicalDocuments = hasAccessByCodes(['master.chemicals.write']);
const [TaskDrawer, taskDrawerApi] = useVbenDrawer({
  connectedComponent: TaskRunsDrawer,
  destroyOnClose: false,
});
const [PreviewDrawer, previewDrawerApi] = useVbenDrawer({
  connectedComponent: PreviewDrawerContent,
  destroyOnClose: true,
});

const columns = [
  { field: 'name_zh', title: '化学品', minWidth: 140, formatter: ({ row }: { row: TechnicalDocumentSource }) => row.name_zh || row.title || row.cas_no },
  { field: 'cas_no', title: 'CAS 号', width: 130 },
  { field: 'doc_type', title: '资料类型', width: 100, formatter: ({ row }: { row: TechnicalDocumentSource }) => `${row.doc_type.toUpperCase()} · ${row.extension.toUpperCase()}` },
  { field: 'object_key', title: 'MinIO 对象', minWidth: 180, formatter: ({ row }: { row: TechnicalDocumentSource }) => `${row.source_bucket}/${row.object_key}` },
  { field: 'parse_status', title: '知识库状态', width: 130, formatter: ({ row }: { row: TechnicalDocumentSource }) => ({ PARSED: '已写入', THIN: '内容偏少', REJECTED: '质检未通过', PENDING: row.ingestible ? '待写入' : '仅文件预览' })[row.parse_status] || row.parse_status },
  { field: 'file_size', title: '文件大小', width: 110, formatter: ({ cellValue }: { cellValue: number }) => cellValue < 1024 * 1024 ? `${Math.ceil(cellValue / 1024)} KB` : `${(cellValue / 1024 / 1024).toFixed(1)} MB` },
  { field: 'section_count', title: '章节数', width: 90 },
  { field: 'updated_at', title: '更新时间', width: 180, formatter: ({ cellValue }: { cellValue?: null | string }) => formatDateTime(cellValue) },
  {
    align: 'center',
    cellRender: {
      attrs: { onClick: onActionClick },
      name: 'CellOperation',
      options: [{ code: 'preview', text: '预览', auth: 'master.chemicals.read' }],
      props: { renderMode: 'menu' },
    },
    field: 'operation',
    fixed: 'right',
    title: '操作',
    width: 90,
  },
];

const [Grid, gridApi] = useVbenVxeGrid({
  gridOptions: {
    columns,
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }) => {
          const rows = await getTechnicalDocumentsApi();
          directorySources.value = rows;
          const filteredRows = filterDirectory(rows, undefined, casNo.value || undefined)
            .filter((row) => !docTypes.value.length || docTypes.value.includes(row.doc_type));
          const start = (page.currentPage - 1) * page.pageSize;
          return { items: filteredRows.slice(start, start + page.pageSize), total: filteredRows.length };
        },
      },
    },
    rowConfig: { keyField: 'object_key' },
    toolbarConfig: { custom: true, export: false, refresh: true, search: false, zoom: true },
  } as VxeTableGridOptions<TechnicalDocumentSource>,
});

function onActionClick({ code, row }: OnActionClickParams<TechnicalDocumentSource>) {
  if (code === 'preview') previewDrawerApi.setData(row).open();
}

function resetSearch() {
  selectedCas.value = undefined;
  docTypes.value = ['msds', 'tds'];
  void gridApi.query();
}

function searchDocuments() {
  void gridApi.query();
}

async function startFetch() {
  if (!canWriteTechnicalDocuments) return;
  if (!/^\d{2,7}-\d{2}-\d$/.test(casNo.value.trim()) || !chemicals.value.some((item) => item.cas_no?.trim() === casNo.value)) {
    message.warning('请先按名称搜索并选择已维护 CAS 号的化学品');
    return;
  }
  if (!docTypes.value.length) {
    message.warning('至少选择 MSDS 或 TDS');
    return;
  }
  busy.value = true;
  try {
    await startTechnicalDocumentFetchApi({ cas_no: casNo.value.trim(), doc_types: docTypes.value });
    message.success('原始文件拉取任务已启动；完成后可单独写入知识库');
    taskDrawerApi.open();
  } finally {
    busy.value = false;
  }
}

async function startIngest() {
  if (!canWriteTechnicalDocuments) return;
  if (!/^\d{2,7}-\d{2}-\d$/.test(casNo.value.trim()) || !chemicals.value.some((item) => item.cas_no?.trim() === casNo.value)) {
    message.warning('请先按名称搜索并选择已维护 CAS 号的化学品');
    return;
  }
  if (!docTypes.value.length) {
    message.warning('至少选择 MSDS 或 TDS');
    return;
  }
  busy.value = true;
  try {
    await startTechnicalDocumentIngestApi({ cas_no: casNo.value.trim(), doc_types: docTypes.value });
    message.success('知识库写入任务已启动');
    taskDrawerApi.open();
  } finally {
    busy.value = false;
  }
}

async function loadChemicalOptions() {
  chemicalsLoading.value = true;
  try {
    const firstPage = await fetchAllPages((page) => getChemicalListApi({ page, page_size: 100, status: 'ACTIVE' }));
    chemicals.value = firstPage.items;
  } catch {
    chemicals.value = [];
  } finally {
    chemicalsLoading.value = false;
  }
}

onMounted(() => {
  void gridApi.query();
  void loadChemicalOptions();
});
</script>

<template>
  <Page auto-content-height>
    <TaskDrawer />
    <PreviewDrawer />
    <div class="flex h-full flex-col gap-3">
      <section class="rounded bg-card p-4">
        <div class="flex w-full flex-wrap items-center gap-x-4 gap-y-2">
          <div class="flex min-w-0 flex-wrap items-center gap-2">
            <span class="shrink-0">化学品</span>
            <Select
              v-model:value="selectedCas"
              :options="chemicalOptions"
              :style="{ width: 'clamp(220px, 22vw, 320px)', maxWidth: '100%' }"
              :loading="chemicalsLoading"
              allow-clear
              show-search
              option-filter-prop="label"
              placeholder="搜索化学品名称或 CAS 号"
            />
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <span class="shrink-0">资料类型</span>
            <Select
              v-model:value="docTypes"
              class="w-44"
              mode="multiple"
              :options="documentTypeOptions"
              placeholder="全部类型"
            />
          </div>
          <div class="ml-auto flex shrink-0 items-center gap-2">
            <Button @click="resetSearch">重置</Button>
            <Button type="primary" @click="searchDocuments">搜索</Button>
          </div>
        </div>
      </section>

      <Grid table-title="技术资料库">
        <template #toolbar-tools>
          <Button v-if="canWriteTechnicalDocuments" :loading="busy" @click="startFetch">拉取数据</Button>
          <Button v-if="canWriteTechnicalDocuments" class="ml-2" type="primary" :loading="busy" @click="startIngest">写入知识库</Button>
          <Button v-if="canReadTechnicalDocuments" class="ml-2" @click="taskDrawerApi.open()">处理任务</Button>
        </template>
      </Grid>
    </div>
  </Page>
</template>
