<script lang="ts" setup>
import type { PurchaseOrderApi, SupplierPortalApi } from '#/api';
import type { Dayjs } from 'dayjs';

import { computed, onMounted, ref } from 'vue';
import dayjs from 'dayjs';

import { useAccess } from '@vben/access';
import { Plus } from '@vben/icons';
import { Button, DatePicker, Input, InputNumber, message, Modal, Select, Tag } from 'antdv-next';

import { createSupplierShipmentApi, getSupplierOrderApi, getSupplierOrderListApi, getSupplierShipmentListApi } from '#/api';
import { DELIVERY_STATUS_DICT, PURCHASE_ORDER_STATUS_DICT } from '#/constants/dictionary';
import { formatDate, formatQuantity } from '#/utils/format';
import SupplierRecordList from '../components/SupplierRecordList.vue';

defineOptions({ name: 'SupplierShipmentList' });

type ShipmentLine = { id: number; name: string; orderQuantity: number; receivedQuantity: number; quantity: number; unitId: number };

const { hasAccessByCodes } = useAccess();
const rows = ref<SupplierPortalApi.Shipment[]>([]);
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
const shipmentDate = ref<Dayjs>();
const expectedDate = ref<Dayjs>();
const logisticsCompany = ref('');
const trackingNo = ref('');
const note = ref('');
const lines = ref<ShipmentLine[]>([]);

const columns = [
  { key: 'delivery_no', title: '发货单号', width: 190 },
  { key: 'po_no', title: '采购订单', width: 180 },
  { key: 'shipment_date', title: '发货日期', width: 130 },
  { key: 'expected_arrival_date', title: '预计到货', width: 130 },
  { key: 'tracking_no', title: '物流单号', width: 180 },
  { key: 'status', title: '发货状态', width: 120 },
  { key: 'item_count', title: '发货明细', width: 120 },
];
const statusOptions = [{ label: '全部状态', value: '' }, ...DELIVERY_STATUS_DICT.options()];
const canSubmit = hasAccessByCodes(['supplier.portal.shipment.submit']);
const orderOptions = computed(() => orders.value.filter((row) => ['ORDERED', 'PARTIAL'].includes(row.status)).map((row) => ({ label: `${row.po_no} · ${PURCHASE_ORDER_STATUS_DICT.label(row.status)}`, value: row.id })));

async function load() {
  loading.value = true;
  try {
    const result = await getSupplierShipmentListApi({ page: page.value, page_size: pageSize.value, keyword: keyword.value || undefined, status: status.value || undefined });
    rows.value = result.items;
    total.value = result.total;
  } finally { loading.value = false; }
}
async function loadOrders() {
  const result = await getSupplierOrderListApi({ page: 1, page_size: 100 });
  orders.value = result.items.filter((row) => ['ORDERED', 'PARTIAL'].includes(row.status));
}
async function onOrderChange(id?: number) {
  selectedOrder.value = id;
  lines.value = [];
  if (!id) return;
  const result = await getSupplierOrderApi(id);
  lines.value = (result.items ?? []).map((item) => ({
    id: item.id,
    name: item.product_name_snapshot,
    orderQuantity: Number(item.order_quantity),
    receivedQuantity: Number(item.received_quantity),
    quantity: 0,
    unitId: item.unit_id,
  }));
}
function openCreate() {
  selectedOrder.value = undefined;
  shipmentDate.value = dayjs();
  expectedDate.value = undefined;
  logisticsCompany.value = '';
  trackingNo.value = '';
  note.value = '';
  lines.value = [];
  modalOpen.value = true;
}
async function submit() {
  const items = lines.value.filter((line) => line.quantity > 0);
  if (!selectedOrder.value || items.length === 0) {
    message.warning('请选择采购订单并填写至少一项发货数量');
    return;
  }
  saving.value = true;
  try {
    await createSupplierShipmentApi({
      po_id: selectedOrder.value,
      shipment_date: shipmentDate.value?.format('YYYY-MM-DD'),
      expected_arrival_date: expectedDate.value?.format('YYYY-MM-DD'),
      logistics_company: logisticsCompany.value.trim() || undefined,
      tracking_no: trackingNo.value.trim() || undefined,
      note: note.value.trim() || undefined,
      items: items.map((line) => ({ po_item_id: line.id, planned_quantity: line.quantity })),
    });
    message.success('发货通知已提交');
    modalOpen.value = false;
    await load();
  } finally { saving.value = false; }
}

onMounted(loadOrders);
</script>

<template>
  <SupplierRecordList
    export-permission="supplier.portal.shipment.export"
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
    subtitle="提交后会进入仓库收货流程；发货数量不能超过订单剩余未收数量。"
    title="发货通知"
  >
    <template #toolbar><Button v-if="canSubmit" type="primary" @click="openCreate"><Plus class="size-5" />新建发货通知</Button></template>
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'delivery_no'"><span>{{ record.delivery_no }}</span></template>
      <template v-else-if="column.key === 'po_no'">{{ record.po_no }}</template>
      <template v-else-if="column.key === 'shipment_date'">{{ formatDate(record.shipment_date) }}</template>
      <template v-else-if="column.key === 'expected_arrival_date'">{{ formatDate(record.expected_arrival_date) }}</template>
      <template v-else-if="column.key === 'tracking_no'">{{ record.tracking_no || '—' }}</template>
      <template v-else-if="column.key === 'status'"><Tag :color="DELIVERY_STATUS_DICT.color(record.status)">{{ DELIVERY_STATUS_DICT.label(record.status) }}</Tag></template>
      <template v-else-if="column.key === 'item_count'"><span class="text-muted-foreground">{{ record.items.length }} 项明细</span></template>
    </template>
  </SupplierRecordList>

  <Modal v-model:open="modalOpen" :confirm-loading="saving" title="新建发货通知" width="760px" @ok="submit">
    <div class="space-y-4 py-2">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div class="sm:col-span-2"><div class="mb-1 text-sm text-muted-foreground">采购订单 <span class="text-red-500">*</span></div><Select :value="selectedOrder" :options="orderOptions" class="w-full" placeholder="选择订单" @change="onOrderChange(Number($event))" /></div>
        <div><div class="mb-1 text-sm text-muted-foreground">发货日期</div><DatePicker v-model:value="shipmentDate" class="w-full" /></div>
        <div><div class="mb-1 text-sm text-muted-foreground">预计到货日期</div><DatePicker v-model:value="expectedDate" class="w-full" /></div>
        <div><div class="mb-1 text-sm text-muted-foreground">物流公司</div><Input v-model:value="logisticsCompany" :maxlength="128" /></div>
        <div><div class="mb-1 text-sm text-muted-foreground">物流单号</div><Input v-model:value="trackingNo" :maxlength="128" /></div>
      </div>
      <div v-if="lines.length" class="rounded-md border">
        <div class="border-b px-3 py-2 font-medium">发货明细</div>
        <div v-for="line in lines" :key="line.id" class="grid grid-cols-[minmax(0,1fr)_150px] items-center gap-3 border-b px-3 py-2 last:border-0">
          <div class="min-w-0"><div class="truncate font-medium">{{ line.name }}</div><div class="text-xs text-muted-foreground">订单 {{ formatQuantity(line.orderQuantity) }} · 已收 {{ formatQuantity(line.receivedQuantity) }}</div></div>
          <InputNumber v-model:value="line.quantity" :min="0" :max="Math.max(0, line.orderQuantity - line.receivedQuantity)" :precision="3" class="w-full" placeholder="本次发货" />
        </div>
      </div>
      <div><div class="mb-1 text-sm text-muted-foreground">备注</div><Input.TextArea v-model:value="note" :maxlength="1000" :rows="2" /></div>
    </div>
  </Modal>
</template>
