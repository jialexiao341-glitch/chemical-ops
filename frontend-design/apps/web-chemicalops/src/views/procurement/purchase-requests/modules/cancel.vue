<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';

import { Alert, Input, message } from 'antdv-next';

import { cancelPurchaseRequestApi } from '#/api';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['procurement.requests.write']));
const emit = defineEmits(['success']);

/** 取消采购申请，后端要求必须填写原因 */
const requestId = ref<number>();
const requestNo = ref('');
const reason = ref('');

const [Modal, modalApi] = useVbenModal<null | { id: number; requestNo: string }>({
  async onConfirm() {
    if (!canConfirm.value) return;
    if (!reason.value.trim()) {
      message.warning('请填写取消原因');
      return;
    }
    if (!requestId.value) {
      return;
    }
    modalApi.lock();
    try {
      await cancelPurchaseRequestApi(requestId.value, reason.value.trim());
      message.success('已取消该申请');
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
      requestId.value = data?.id;
      requestNo.value = data?.requestNo ?? '';
      reason.value = '';
    }
  },
});

const title = computed(() => `取消采购申请 ${requestNo.value}`);
</script>

<template>
  <Modal :show-confirm-button="canConfirm" :title="title" class="w-[520px] max-w-[100vw]">
    <div class="space-y-4 px-1">
      <Alert
        message="取消后该申请不可恢复；已批准的申请无法取消。"
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
