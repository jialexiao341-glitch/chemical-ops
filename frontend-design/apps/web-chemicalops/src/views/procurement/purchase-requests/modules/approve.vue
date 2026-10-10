<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';
import { useUserStore } from '@vben/stores';

import { Alert, Input, message } from 'antdv-next';

import {
  approvePurchaseRequestApi,
  rejectPurchaseRequestApi,
} from '#/api';

const emit = defineEmits(['success']);
const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();
const operatorId = ref<number>();
const canApprove = computed(() => hasAccessByCodes(['procurement.requests.approve']));
const isOwn = computed(() => String(operatorId.value) === String(userStore.userInfo?.userId));

/** 审批或驳回采购申请，驳回时要求填写意见 */
const requestId = ref<number>();
const requestNo = ref('');
const action = ref<'approve' | 'reject'>('approve');
const opinion = ref('');
const submitting = ref(false);

const isApprove = computed(() => action.value === 'approve');

const [Modal, modalApi] = useVbenModal<null | {
        action: 'approve' | 'reject';
        operatorId: number;
        id: number;
        requestNo: string;
      }>({
  async onConfirm() {
    if (!canApprove.value || isOwn.value) return;
    if (!isApprove.value && !opinion.value.trim()) {
      message.warning('驳回时必须填写审批意见');
      return;
    }
    if (!requestId.value) {
      return;
    }
    submitting.value = true;
    modalApi.lock();
    try {
      if (isApprove.value) {
        await approvePurchaseRequestApi(requestId.value, opinion.value || undefined);
      } else {
        await rejectPurchaseRequestApi(requestId.value, opinion.value.trim());
      }
      message.success(isApprove.value ? '已审批通过' : '已驳回');
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
  onOpenChange(isOpen) {
    if (isOpen) {
      const data = modalApi.getData();
      operatorId.value = data?.operatorId;
      action.value = data?.action ?? 'approve';
      requestId.value = data?.id;
      requestNo.value = data?.requestNo ?? '';
      opinion.value = '';
    }
  },
});

const title = computed(() =>
  isApprove.value ? '审批通过采购申请' : '驳回采购申请',
);
</script>

<template>
  <Modal :show-confirm-button="canApprove" :confirm-disabled="isOwn" :title="title" class="w-[520px] max-w-[100vw]">
    <div class="space-y-4 px-1">
      <Alert
        :message="
          isOwn ? '不能审批本人经办的记录，请由其他有审批权限的人员处理。' : isApprove
            ? `确认通过采购申请 ${requestNo}？通过后即可发起询价。`
            : `驳回后申请会回到可编辑状态，申请人可修改后重新提交。`
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
