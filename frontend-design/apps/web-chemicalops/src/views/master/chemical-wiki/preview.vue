<script setup lang="ts">
import type { ChemicalWikiDetail, ChemicalWikiEntry, ChemicalWikiItemReference, ChemicalWikiSource, ChemicalWikiVersion } from '#/api/chemical-wiki';
import { computed, ref } from 'vue';
import { useAccess } from '@vben/access';
import { useVbenDrawer } from '@vben/common-ui';
import { Alert, Button, Empty, Input, Select, Spin, Tag, message } from 'antdv-next';
import { getChemicalWikiEntryApi, getChemicalWikiSourcesApi, getChemicalWikiVersionApi, getChemicalWikiVersionsApi, saveChemicalWikiVersionApi, updateChemicalWikiSourceApi } from '#/api/chemical-wiki';
import { formatDateTime } from '#/utils/format';

type Row = ChemicalWikiEntry & { doc_type: 'msds' | 'tds' };
const row = ref<Row>();
const detail = ref<ChemicalWikiDetail>();
const loading = ref(false);
const error = ref('');
const note = ref('');
const saving = ref(false);
const versions = ref<ChemicalWikiVersion[]>([]);
const historyOpen = ref(false);
const historical = ref(false);
const editing = ref(false);
const editItems = ref<Array<ChemicalWikiItemReference & { text: string }>>([]);
const selectedSource = ref<string>();
const selectedSection = ref<string>();
const sourcePickerOpen = ref(false);
const sourceCandidates = ref<ChemicalWikiSource[]>([]);
const selectedDocument = ref<number>();
const { hasAccessByCodes } = useAccess();
const canEdit = hasAccessByCodes(['master.chemicals.write']);
const sourceOptions = computed(() => (detail.value?.msds.rows || []).flatMap((item) =>
  item.cells.slice(1).map((text, index) => ({
    value: `${item.row}:${index + 2}`,
    label: `第 ${item.row} 行 · ${text.slice(0, 80)}`,
    disabled: !text.trim() || editItems.value.some((entry) => entry.source_row === item.row && entry.source_cell === index + 2),
  }))));
const title = computed(() => row.value ? `${row.value.name} · ${row.value.doc_type.toUpperCase()}` : '化学品资料');
const [Drawer, drawerApi] = useVbenDrawer<Row>({ footer: false, async onOpenChange(open) {
  if (!open) return;
  row.value = drawerApi.getData(); detail.value = undefined; error.value = ''; versions.value = []; historyOpen.value = false;
  historical.value = false; editing.value = false; sourcePickerOpen.value = false;
  if (!row.value) return;
  loading.value = true;
  try { detail.value = await getChemicalWikiEntryApi(row.value.id); note.value = detail.value.note; }
  catch { error.value = '资料加载失败，请稍后重试。'; }
  finally { loading.value = false; }
} });
async function saveNote() {
  if (!row.value || !detail.value || !canEdit || historical.value) return;
  saving.value = true;
  try {
    const result = await saveChemicalWikiVersionApi(row.value.id, { expected_version: detail.value.version, note: note.value });
    detail.value.version = result.version; detail.value.note = result.note;
    if (historyOpen.value) versions.value = await getChemicalWikiVersionsApi(row.value.id);
    message.success('维护说明已保存');
  } finally { saving.value = false; }
}
function beginEdit() {
  if (!detail.value) return;
  editItems.value = detail.value.technical.items.map((item) => ({ ...item }));
  selectedSection.value = detail.value.technical.sections[0];
  selectedSource.value = undefined;
  editing.value = true;
}
function addItem() {
  if (!detail.value || !selectedSource.value || !selectedSection.value) return;
  const [sourceRow, sourceCell] = selectedSource.value.split(':').map(Number);
  const text = detail.value.msds.rows.find((item) => item.row === sourceRow)?.cells[(sourceCell ?? 0) - 1];
  if (sourceRow && sourceCell && text?.trim()) editItems.value.push({ section: selectedSection.value, source_row: sourceRow, source_cell: sourceCell, text });
  selectedSource.value = undefined;
}
async function saveTechnical() {
  if (!row.value || !detail.value || historical.value) return;
  saving.value = true;
  try {
    const items = editItems.value.map(({ section, source_row, source_cell }) => ({ section, source_row, source_cell }));
    await saveChemicalWikiVersionApi(row.value.id, { expected_version: detail.value.version, note: note.value, items });
    detail.value = await getChemicalWikiEntryApi(row.value.id);
    note.value = detail.value.note; editing.value = false;
    if (historyOpen.value) versions.value = await getChemicalWikiVersionsApi(row.value.id);
    message.success('技术信息已保存');
  } finally { saving.value = false; }
}
async function toggleSources() {
  if (!row.value) return;
  sourcePickerOpen.value = !sourcePickerOpen.value;
  selectedDocument.value = undefined;
  if (sourcePickerOpen.value) sourceCandidates.value = await getChemicalWikiSourcesApi(row.value.id);
}
async function updateSource() {
  if (!row.value || !detail.value || !selectedDocument.value || historical.value) return;
  saving.value = true;
  try {
    await updateChemicalWikiSourceApi(row.value.id, { expected_version: detail.value.version, document_id: selectedDocument.value });
    detail.value = await getChemicalWikiEntryApi(row.value.id);
    note.value = detail.value.note; sourcePickerOpen.value = false; editing.value = false;
    if (historyOpen.value) versions.value = await getChemicalWikiVersionsApi(row.value.id);
    message.success('来源已更新，请重新维护技术信息');
  } finally { saving.value = false; }
}
async function showVersion(version: number) {
  if (!row.value) return;
  detail.value = await getChemicalWikiVersionApi(row.value.id, version);
  note.value = detail.value.note; historical.value = true; editing.value = false; sourcePickerOpen.value = false;
}
async function showCurrent() {
  if (!row.value) return;
  detail.value = await getChemicalWikiEntryApi(row.value.id);
  note.value = detail.value.note; historical.value = false;
}
async function toggleHistory() {
  if (!row.value) return;
  historyOpen.value = !historyOpen.value;
  if (historyOpen.value) versions.value = await getChemicalWikiVersionsApi(row.value.id);
}
defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[900px] max-w-[100vw]" :footer="false">
    <Spin :spinning="loading">
      <div v-if="row && detail" class="space-y-5 pb-5">
        <section class="rounded-lg border border-border p-4">
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="m-0 text-base font-semibold">{{ row.name }}</h2>
            <Tag color="blue">{{ row.doc_type.toUpperCase() }}</Tag>
            <Tag v-if="row.cas_valid_checksum === false" color="warning">CAS 校验未通过</Tag>
          </div>
          <div class="mt-3 text-sm text-muted-foreground">CAS：{{ row.cas_no || '原文未提供' }} · {{ detail.msds.source_heading }}</div>
          <div class="mt-2 break-all text-xs text-muted-foreground">来源：{{ detail.msds.source.filename }} · SHA-256 {{ detail.msds.source.sha256 }}</div>
        </section>
        <Alert v-if="row.doc_type === 'tds'" type="info" show-icon message="技术信息整理自 MSDS，不代表供应商 TDS 或产品规格。" />
        <Alert v-if="historical" type="info" show-icon message="当前查看的是历史版本。" />
        <Alert v-if="detail.source_status === 'CHANGED'" type="warning" show-icon message="保存的来源文件已变化，当前内容仍是原版本，请核对后更新。" />
        <Alert v-else-if="detail.source_status === 'UNAVAILABLE'" type="warning" show-icon message="保存的来源文件不可读取，当前内容来自原文快照。" />
        <section v-if="canEdit && !historical" class="space-y-3 rounded-lg border border-border p-4">
          <div class="flex items-center justify-between gap-3">
            <h3 class="m-0 text-sm font-semibold">原文来源</h3>
            <Button size="small" @click="toggleSources">{{ sourcePickerOpen ? '取消更新' : '更新来源' }}</Button>
          </div>
          <template v-if="sourcePickerOpen">
            <Alert type="info" show-icon message="选择同 CAS 的已入库 MSDS；更新后保留历史版本，并需重新选择技术信息。" />
            <div class="flex flex-wrap items-center gap-2">
              <Select v-model:value="selectedDocument" class="min-w-0 flex-1" :options="sourceCandidates.map((item) => ({ value: item.id, label: `${item.title || item.object_key} · ${item.cas_no} · ${item.object_key}` }))" placeholder="选择已入库的安全资料" />
              <Button type="primary" :disabled="!selectedDocument" :loading="saving" @click="updateSource">更新</Button>
            </div>
            <div v-if="!sourceCandidates.length" class="text-sm text-muted-foreground">没有可用的同 CAS 安全资料，或原始 CAS 需要核实。</div>
          </template>
        </section>
        <section class="space-y-3 rounded-lg border border-border p-4">
          <div class="flex items-center justify-between gap-3">
            <h3 class="m-0 text-sm font-semibold">维护说明 · 版本 {{ detail.version }}</h3>
            <Button size="small" @click="toggleHistory">{{ historyOpen ? '收起历史' : '查看历史' }}</Button>
          </div>
          <Input.TextArea v-model:value="note" :disabled="!canEdit || historical" :rows="3" :maxlength="5000" placeholder="填写对资料的维护说明" />
          <div v-if="canEdit && !historical" class="flex justify-end"><Button type="primary" :loading="saving" :disabled="editing" @click="saveNote">保存说明</Button></div>
          <div v-if="historyOpen" class="space-y-2 border-t border-border pt-3">
            <div class="flex flex-wrap gap-2">
              <Button size="small" @click="showCurrent">当前版本</Button>
              <Button size="small" @click="showVersion(0)">原始版本</Button>
            </div>
            <Empty v-if="!versions.length" description="暂无维护历史" />
            <div v-for="version in versions" :key="version.version" class="text-sm">
              <span class="text-muted-foreground">版本 {{ version.version }} · 用户 {{ version.actor_id }} · {{ formatDateTime(version.created_at) }}</span>
              <Button size="small" type="link" @click="showVersion(version.version)">查看</Button>
              <div class="whitespace-pre-wrap break-words">{{ version.note || '无说明' }}</div>
            </div>
          </div>
        </section>
        <template v-if="row.doc_type === 'msds'">
          <section v-for="item in detail.msds.rows" :key="item.row" class="rounded-lg border border-border p-4">
            <div class="mb-2 text-sm font-medium">{{ item.cells[0] || `原表第 ${item.row} 行` }}</div>
            <pre v-for="(cell, index) in item.cells.slice(1)" :key="index" class="m-0 whitespace-pre-wrap break-words font-sans text-sm leading-6">{{ cell }}</pre>
          </section>
        </template>
        <template v-else>
          <div v-if="canEdit && !historical" class="flex justify-end gap-2">
            <Button v-if="!editing" @click="beginEdit">维护技术信息</Button>
            <template v-else>
              <Button @click="editing = false">取消</Button>
              <Button type="primary" :loading="saving" @click="saveTechnical">保存技术信息</Button>
            </template>
          </div>
          <section v-if="editing" class="space-y-3 rounded-lg border border-border p-4">
            <h3 class="m-0 text-sm font-semibold">从原文添加字段</h3>
            <div class="flex flex-wrap items-center gap-2">
              <Select v-model:value="selectedSection" class="w-44" :options="detail.technical.sections.map((section) => ({ value: section, label: section }))" placeholder="选择目录" />
              <Select v-model:value="selectedSource" class="min-w-0 flex-1" show-search option-filter-prop="label" :options="sourceOptions" placeholder="选择原文内容" />
              <Button :disabled="!selectedSource || !selectedSection" @click="addItem">添加</Button>
            </div>
          </section>
          <section v-for="section in detail.technical.sections" :key="section" class="rounded-lg border border-border p-4">
            <h3 class="m-0 mb-3 text-sm font-semibold">{{ section }}</h3>
            <template v-if="(editing ? editItems : detail.technical.items).some((item) => item.section === section)">
              <div v-for="item in (editing ? editItems : detail.technical.items).filter((entry) => entry.section === section)" :key="`${item.source_row}-${item.source_cell}`" class="mb-2 text-sm">
                <span class="whitespace-pre-wrap break-words">{{ item.text }}</span>
                <span class="ml-2 text-xs text-muted-foreground">原表第 {{ item.source_row }} 行</span>
                <Button v-if="editing" size="small" type="link" @click="editItems = editItems.filter((entry) => entry.source_row !== item.source_row || entry.source_cell !== item.source_cell)">移除</Button>
              </div>
            </template>
            <div v-else class="text-sm text-muted-foreground">未从原文提取到内容</div>
          </section>
        </template>
      </div>
      <Alert v-else-if="error" type="error" show-icon :message="error" />
      <Empty v-else-if="!loading" description="暂无资料" />
    </Spin>
  </Drawer>
</template>
