<script lang="ts" setup>
import type { InventoryApi } from '#/api';

import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';

import { Alert, Input, message } from 'antdv-next';

import { freezeBalanceApi, unfreezeBalanceApi } from '#/api';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['warehouse.inventory.freeze.write']));
const emit = defineEmits(['success']);

/**
 * 冻结与解冻共用同一个弹窗，由打开的载荷决定动作。
 * 后端要求必须填写原因，并会写入状态变更历史与审计日志。
 */
interface FreezePayload {
  action: 'freeze' | 'unfreeze';
  balance: InventoryApi.InventoryBalance;
  productName?: string;
}

const payload = ref<null | FreezePayload>();
const reason = ref('');
const submitting = ref(false);

const isFreeze = computed(() => payload.value?.action === 'freeze');

const [Modal, modalApi] = useVbenModal<null | FreezePayload>({
  async onConfirm() {
    if (!canConfirm.value) return;
    if (!reason.value.trim()) {
      message.warning('请填写操作原因');
      return;
    }
    const data = payload.value;
    if (!data) {
      return;
    }
    submitting.value = true;
    modalApi.lock();
    try {
      if (data.action === 'freeze') {
        await freezeBalanceApi(data.balance.id, reason.value.trim());
      } else {
        await unfreezeBalanceApi(data.balance.id, reason.value.trim());
      }
      message.success(isFreeze.value ? '已人工冻结库存' : '已解除人工冻结');
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
      payload.value = modalApi.getData();
      reason.value = '';
    }
  },
});

const title = computed(() => (isFreeze.value ? '人工冻结库存' : '解除人工冻结'));
</script>

<template>
  <Modal :show-confirm-button="canConfirm" :title="title" class="w-[520px] max-w-[100vw]">
    <div class="space-y-4 px-1">
      <Alert
        :message="
          isFreeze
            ? '人工冻结不会改变库存数量，但会阻止领用、调拨和盘点差异调整。'
            : payload?.balance.quality_hold
              ? '解除人工冻结后，质量隔离仍然生效，库存不可用。'
              : payload?.balance.batch_status !== 'ACTIVE'
                ? '解除人工冻结后，批次状态仍可能限制库存使用。'
                : '解除人工冻结后，可用量仍受锁定数量限制。'
        "
        :type="isFreeze ? 'warning' : 'info'"
        show-icon
      />
      <div>
        <div class="text-muted-foreground mb-2 text-xs">
          库存批次 #{{ payload?.balance.id }}
          <span v-if="payload?.productName"> · {{ payload.productName }}</span>
        </div>
        <Input.TextArea
          v-model:value="reason"
          :maxlength="500"
          :rows="3"
          placeholder="请填写操作原因（必填）"
          show-count
        />
      </div>
    </div>
  </Modal>
</template>
