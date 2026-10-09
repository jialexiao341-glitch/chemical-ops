<script lang="ts" setup>
import type { SupplierPortalApi } from '#/api';

import { ref } from 'vue';
import { useRouter } from 'vue-router';

import { Button, Tag } from 'antdv-next';

import { getSupplierRfqListApi } from '#/api';
import { RFQ_STATUS_DICT, RFQ_SUPPLIER_RESPONSE_DICT } from '#/constants/dictionary';
import { formatDate, formatDateTime } from '#/utils/format';
import SupplierRecordList from '../components/SupplierRecordList.vue';

defineOptions({ name: 'SupplierRfqList' });

const router = useRouter();
const rfqs = ref<SupplierPortalApi.RfqListItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const keyword = ref('');
const status = ref('');
const loading = ref(false);

const columns = [
  { key: 'rfq_no', title: '询价编号', width: 160 },
  { key: 'item_summary', title: '询价物料', width: 220 },
  { key: 'requested_delivery_date', title: '期望交期', width: 130 },
  { key: 'quote_deadline', title: '报价截止', width: 170 },
  { key: 'status', title: '询价状态', width: 110 },
  { key: 'response_status', title: '我的响应', width: 110 },
  { key: '__action', title: '操作', width: 130 },
];
const statusOptions = [
  { label: '全部状态', value: '' },
  ...RFQ_STATUS_DICT.options().filter(({ value }) => value !== 'DRAFT'),
];

async function load() {
  loading.value = true;
  try {
    const result = await getSupplierRfqListApi({ page: page.value, page_size: pageSize.value, status: status.value || undefined, keyword: keyword.value || undefined });
    rfqs.value = result.items;
    total.value = result.total;
  } finally {
    loading.value = false;
  }
}
function openDetail(rfq: SupplierPortalApi.RfqListItem) { void router.push({ name: 'SupplierRfqDetail', params: { id: rfq.id } }); }


</script>

<template>
  <SupplierRecordList
    export-permission="supplier.portal.rfq.export"
    v-model:keyword="keyword"
    v-model:status="status"
    :columns="columns"
    :fetch-records="load"
    :loading="loading"
    v-model:page="page"
    v-model:page-size="pageSize"
    :rows="rfqs"
    :status-options="statusOptions"
    :total="total"
    :scroll-x="1120"
    subtitle="仅显示发送给当前供应商账号关联企业的询价，可按询价状态筛选。"
    title="我的询价"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'rfq_no'">
        <span>{{ record.rfq_no }}</span>
      </template>
      <template v-else-if="column.key === 'item_summary'">
        <span :title="`${record.item_summary} · ${record.item_count} 项物料`">{{ record.item_summary }}</span>
      </template>
      <template v-else-if="column.key === 'requested_delivery_date'">{{ formatDate(record.requested_delivery_date) }}</template>
      <template v-else-if="column.key === 'quote_deadline'">{{ formatDateTime(record.quote_deadline) }}</template>
      <template v-else-if="column.key === 'status'"><Tag :color="RFQ_STATUS_DICT.color(record.status)">{{ RFQ_STATUS_DICT.label(record.status) }}</Tag></template>
      <template v-else-if="column.key === 'response_status'"><Tag :color="RFQ_SUPPLIER_RESPONSE_DICT.color(record.response_status)">{{ RFQ_SUPPLIER_RESPONSE_DICT.label(record.response_status) }}</Tag></template>
      <template v-else-if="column.key === '__action'"><Button size="small" type="link" @click="openDetail(record)">查看并报价</Button></template>
    </template>
  </SupplierRecordList>
</template>
