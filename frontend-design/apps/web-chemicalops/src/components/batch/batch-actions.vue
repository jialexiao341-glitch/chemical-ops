<script setup lang="ts">
import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { IconifyIcon } from '@vben/icons';

import { Button, Dropdown, message, Modal } from 'antdv-next';

import { batchDeleteApi, batchExportApi, batchImportApi } from '#/api/batch';

type DeleteMode = 'draft' | 'master' | 'permission' | 'readonly';

const props = defineProps<{
  deleteMode: DeleteMode;
  gridApi: any;
  importable?: boolean;
  resource: string;
  writePermission?: string;
  exportPermission?: string;
  importPermission?: string;
  deletePermission?: string;
}>();

const { hasAccessByCodes } = useAccess();
const busy = ref(false);
const menuOpen = ref(false);
const fileInput = ref<HTMLInputElement>();
const canWrite = computed(
  () => !props.writePermission || hasAccessByCodes([props.writePermission]),
);
const canExport = computed(() => hasAccessByCodes([props.exportPermission ?? `${props.resource}.export`]));
const canImport = computed(
  () => props.importable && canWrite.value && hasAccessByCodes([props.importPermission ?? `${props.resource}.import`]),
);
const canDelete = computed(
  () => props.deleteMode !== 'readonly'
    && hasAccessByCodes([props.deletePermission ?? (
      props.deleteMode === 'master'
        ? props.resource.startsWith('system.')
          ? props.writePermission ?? `${props.resource}.write`
          : props.resource === 'master.suppliers' ? 'master.suppliers.deactivate' : `${props.resource}.delete`
        : props.writePermission ?? `${props.resource}.write`
    )]),
);

function selectedIds(): number[] {
  const rows = props.gridApi.grid?.getCheckboxRecords?.() ?? [];
  return rows.map((row: { id: number }) => row.id);
}

function selectionOrWarn(): number[] {
  const ids = selectedIds();
  if (ids.length === 0) message.warning('请先勾选记录');
  return ids;
}

function onDelete() {
  menuOpen.value = false;
  const ids = selectionOrWarn();
  if (!ids.length) return;
  const action = props.deleteMode === 'master' ? '停用' : '删除';
  Modal.confirm({
    title: `确认批量${action} ${ids.length} 条记录？`,
    content: props.deleteMode === 'draft'
      ? '仅草稿可删除；如果包含已提交记录，整批操作会被拒绝。'
      : props.deleteMode === 'master'
        ? '停用后记录会保留在停用记录中，历史业务引用不受影响。'
        : '请确认所选权限没有被角色引用。',
    okText: `确认${action}`,
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      busy.value = true;
      try {
        const result = await batchDeleteApi(props.resource, ids);
        message.success(`已${action} ${result.count} 条记录`);
        props.gridApi.grid?.clearCheckboxRow?.();
        await props.gridApi.query();
      } finally {
        busy.value = false;
      }
    },
  });
}

async function onExport() {
  menuOpen.value = false;
  const ids = selectionOrWarn();
  if (!ids.length) return;
  busy.value = true;
  try {
    const blob = await batchExportApi(props.resource, ids);
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${props.resource.replaceAll('.', '-')}.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    message.success(`已导出 ${ids.length} 条记录`);
  } finally {
    busy.value = false;
  }
}

async function onImport(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  busy.value = true;
  try {
    const result = await batchImportApi(props.resource, file);
    message.success(`已导入 ${result.count} 条记录`);
    await props.gridApi.query();
  } finally {
    busy.value = false;
  }
}

function onChooseImport() {
  menuOpen.value = false;
  fileInput.value?.click();
}
</script>

<template>
  <Dropdown v-if="canExport || canImport || canDelete" :open="menuOpen" :trigger="['click']" placement="bottomRight" @open-change="menuOpen = $event">
    <Button :disabled="busy" class="batch-trigger">批量操作 <IconifyIcon class="size-4 text-slate-500" icon="lucide:chevron-down" /></Button>
    <template #popupRender>
      <div class="batch-menu">
        <button v-if="canExport" class="batch-menu-item" type="button" @click="onExport">导出所选</button>
        <button
          v-if="canImport"
          class="batch-menu-item"
          type="button"
          @click="onChooseImport"
        >导入 CSV</button>
        <div v-if="canImport && canDelete" class="batch-menu-divider"></div>
        <button
          v-if="canDelete"
          class="batch-menu-item batch-menu-danger"
          type="button"
          @click="onDelete"
        >{{ deleteMode === 'master' ? '停用所选' : deleteMode === 'draft' ? '删除所选草稿' : '删除所选' }}</button>
      </div>
    </template>
  </Dropdown>
  <input ref="fileInput" accept=".csv,text/csv" class="hidden" type="file" @change="onImport" />
</template>

<style scoped>
.batch-trigger { display: inline-flex; align-items: center; gap: 7px; font-weight: 500; }
.batch-menu { min-width: 154px; padding: 5px; border: 1px solid #e2e8f0; border-radius: 9px; background: #fff; box-shadow: 0 10px 28px #0f27401f; }
.batch-menu-item { display: block; width: 100%; padding: 8px 11px; border: 0; border-radius: 5px; background: transparent; color: #172b4d; text-align: left; font-size: 14px; line-height: 20px; cursor: pointer; }
.batch-menu-item:hover:not(:disabled) { background: #f1f5f9; }
.batch-menu-item:disabled { color: #94a3b8; cursor: not-allowed; }
.batch-menu-danger { color: #dc2626; }
.batch-menu-danger:hover:not(:disabled) { background: #fff1f2; }
.batch-menu-divider { height: 1px; margin: 4px 6px; background: #e8edf3; }
:global(.dark) .batch-menu { border-color: #334155; background: #1e293b; }
:global(.dark) .batch-menu-item { color: #e2e8f0; }
:global(.dark) .batch-menu-item:hover:not(:disabled) { background: #334155; }
:global(.dark) .batch-menu-danger { color: #fca5a5; }
:global(.dark) .batch-menu-danger:hover:not(:disabled) { background: #4c2633; }
:global(.dark) .batch-menu-divider { background: #334155; }
</style>
