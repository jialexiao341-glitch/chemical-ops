<script lang="ts" setup>
import type { PurchaseOrderApi } from '#/api';
import type { Dayjs } from 'dayjs';

import { ref } from 'vue';
import dayjs from 'dayjs';

import { useAccess } from '@vben/access';
import { Button, DatePicker, Input, message, Modal, Tag } from 'antdv-next';

import { getSupplierOrderListApi, updateSupplierExpectedDeliveryApi } from '#/api';
import { PURCHASE_ORDER_STATUS_DICT } from '#/constants/dictionary';
import { formatDate } from '#/utils/format';
import SupplierRecordList from '../components/SupplierRecordList.vue';

defineOptions({ name: 'SupplierDeliveryUpdates' });

const { hasAccessByCodes } = useAccess();
const rows = ref<PurchaseOrderApi.PurchaseOrder[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const keyword = ref('');
const status = ref('ACTIVE');
const loading = ref(false);
const saving = ref(false);
const modalOpen = ref(false);
const order = ref<PurchaseOrderApi.PurchaseOrder>();
const expectedDate = ref<Dayjs>();
const note = ref('');

const columns = [
  { key: 'po_no', title: '订单编号', width: 200 },
  { key: 'expected_arrival_date', title: '当前预计交期', width: 170 },
  { key: 'status', title: '订单状态', width: 140 },
  { key: 'supplier_confirmed_at', title: '供应商确认', width: 140 },
  { key: '__action', title: '操作', width: 170 },
];
const statusOptions = [
  { label: '全部可更新订单', value: 'ACTIVE' },
  { label: '已下单', value: 'ORDERED' },
  { label: '部分到货', value: 'PARTIAL' },
];
const canUpdate = hasAccessByCodes(['supplier.portal.delivery.update']);

async function load() {
  loading.value = true;
  try {
    const result = await getSupplierOrderListApi({ page: page.value, page_size: pageSize.value, keyword: keyword.value || undefined, status: status.value || 'ACTIVE' });
    rows.value = result.items;
    total.value = result.total;
  } finally { loading.value = false; }
}
function openUpdate(value: PurchaseOrderApi.PurchaseOrder) {
  order.value = value;
  expectedDate.value = value.expected_arrival_date ? dayjs(value.expected_arrival_date) : undefined;
  note.value = '';
  modalOpen.value = true;
}
async function save() {
  if (!order.value || !expectedDate.value || saving.value) {
    message.warning('请选择预计交期');
    return;
  }
  saving.value = true;
  try {
    await updateSupplierExpectedDeliveryApi(order.value.id, expectedDate.value.format('YYYY-MM-DD'), note.value.trim() || undefined);
    message.success('预计交期已更新');
    modalOpen.value = false;
    await load();
  } finally { saving.value = false; }
}


</script>

<template>
  <SupplierRecordList
    export-permission="supplier.portal.delivery.export"
    v-model:keyword="keyword"
    v-model:status="status"
    :columns="canUpdate ? columns : columns.filter((column) => column.key !== '__action')"
    :fetch-records="load"
    :loading="loading"
    v-model:page="page"
    v-model:page-size="pageSize"
    :rows="rows"
    :status-options="statusOptions"
    :total="total"
    subtitle="仅可更新已下单或部分到货订单的预计交期；每次变更都会记录到订单履历。"
    title="交期更新"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'po_no'"><span>{{ record.po_no }}</span></template>
      <template v-else-if="column.key === 'expected_arrival_date'">{{ formatDate(record.expected_arrival_date) }}</template>
      <template v-else-if="column.key === 'status'"><Tag :color="PURCHASE_ORDER_STATUS_DICT.color(record.status)">{{ PURCHASE_ORDER_STATUS_DICT.label(record.status) }}</Tag></template>
      <template v-else-if="column.key === 'supplier_confirmed_at'"><Tag :color="record.supplier_confirmed_at ? 'success' : 'warning'">{{ record.supplier_confirmed_at ? '已确认' : '待确认' }}</Tag></template>
      <template v-else-if="column.key === '__action'"><Button v-if="canUpdate" type="link" @click="openUpdate(record)">更新预计交期</Button></template>
    </template>
  </SupplierRecordList>

  <Modal v-model:open="modalOpen" :confirm-loading="saving" title="更新预计交期" @ok="save">
    <div v-if="order" class="space-y-4 py-2">
      <div><div class="mb-1 text-sm text-muted-foreground">采购订单</div><div class="font-medium">{{ order.po_no }}</div></div>
      <div><div class="mb-1 text-sm text-muted-foreground">预计到货日期</div><DatePicker v-model:value="expectedDate" class="w-full" /></div>
      <div><div class="mb-1 text-sm text-muted-foreground">变更说明</div><Input.TextArea v-model:value="note" :maxlength="1000" :rows="3" placeholder="填写延期原因或交期说明" /></div>
    </div>
  </Modal>
</template>
