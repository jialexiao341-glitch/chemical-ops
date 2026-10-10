<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';

import { Alert, Input, message } from 'antdv-next';

import { cancelPurchaseOrderApi } from '#/api';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['procurement.orders.write']));
const emit = defineEmits(['success']);

/** 取消采购订单，后端要求必须填写原因 */
const orderId = ref<number>();
const poNo = ref('');
const reason = ref('');

const [Modal, modalApi] = useVbenModal<null | { id: number; poNo: string }>({
  async onConfirm() {
    if (!canConfirm.value) return;
    if (!reason.value.trim()) {
      message.warning('请填写取消原因');
      return;
    }
    if (!orderId.value) {
      return;
    }
    modalApi.lock();
    try {
      await cancelPurchaseOrderApi(orderId.value, reason.value.trim());
      message.success('订单已取消');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，这里保持弹窗打开，
      // 让用户修正后重新提交；不吞掉异常会导致未捕获的 Promise 拒绝。
    } finally {
      modalApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (isOpen) {
      const data = modalApi.getData();
      orderId.value = data?.id;
      poNo.value = data?.poNo ?? '';
      reason.value = '';
    }
  },
});

const title = computed(() => `取消采购订单 ${poNo.value}`);
</script>

<template>
  <Modal :show-confirm-button="canConfirm" :title="title" class="w-[520px] max-w-[100vw]">
    <div class="space-y-4 px-1">
      <Alert
        message="只有草稿、审批中或已批准但尚未正式下单的订单可以取消。"
        type="warning"
        show-icon
      />
      <div>
        <div class="mb-2 text-sm">
          取消原因 <span class="text-red-500">*</span>
        </div>
        <Input.TextArea
          v-model:value="reason"
          :maxlength="500"
          :rows="3"
          placeholder="请填写取消原因（必填）"
        />
      </div>
    </div>
  </Modal>
</template>
