<script lang="ts" setup>
import type { PurchaseOrderApi } from '#/api';

import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { ArrowLeft } from '@vben/icons';

import {
  Button,
  Card,
  Descriptions,
  DescriptionsItem,
  Empty,
  Input,
  message,
  Modal,
  Spin,
  Table,
  Tag,
} from 'antdv-next';

import {
  confirmSupplierOrderApi,
  getSupplierOrderApi,
  getUnitListApi,
  rejectSupplierOrderApi,
} from '#/api';
import {
  LINE_STATUS_DICT,
  PURCHASE_ORDER_STATUS_DICT,
} from '#/constants/dictionary';
import {
  formatAmount,
  formatDate,
  formatDateTime,
  formatQuantity,
} from '#/utils/format';

defineOptions({ name: 'SupplierOrderDetail' });

const route = useRoute();
const router = useRouter();
const { hasAccessByCodes } = useAccess();
const order = ref<PurchaseOrderApi.PurchaseOrder>();
const unitNames = ref(new Map<number, string>());
const loading = ref(false);
const acting = ref(false);
const rejectVisible = ref(false);
const rejectReason = ref('');

const canRespond = computed(
  () =>
    Boolean(
      order.value &&
        ['ORDERED', 'PARTIAL', 'COMPLETED'].includes(order.value.status) &&
        !order.value.supplier_confirmed_at &&
        hasAccessByCodes(['supplier.portal.confirm']),
    ),
);

const itemColumns = [
  { dataIndex: 'line_no', key: 'line_no', title: '行号', width: 70 },
  { dataIndex: 'product_name_snapshot', key: 'product_name_snapshot', title: '物料', minWidth: 180 },
  { dataIndex: 'supplier_model_snapshot', key: 'supplier_model_snapshot', title: '供应商型号', minWidth: 140 },
  { dataIndex: 'order_quantity', key: 'order_quantity', title: '订购数量', width: 120, align: 'right' as const },
  { dataIndex: 'unit_id', key: 'unit_id', title: '单位', width: 90 },
  { dataIndex: 'unit_price', key: 'unit_price', title: '单价', width: 120, align: 'right' as const },
  { dataIndex: 'tax_rate', key: 'tax_rate', title: '税率', width: 90, align: 'right' as const },
  { dataIndex: 'planned_arrival_date', key: 'planned_arrival_date', title: '计划到货', width: 130 },
  { dataIndex: 'received_quantity', key: 'received_quantity', title: '已收数量', width: 120, align: 'right' as const },
  { dataIndex: 'status', key: 'status', title: '明细状态', width: 110 },
];

async function load() {
  const orderId = Number(route.params.id);
  if (!Number.isInteger(orderId) || orderId <= 0) {
    return;
  }
  loading.value = true;
  try {
    const [detail, units] = await Promise.all([
      getSupplierOrderApi(orderId),
      getUnitListApi(),
    ]);
    order.value = detail;
    unitNames.value = new Map(units.map((unit) => [unit.id, unit.unit_name]));
  } finally {
    loading.value = false;
  }
}

async function confirmOrder() {
  if (!order.value) {
    return;
  }
  acting.value = true;
  try {
    await confirmSupplierOrderApi(order.value.id);
    message.success('已确认采购订单');
    await load();
  } catch {
    // 请求层已展示后端返回的中文错误。
  } finally {
    acting.value = false;
  }
}

function askConfirm() {
  Modal.confirm({
    content: `确认接受采购订单 ${order.value?.po_no}？`,
    onOk: confirmOrder,
    okText: '确认订单',
    title: '确认采购订单',
  });
}

async function rejectOrder() {
  if (!order.value || !rejectReason.value.trim()) {
    message.warning('请填写拒绝原因');
    return;
  }
  acting.value = true;
  try {
    await rejectSupplierOrderApi(order.value.id, rejectReason.value.trim());
    rejectVisible.value = false;
    rejectReason.value = '';
    message.success('已拒绝采购订单');
    await load();
  } catch {
    // 请求层已展示后端返回的中文错误。
  } finally {
    acting.value = false;
  }
}

onMounted(load);
</script>

<template>
  <Page auto-content-height>
    <Spin :spinning="loading">
      <Empty v-if="!order && !loading" description="未找到该采购订单" />
      <div v-else-if="order" class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <Button size="small" type="text" @click="router.back()">
              <ArrowLeft class="size-4" />
              返回订单列表
            </Button>
            <span class="text-lg font-semibold">{{ order.po_no }}</span>
            <Tag :color="PURCHASE_ORDER_STATUS_DICT.color(order.status)">
              {{ PURCHASE_ORDER_STATUS_DICT.label(order.status) }}
            </Tag>
          </div>
          <div v-if="canRespond" class="flex gap-2">
            <Button :loading="acting" danger @click="rejectVisible = true">
              拒绝订单
            </Button>
            <Button :loading="acting" type="primary" @click="askConfirm">
              确认订单
            </Button>
          </div>
        </div>

        <Card title="订单信息">
          <Descriptions :column="{ xs: 1, sm: 2, md: 3 }" bordered size="small">
            <DescriptionsItem label="订单编号">{{ order.po_no }}</DescriptionsItem>
            <DescriptionsItem label="订单状态">
              <Tag :color="PURCHASE_ORDER_STATUS_DICT.color(order.status)">
                {{ PURCHASE_ORDER_STATUS_DICT.label(order.status) }}
              </Tag>
            </DescriptionsItem>
            <DescriptionsItem label="订单金额">
              {{ formatAmount(order.order_amount) }} {{ order.currency_code }}
            </DescriptionsItem>
            <DescriptionsItem label="下单日期">{{ formatDate(order.order_date) }}</DescriptionsItem>
            <DescriptionsItem label="期望到货">{{ formatDate(order.expected_arrival_date) }}</DescriptionsItem>
            <DescriptionsItem label="供应商确认">
              {{ order.supplier_confirmed_at ? formatDateTime(order.supplier_confirmed_at) : '待确认' }}
            </DescriptionsItem>
            <DescriptionsItem label="送货地址" :span="{ xs: 1, sm: 2, md: 3 }">
              {{ order.delivery_address || '未提供' }}
            </DescriptionsItem>
          </Descriptions>
        </Card>

        <Card :title="`订单明细（${order.items?.length ?? 0}）`">
          <Table
            :columns="itemColumns"
            :data-source="order.items ?? []"
            :pagination="false"
            :scroll="{ x: 1260 }"
            row-key="id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'order_quantity'">
                {{ formatQuantity(record.order_quantity) }}
              </template>
              <template v-else-if="column.key === 'unit_id'">
                {{ unitNames.get(record.unit_id) ?? `#${record.unit_id}` }}
              </template>
              <template v-else-if="column.key === 'unit_price'">
                {{ formatAmount(record.unit_price, 6) }} {{ order.currency_code }}
              </template>
              <template v-else-if="column.key === 'tax_rate'">
                {{ record.tax_rate == null ? '-' : `${formatQuantity(record.tax_rate)}%` }}
              </template>
              <template v-else-if="column.key === 'planned_arrival_date'">
                {{ formatDate(record.planned_arrival_date) }}
              </template>
              <template v-else-if="column.key === 'received_quantity'">
                {{ formatQuantity(record.received_quantity) }}
              </template>
              <template v-else-if="column.key === 'status'">
                <Tag :color="record.status === 'OPEN' ? 'processing' : LINE_STATUS_DICT.color(record.status)">
                  {{ record.status === 'OPEN' ? '待收货' : LINE_STATUS_DICT.label(record.status) }}
                </Tag>
              </template>
            </template>
          </Table>
        </Card>
      </div>
    </Spin>

    <Modal
      v-model:open="rejectVisible"
      cancel-text="返回"
      ok-text="提交拒绝"
      title="拒绝采购订单"
      :confirm-loading="acting"
      @ok="rejectOrder"
    >
      <div class="py-2">
        <div class="mb-2 text-sm">拒绝原因 <span class="text-red-500">*</span></div>
        <Input.TextArea
          v-model:value="rejectReason"
          :maxlength="1000"
          :rows="4"
          placeholder="请说明无法接受该订单的原因"
        />
      </div>
    </Modal>
  </Page>
</template>
