<script lang="ts" setup>
import type { PurchaseOrderApi, SupplierPortalApi } from '#/api';

import { computed, onMounted, ref } from 'vue';

import { useAccess } from '@vben/access';
import { Plus } from '@vben/icons';
import { Button, Input, message, Modal, Select, Tag } from 'antdv-next';

import { downloadSupplierQualityDocumentApi, getSupplierOrderListApi, getSupplierQualityDocumentsApi, submitSupplierQualityDocumentApi } from '#/api';
import { SUPPLIER_QUALITY_DOCUMENT_STATUS_DICT } from '#/constants/dictionary';
import { formatDateTime } from '#/utils/format';
import SupplierRecordList from '../components/SupplierRecordList.vue';

defineOptions({ name: 'SupplierQualityDocuments' });

const { hasAccessByCodes } = useAccess();
const rows = ref<SupplierPortalApi.QualityDocument[]>([]);
const orders = ref<PurchaseOrderApi.PurchaseOrder[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const keyword = ref('');
const status = ref('');
const loading = ref(false);
const saving = ref(false);
const modalOpen = ref(false);
const selectedOrder = ref<number>();
const documentType = ref('COA');
const note = ref('');
const fileValue = ref<File>();
const fileInput = ref<HTMLInputElement>();

const columns = [
  { key: 'document_no', title: '资料编号', width: 190 },
  { key: 'po_no', title: '采购订单', width: 190 },
  { key: 'document_type', title: '资料类型', width: 150 },
  { key: 'file_name', title: '文件名称', width: 260 },
  { key: 'submitted_at', title: '提交时间', width: 180 },
  { key: 'status', title: '资料状态', width: 120 },
  { key: '__action', title: '操作', width: 120 },
];
const statusOptions = [{ label: '全部状态', value: '' }, ...SUPPLIER_QUALITY_DOCUMENT_STATUS_DICT.options()];
const typeOptions = [
  { label: '分析证书（COA）', value: 'COA' },
  { label: '安全数据表（SDS）', value: 'SDS' },
  { label: '检验报告', value: 'INSPECTION_REPORT' },
  { label: '其他资料', value: 'OTHER' },
];
const orderOptions = computed(() => orders.value.map((row) => ({ label: row.po_no, value: row.id })));
const canSubmit = hasAccessByCodes(['supplier.portal.quality.submit']);

async function load() {
  loading.value = true;
  try {
    const result = await getSupplierQualityDocumentsApi({ page: page.value, page_size: pageSize.value, keyword: keyword.value || undefined, status: status.value || undefined });
    rows.value = result.items;
    total.value = result.total;
  } finally { loading.value = false; }
}
async function loadOrders() {
  const result = await getSupplierOrderListApi({ page: 1, page_size: 100 });
  orders.value = result.items;
}
function openSubmit() {
  selectedOrder.value = undefined;
  documentType.value = 'COA';
  note.value = '';
  fileValue.value = undefined;
  if (fileInput.value) fileInput.value.value = '';
  modalOpen.value = true;
}
function onFileChange(event: Event) {
  fileValue.value = (event.target as HTMLInputElement).files?.[0];
}
async function submit() {
  if (!selectedOrder.value || !fileValue.value) {
    message.warning('请选择关联订单并选择要提交的文件');
    return;
  }
  const data = new FormData();
  data.append('po_id', String(selectedOrder.value));
  data.append('document_type', documentType.value);
  data.append('note', note.value.trim());
  data.append('file', fileValue.value);
  saving.value = true;
  try {
    await submitSupplierQualityDocumentApi(data);
    message.success('质量资料已提交');
    modalOpen.value = false;
    await load();
  } finally { saving.value = false; }
}
async function download(record: SupplierPortalApi.QualityDocument) {
  const blob = await downloadSupplierQualityDocumentApi(record.id);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = record.file_name;
  anchor.click();
  URL.revokeObjectURL(url);
}

onMounted(loadOrders);
</script>

<template>
  <SupplierRecordList
    export-permission="supplier.portal.quality.export"
    v-model:keyword="keyword"
    v-model:status="status"
    :columns="columns"
    :fetch-records="load"
    :loading="loading"
    v-model:page="page"
    v-model:page-size="pageSize"
    :rows="rows"
    :status-options="statusOptions"
    :total="total"
    :scroll-x="1250"
    subtitle="提交并查看与本供应商订单关联的 COA、SDS、检验报告等质量资料。"
    title="质量资料"
  >
    <template #toolbar><Button v-if="canSubmit" type="primary" @click="openSubmit"><Plus class="size-5" />提交质量资料</Button></template>
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'document_no'"><span>{{ record.document_no }}</span></template>
      <template v-else-if="column.key === 'po_no'">{{ record.po_no }}</template>
      <template v-else-if="column.key === 'document_type'">{{ typeOptions.find((option) => option.value === record.document_type)?.label || record.document_type }}</template>
      <template v-else-if="column.key === 'file_name'"><span class="block max-w-64 truncate" :title="record.file_name">{{ record.file_name }}</span></template>
      <template v-else-if="column.key === 'submitted_at'">{{ formatDateTime(record.submitted_at) }}</template>
      <template v-else-if="column.key === 'status'"><Tag :color="SUPPLIER_QUALITY_DOCUMENT_STATUS_DICT.color(record.status)">{{ SUPPLIER_QUALITY_DOCUMENT_STATUS_DICT.label(record.status) }}</Tag></template>
      <template v-else-if="column.key === '__action'"><Button type="link" size="small" @click="download(record)">下载文件</Button></template>
    </template>
  </SupplierRecordList>

  <Modal v-model:open="modalOpen" :confirm-loading="saving" title="提交质量资料" width="620px" @ok="submit">
    <div class="space-y-4 py-2">
      <div><div class="mb-1 text-sm text-muted-foreground">关联采购订单 <span class="text-red-500">*</span></div><Select v-model:value="selectedOrder" :options="orderOptions" class="w-full" placeholder="请选择订单" /></div>
      <div><div class="mb-1 text-sm text-muted-foreground">资料类型</div><Select v-model:value="documentType" :options="typeOptions" class="w-full" /></div>
      <div><div class="mb-1 text-sm text-muted-foreground">资料文件 <span class="text-red-500">*</span></div><div class="flex items-center gap-3"><input ref="fileInput" type="file" accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg" class="hidden" @change="onFileChange" /><Button @click="fileInput?.click()">选择文件</Button><span class="max-w-sm truncate text-sm text-muted-foreground">{{ fileValue?.name || '支持 PDF、Office 文档和常见图片格式' }}</span></div></div>
      <div><div class="mb-1 text-sm text-muted-foreground">说明</div><Input.TextArea v-model:value="note" :maxlength="1000" :rows="3" placeholder="例如批次号、对应产品或资料版本" /></div>
    </div>
  </Modal>
</template>
