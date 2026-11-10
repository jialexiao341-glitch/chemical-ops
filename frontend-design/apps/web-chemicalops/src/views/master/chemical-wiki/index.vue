<script setup lang="ts">
import type { OnActionClickParams, VxeTableGridOptions } from '#/adapter/vxe-table';
import type { ChemicalWikiEntry } from '#/api/chemical-wiki';

import { ref } from 'vue';
import { Page, useVbenDrawer } from '@vben/common-ui';
import { Button, Input, Select } from 'antdv-next';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getChemicalWikiEntriesApi } from '#/api/chemical-wiki';
import WikiPreview from './preview.vue';

defineOptions({ name: 'ChemicalWiki' });
type Row = ChemicalWikiEntry & { doc_type: 'msds' | 'tds'; row_key: string };
const keyword = ref('');
const docType = ref<string>();
const [Preview, previewApi] = useVbenDrawer({ connectedComponent: WikiPreview, destroyOnClose: true });
function onActionClick({ code, row }: OnActionClickParams<Row>) {
  if (code === 'preview') previewApi.setData(row).open();
}
const [Grid, gridApi] = useVbenVxeGrid({
  gridOptions: {
    columns: [
      { field: 'doc_type', title: '资料目录', width: 150, formatter: ({ row }: { row: Row }) => row.doc_type === 'msds' ? 'MSDS' : 'TDS 技术信息' },
      { field: 'name', title: '化学品', minWidth: 160 },
      { field: 'cas_no', title: 'CAS 号', minWidth: 140, formatter: ({ row }: { row: Row }) => row.cas_no || '未提供' },
      { field: 'cas_valid_checksum', title: 'CAS 校验', width: 130, formatter: ({ row }: { row: Row }) => row.cas_valid_checksum === false ? '校验未通过' : row.cas_no ? '需核对身份' : '未提供' },
      { field: 'id', title: '原表序号', width: 110 },
      { field: 'operation', title: '操作', width: 90, fixed: 'right', align: 'center',
        cellRender: { name: 'CellOperation', attrs: { onClick: onActionClick },
          options: [{ code: 'preview', text: '查看', auth: 'master.chemicals.read' }], props: { renderMode: 'menu' } } },
    ],
    height: 'auto', keepSource: true,
    proxyConfig: { ajax: { query: async ({ page }) => {
      const entries = await getChemicalWikiEntriesApi();
      const rows: Row[] = entries.flatMap((entry) => (['msds', 'tds'] as const).map((type) => ({
        ...entry, doc_type: type, row_key: `${type}-${entry.id}`,
      })));
      const term = keyword.value.trim().toLowerCase();
      const filtered = rows.filter((row) => (!docType.value || row.doc_type === docType.value)
        && (!term || `${row.name} ${row.cas_no || ''}`.toLowerCase().includes(term)))
        .sort((a, b) => a.doc_type.localeCompare(b.doc_type) || a.id - b.id);
      const start = (page.currentPage - 1) * page.pageSize;
      return { items: filtered.slice(start, start + page.pageSize), total: filtered.length };
    } } },
    rowConfig: { keyField: 'row_key' },
    toolbarConfig: { custom: true, export: false, refresh: true, search: false, zoom: true },
  } as VxeTableGridOptions<Row>,
});
function resetSearch() { keyword.value = ''; docType.value = undefined; void gridApi.query(); }
</script>

<template>
  <Page auto-content-height>
    <Preview />
    <div class="flex h-full flex-col gap-3">
      <section class="rounded bg-card p-4">
        <div class="flex w-full flex-wrap items-center gap-x-4 gap-y-2">
          <span class="shrink-0">资料目录</span>
          <Select v-model:value="docType" class="w-44" allow-clear placeholder="全部类型"
            :options="[{ label: 'MSDS', value: 'msds' }, { label: 'TDS 技术信息', value: 'tds' }]" />
          <Input v-model:value="keyword" class="w-60" allow-clear placeholder="化学品名称或 CAS 号" @press-enter="gridApi.query()" />
          <div class="ml-auto flex shrink-0 items-center gap-2">
            <Button @click="resetSearch">重置</Button>
            <Button type="primary" @click="gridApi.query()">搜索</Button>
          </div>
        </div>
      </section>
      <Grid table-title="化学品知识库" />
    </div>
  </Page>
</template>
