<script lang="ts" setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { Button, Modal } from 'antdv-next';
import { requestClient } from '#/api/request';
import SupplierRecordList from '#/views/supplier-portal/components/SupplierRecordList.vue';

interface DocumentRow { type: 'quote' | 'quality' | 'invoice'; object_id: number; file_id: null | number; file_name: string; document_no: string; parent_no: null | string; status: string; file_parse_status: null | string; review_status?: null | string }
interface Reference { field: null | string; quote: null | string; location: null | string; review_id?: number; delivery_item_id?: number; review_status?: string }
interface ReferenceResult { references: Reference[]; message: null | string; review_status?: string }
const router = useRouter();
const rows = ref<DocumentRow[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const keyword = ref('');
const status = ref('');
const loading = ref(false);
const detail = ref<ReferenceResult>();
const selected = ref<DocumentRow>();
const open = ref(false);
const labels = { quote: '报价文件', quality: '质量报告', invoice: '发票文件' };
const statusLabels: Record<string, string> = {
  NOT_STARTED: '未开始', PROCESSING: '处理中', SUCCEEDED: '成功', FAILED: '失败',
  DRAFT: '草稿', SUBMITTED: '已提交', VERIFIED: '已核验', REJECTED: '已驳回',
  PENDING: '待处理', CONFIRMED: '已确认', NEEDS_CORRECTION: '待修正', CORRECTION_SUBMITTED: '修正已提交',
  CANCELLED: '已取消', VOID: '已作废', PASS: '合格', FAIL: '不合格', REINSPECTION: '待复验',
};
const columns = [
  { key: 'file_name', title: '文件名称', width: 250 },
  { key: 'type', title: '类型', width: 120 },
  { key: 'document_no', title: '关联单据', width: 180 },
  { key: 'status', title: '业务状态', width: 130 },
  { key: 'file_parse_status', title: '通用文件解析状态', width: 160 },
  { key: 'review_status', title: '报告复核状态', width: 140 },
  { key: '__action', title: '操作', width: 100 },
];
async function fetchRecords() {
  loading.value = true;
  try {
    const result = await requestClient.get<{ items: DocumentRow[]; total: number }>('/ai/documents', { params: { kind: status.value || undefined, keyword: keyword.value || undefined, page: page.value, page_size: pageSize.value } });
    rows.value = result.items;
    total.value = result.total;
  } finally { loading.value = false; }
}
async function showReferences(row: DocumentRow) {
  if (row.file_id === null) {
    selected.value = row;
    detail.value = { references: [], message: '未关联来源文件' };
    open.value = true;
    return;
  }
  detail.value = await requestClient.get<ReferenceResult>(`/ai/documents/${row.type}/${row.object_id}/${row.file_id}/references`);
  selected.value = row;
  open.value = true;
}
function openRecord(row: DocumentRow) {
  if (row.type === 'quote') void router.push({ path: '/procurement/rfqs', query: { ai_record_id: row.object_id, document_quotes: '1' } });
  else if (row.type === 'invoice') void router.push({ path: '/finance/invoices', query: { ai_record_id: row.object_id, ai_record_type: 'invoices' } });
  else void router.push({ path: '/quality/acceptances', query: { report_id: row.object_id, report_file_id: row.file_id ?? undefined } });
}
function openReview(reviewId: number) {
  if (!selected.value) return;
  open.value = false;
  void router.push({ path: '/quality/acceptances', query: { report_id: selected.value.object_id, report_file_id: selected.value.file_id ?? undefined, report_review_id: reviewId } });
}
</script>

<template>
  <SupplierRecordList v-model:keyword="keyword" v-model:status="status" v-model:page="page" v-model:page-size="pageSize"
    title="业务文档" subtitle="查看有权访问的报价文件、质量报告和发票文件" :columns="columns" :rows="rows" :total="total"
    :loading="loading" :fetch-records="fetchRecords" status-label="类型" :status-options="[{ label: '报价文件', value: 'quote' }, { label: '质量报告', value: 'quality' }, { label: '发票文件', value: 'invoice' }]">
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === '__action'"><Button type="link" @click="showReferences(record)">查看引用</Button><Button type="link" @click="openRecord(record)">查看单据</Button></template>
      <template v-else-if="column.key === 'type'">{{ labels[(record as DocumentRow).type] }}</template>
      <template v-else-if="['status', 'file_parse_status', 'review_status'].includes(column.key)">{{ statusLabels[record[column.key]] || record[column.key] || '—' }}</template>
      <template v-else>{{ record[column.key] || '—' }}</template>
    </template>
  </SupplierRecordList>
  <Modal v-model:open="open" title="文档引用" :footer="null">
    <p>{{ selected?.file_name }} · {{ selected?.document_no }}</p>
    <p v-if="selected?.file_parse_status === 'FAILED'">文件通用解析失败；业务候选解析状态以原业务页面为准。</p>
    <p v-if="detail?.message">{{ detail.message }}</p>
    <p v-if="detail?.review_status">报告复核状态：{{ detail.review_status }}</p>
    <div v-for="(item, index) in detail?.references" :key="index" class="mt-3">
      <p>核对记录 {{ item.review_id }} · 到货明细 {{ item.delivery_item_id }} · {{ item.review_status ? statusLabels[item.review_status] || item.review_status : '—' }}</p>
      <p>{{ item.field || '未记录字段' }} · {{ item.location || '位置未记录' }}</p>
      <p>{{ item.quote || '原文未记录' }}</p>
      <Button v-if="item.review_id" type="link" @click="openReview(item.review_id)">查看核对记录</Button>
    </div>
  </Modal>
</template>
