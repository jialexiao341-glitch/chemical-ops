<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';

import { Alert, Input, message } from 'antdv-next';

import { selectQuoteApi } from '#/api';
import { formatAmount } from '#/utils/format';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['procurement.rfqs.award']));
const emit = defineEmits(['success']);

/** 中选报价弹窗的载荷 */
interface SelectQuotePayload {
  comparisonId: number;
  quoteId: number;
  rfqId: number;
  supplierName: string;
  totalAmount?: null | string;
  unitPrice?: null | string;
}

/**
 * 确认中选报价。
 * 确认后其他已提交报价会被置为未中选，询价单进入已关闭状态。
 */
const payload = ref<null | SelectQuotePayload>();
const reason = ref('');

const [Modal, modalApi] = useVbenModal<null | SelectQuotePayload>({
  async onConfirm() {
    if (!canConfirm.value) return;
    if (!reason.value.trim()) {
      message.warning('请填写中选理由');
      return;
    }
    const data = payload.value;
    if (!data) {
      return;
    }
    modalApi.lock();
    try {
      await selectQuoteApi(data.rfqId, {
        comparison_id: data.comparisonId,
        quote_id: data.quoteId,
        selection_reason: reason.value.trim(),
      });
      message.success('已确认中选报价');
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
      payload.value = modalApi.getData();
      reason.value = '';
    }
  },
});

const title = computed(() => `确认中选 · ${payload.value?.supplierName ?? ''}`);
</script>

<template>
  <Modal :show-confirm-button="canConfirm" :title="title" class="w-[540px] max-w-[100vw]">
    <div class="space-y-4 px-1">
      <Alert
        message="确认后该询价单关闭，其他已提交报价会被置为未中选，且不可撤销。"
        type="warning"
        show-icon
      />
      <div class="bg-accent rounded-md px-3 py-2 text-sm">
        <div>
          供应商：<span class="font-medium">{{ payload?.supplierName }}</span>
        </div>
        <div v-if="payload?.unitPrice">
          中选单价：{{ formatAmount(payload.unitPrice, 6) }}
        </div>
        <div v-if="payload?.totalAmount">
          该行金额：{{ formatAmount(payload.totalAmount) }}
        </div>
      </div>
      <div>
        <div class="mb-2 text-sm">
          中选理由 <span class="text-red-500">*</span>
        </div>
        <Input.TextArea
          v-model:value="reason"
          :maxlength="500"
          :rows="3"
          placeholder="请说明选择该报价的理由（必填）"
        />
      </div>
    </div>
  </Modal>
</template>
