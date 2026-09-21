<script lang="ts" setup>
import type { DeliveryApi } from '#/api';

import { computed, ref, watch } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import {
  Alert,
  DatePicker,
  Empty,
  InputNumber,
  message,
  Spin,
  Table,
  Tag,
} from 'antdv-next';

import { getDeliveryApi, receiveDeliveryApi } from '#/api';
import { formatQuantity } from '#/utils/format';

const emit = defineEmits(['success']);

/** 收货明细行，含用于展示的计划/短交数量 */
interface ReceiveRow {
  actual_quantity?: null | number | string;
  batch_no?: string;
  delivery_item_id: number;
  planned_quantity: number;
  productName: string;
  short_quantity: number;
}

/**
 * 确认收货。
 *
 * 短交数量默认按「计划 - 实收」自动推算；
 * 存在短交时后端会自动创建 SHORT_DELIVERY 异常并通知采购经理。
 */
const payload = ref<DeliveryApi.Delivery>();
const actualArrivalDate = ref<string>();
const rows = ref<ReceiveRow[]>([]);
const loading = ref(false);
const submitting = ref(false);

const hasShortDelivery = computed(() =>
  rows.value.some((row) => row.short_quantity > 0),
);

const [Modal, modalApi] = useVbenModal<null | DeliveryApi.Delivery>({
  async onConfirm() {
    const delivery = payload.value;
    if (!delivery) {
      return;
    }
    if (
      rows.value.some(
        (row) =>
          row.actual_quantity === undefined ||
          row.actual_quantity === null ||
          row.actual_quantity === '',
      )
    ) {
      message.warning('请填写全部明细的实收数量');
      return;
    }
    submitting.value = true;
    modalApi.lock();
    try {
      await receiveDeliveryApi(delivery.id, {
        actual_arrival_date: actualArrivalDate.value,
        items: rows.value.map((row) => ({
          actual_quantity: row.actual_quantity as number,
          delivery_item_id: row.delivery_item_id,
          short_quantity: row.short_quantity,
        })),
      });
      message.success('收货已确认');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，这里保持弹窗打开，
      // 让用户修正后重新提交；不吞掉异常会产生未捕获的 Promise 拒绝。
    } finally {
      submitting.value = false;
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    actualArrivalDate.value = undefined;
    rows.value = [];
    payload.value = undefined;

    const data = modalApi.getData();
    if (!data?.id) {
      return;
    }
    loading.value = true;
    try {
      const delivery = await getDeliveryApi(data.id);
      payload.value = delivery;
      actualArrivalDate.value = delivery.actual_arrival_date ?? undefined;
      rows.value = (delivery.items ?? []).map((item) => {
        const planned = Number(item.planned_quantity ?? 0);
        // 已收过货的明细保留原实收数量，未收货的默认按计划数量填充
        const actual =
          item.actual_quantity === null || item.actual_quantity === undefined
            ? planned
            : Number(item.actual_quantity);
        return {
          actual_quantity: actual,
          batch_no: item.batch_no ?? '',
          delivery_item_id: item.id,
          planned_quantity: planned,
          productName: `明细 #${item.id}`,
          short_quantity: Math.max(planned - actual, 0),
        };
      });
    } finally {
      loading.value = false;
    }
  },
});

/** 实收数量变化时同步短交数量 */
watch(
  rows,
  (list) => {
    for (const row of list) {
      const actual = Number(row.actual_quantity ?? 0);
      row.short_quantity = Math.max(row.planned_quantity - actual, 0);
    }
  },
  { deep: true },
);

const columns = [
  { key: 'productName', title: '到货明细', width: 150 },
  { key: 'planned_quantity', title: '计划数量', width: 130 },
  { key: 'actual_quantity', title: '实收数量', width: 170 },
  { key: 'short_quantity', title: '短交数量', width: 150 },
  { key: 'batch_no', title: '批次号', width: 140 },
];
</script>

<template>
  <Modal title="确认收货" class="w-[880px]">
    <Spin :spinning="loading">
      <div class="space-y-4 px-1">
        <Alert
          v-if="hasShortDelivery"
          message="存在短交：确认收货后系统会自动创建短交异常，并通知采购经理与仓库人员。"
          type="warning"
          show-icon
        />
        <div>
          <div class="mb-2 text-sm">实际到货日期</div>
          <DatePicker
            v-model:value="actualArrivalDate"
            class="w-[240px]"
            value-format="YYYY-MM-DD"
          />
        </div>

        <Empty
          v-if="rows.length === 0 && !loading"
          description="该到货单没有明细"
        />
        <Table
          v-else
          :columns="columns"
          :data-source="rows"
          :pagination="false"
          row-key="delivery_item_id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'planned_quantity'">
              {{ formatQuantity(record.planned_quantity) }}
            </template>
            <template v-else-if="column.key === 'actual_quantity'">
              <InputNumber
                v-model:value="record.actual_quantity"
                :min="0"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'short_quantity'">
              <Tag
                :color="Number(record.short_quantity) > 0 ? 'error' : 'success'"
              >
                {{ formatQuantity(record.short_quantity) }}
              </Tag>
            </template>
            <template v-else-if="column.key === 'batch_no'">
              <span class="text-muted-foreground">
                {{ record.batch_no || '-' }}
              </span>
            </template>
          </template>
        </Table>
      </div>
    </Spin>
  </Modal>
</template>
