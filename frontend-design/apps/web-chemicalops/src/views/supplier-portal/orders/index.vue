<script lang="ts" setup>
import type { PurchaseOrderApi } from '#/api';

import { ref } from 'vue';
import { useRouter } from 'vue-router';

import { Button, Tag } from 'antdv-next';

import { getSupplierOrderListApi } from '#/api';
import { PURCHASE_ORDER_STATUS_DICT } from '#/constants/dictionary';
import { formatAmount, formatDate } from '#/utils/format';
import SupplierRecordList from '../components/SupplierRecordList.vue';

defineOptions({ name: 'SupplierOrderList' });

const router = useRouter();
const orders = ref<PurchaseOrderApi.PurchaseOrder[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const keyword = ref('');
const status = ref('');
const loading = ref(false);

const columns = [
  { key: 'po_no', title: '订单编号', width: 190 },
  { key: 'order_date', title: '下单日期', width: 130 },
  { key: 'expected_arrival_date', title: '预计到货', width: 130 },
  { key: 'order_amount', title: '订单金额', width: 160 },
  { key: 'status', title: '订单状态', width: 120 },
  { key: 'supplier_confirmed_at', title: '供应商确认', width: 130 },
  { key: '__action', title: '操作', width: 120 },
];
const statusOptions = [
  { label: '全部状态', value: '' },
  ...PURCHASE_ORDER_STATUS_DICT.options().filter(({ value }) => value !== 'DRAFT'),
];

async function load() {
  loading.value = true;
  try {
    const result = await getSupplierOrderListApi({ page: page.value, page_size: pageSize.value, status: status.value || undefined, keyword: keyword.value || undefined });
    orders.value = result.items;
    total.value = result.total;
  } finally {
    loading.value = false;
  }
}
function openDetail(order: PurchaseOrderApi.PurchaseOrder) { void router.push({ name: 'SupplierOrderDetail', params: { id: order.id } }); }


</script>

<template>
  <SupplierRecordList
    v-model:keyword="keyword"
    v-model:status="status"
    :columns="columns"
    :fetch-records="load"
    :loading="loading"
    v-model:page="page"
    v-model:page-size="pageSize"
    :rows="orders"
    :status-options="statusOptions"
    :total="total"
    :scroll-x="1040"
    subtitle="仅显示当前供应商账号关联企业的正式订单，可按订单状态筛选。"
    title="我的订单"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'po_no'"><span>{{ record.po_no }}</span></template>
      <template v-else-if="column.key === 'order_date'">{{ formatDate(record.order_date) }}</template>
      <template v-else-if="column.key === 'expected_arrival_date'">{{ formatDate(record.expected_arrival_date) }}</template>
      <template v-else-if="column.key === 'order_amount'">{{ formatAmount(record.order_amount) }} {{ record.currency_code }}</template>
      <template v-else-if="column.key === 'status'"><Tag :color="PURCHASE_ORDER_STATUS_DICT.color(record.status)">{{ PURCHASE_ORDER_STATUS_DICT.label(record.status) }}</Tag></template>
      <template v-else-if="column.key === 'supplier_confirmed_at'"><Tag :color="record.supplier_confirmed_at ? 'success' : 'warning'">{{ record.supplier_confirmed_at ? '已确认' : '待确认' }}</Tag></template>
      <template v-else-if="column.key === '__action'"><Button size="small" type="link" @click="openDetail(record)">查看详情</Button></template>
    </template>
  </SupplierRecordList>
</template>
