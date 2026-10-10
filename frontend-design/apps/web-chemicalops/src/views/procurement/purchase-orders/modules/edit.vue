<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';

import { Alert, DatePicker, Input, message } from 'antdv-next';
import dayjs, { type Dayjs } from 'dayjs';

import { updatePurchaseOrderApi } from '#/api';
import type { PurchaseOrderApi } from '#/api';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['procurement.orders.write']));
const emit = defineEmits(['success']);

const orderId = ref<number>();
const poNo = ref('');
const deliveryAddress = ref('');
const expectedArrivalDate = ref<Dayjs | null>(null);
const note = ref('');

const [Modal, modalApi] = useVbenModal<null | {
  id: number;
  order: PurchaseOrderApi.PurchaseOrder;
  poNo: string;
}>({
  async onConfirm() {
    if (!canConfirm.value) return;
    if (!orderId.value) return;
    modalApi.lock();
    try {
      await updatePurchaseOrderApi(orderId.value, {
        delivery_address: deliveryAddress.value.trim() || null,
        expected_arrival_date: expectedArrivalDate.value?.format('YYYY-MM-DD') ?? null,
        note: note.value.trim() || null,
      });
      message.success('采购订单草稿已更新');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层负责展示服务端错误，保留弹窗以便修正后重试。
    } finally {
      modalApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (!isOpen) return;
    const data = modalApi.getData();
    orderId.value = data?.id;
    poNo.value = data?.poNo ?? '';
    deliveryAddress.value = data?.order.delivery_address ?? '';
    expectedArrivalDate.value = data?.order.expected_arrival_date
      ? dayjs(data.order.expected_arrival_date)
      : null;
    note.value = data?.order.note ?? '';
  },
});

const title = computed(() => `编辑采购订单草稿 ${poNo.value}`);
</script>

<template>
  <Modal :show-confirm-button="canConfirm" :title="title" class="w-[560px] max-w-[100vw]">
    <div class="space-y-4 px-1">
      <Alert
        message="草稿阶段仅可修改收货地址、期望到货日和备注；提交审批后不可修改。"
        type="info"
        show-icon
      />
      <div>
        <div class="mb-2 text-sm">收货地址</div>
        <Input v-model:value="deliveryAddress" :maxlength="500" />
      </div>
      <div>
        <div class="mb-2 text-sm">期望到货日</div>
        <DatePicker
          v-model:value="expectedArrivalDate"
          class="w-full"
          format="YYYY-MM-DD"
        />
      </div>
      <div>
        <div class="mb-2 text-sm">备注</div>
        <Input.TextArea v-model:value="note" :maxlength="1000" :rows="3" />
      </div>
    </div>
  </Modal>
</template>
