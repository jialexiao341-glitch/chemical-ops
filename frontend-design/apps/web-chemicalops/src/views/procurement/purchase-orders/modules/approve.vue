<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';
import { useUserStore } from '@vben/stores';

import { Alert, Input, message } from 'antdv-next';

import { approvePurchaseOrderApi, rejectPurchaseOrderApi } from '#/api';

const emit = defineEmits(['success']);
const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();
const operatorId = ref<number>();
const canApprove = computed(() => hasAccessByCodes(['procurement.orders.approve']));
const isOwn = computed(() => String(operatorId.value) === String(userStore.userInfo?.userId));

/** 采购订单审批：通过时意见选填，驳回时必填 */
const orderId = ref<number>();
const poNo = ref('');
const action = ref<'approve' | 'reject'>('approve');
const opinion = ref('');

const isApprove = computed(() => action.value === 'approve');

const [Modal, modalApi] = useVbenModal<null | {
        action: 'approve' | 'reject';
        operatorId: number;
        id: number;
        poNo: string;
      }>({
  async onConfirm() {
    if (!canApprove.value || isOwn.value) return;
    if (!isApprove.value && !opinion.value.trim()) {
      message.warning('驳回时必须填写审批意见');
      return;
    }
    if (!orderId.value) {
      return;
    }
    modalApi.lock();
    try {
      if (isApprove.value) {
        await approvePurchaseOrderApi(orderId.value, opinion.value || undefined);
      } else {
        await rejectPurchaseOrderApi(orderId.value, opinion.value.trim());
      }
      message.success(isApprove.value ? '订单已审批通过' : '订单已驳回');
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
      operatorId.value = data?.operatorId;
      action.value = data?.action ?? 'approve';
      orderId.value = data?.id;
      poNo.value = data?.poNo ?? '';
      opinion.value = '';
    }
  },
});

const title = computed(() =>
  isApprove.value ? `审批通过 ${poNo.value}` : `驳回 ${poNo.value}`,
);
</script>

<template>
  <Modal :show-confirm-button="canApprove" :confirm-disabled="isOwn" :title="title" class="w-[520px] max-w-[100vw]">
    <div class="space-y-4 px-1">
      <Alert
        :message="
          isOwn ? '不能审批本人经办的记录，请由其他有审批权限的人员处理。' : isApprove
            ? '审批通过后订单进入已批准状态，可执行正式下单。'
            : '驳回后订单会回到草稿状态，采购员可修改后重新提交。'
        "
        :type="isApprove ? 'info' : 'warning'"
        show-icon
      />
      <div>
        <div class="mb-2 text-sm">
          审批意见
          <span v-if="!isApprove" class="text-red-500">*</span>
        </div>
        <Input.TextArea
          v-model:value="opinion"
          :maxlength="500"
          :rows="3"
          :placeholder="isApprove ? '选填' : '请说明驳回原因（必填）'"
        />
      </div>
    </div>
  </Modal>
</template>
