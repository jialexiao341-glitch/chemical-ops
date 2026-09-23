<script lang="ts" setup>
import { ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import {
  Alert,
  Empty,
  Input,
  InputNumber,
  message,
  Select,
  Spin,
} from 'antdv-next';

import { createPaymentApi, getReconciliationListApi } from '#/api';
import { PAYMENT_METHOD_DICT } from '#/constants/dictionary';

const emit = defineEmits(['success']);

/**
 * 发起付款申请。
 * 后端校验：仅 CONFIRMED 对账单可付款，累计付款不超应付，
 * 且已核验发票金额必须足以覆盖本次付款。
 */
const reconciliationId = ref<number>();
const amount = ref<null | number>(null);
const paymentMethod = ref('BANK_TRANSFER');
const note = ref('');
const options = ref<Array<{ label: string; value: number }>>([]);
const loading = ref(false);

/** antd Select 默认按 value（数字 id）过滤，show-search 需显式按 label 搜索 */
function filterByLabel(input: string, option: { label: string }) {
  return option.label.toLowerCase().includes(input.toLowerCase());
}

const [Modal, modalApi] = useVbenModal({
  async onConfirm() {
    if (!reconciliationId.value) {
      message.warning('请选择对账单');
      return;
    }
    if (!amount.value || amount.value <= 0) {
      message.warning('请填写大于 0 的付款金额');
      return;
    }
    modalApi.lock();
    try {
      await createPaymentApi({
        amount: amount.value,
        note: note.value.trim() || undefined,
        payment_method: paymentMethod.value,
        reconciliation_id: reconciliationId.value,
      });
      message.success('付款申请已发起（待审批）');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层已弹出后端中文错误，保持弹窗打开
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    reconciliationId.value = undefined;
    amount.value = null;
    paymentMethod.value = 'BANK_TRANSFER';
    note.value = '';
    loading.value = true;
    try {
      const res = await getReconciliationListApi({
        page: 1,
        page_size: 100,
        status: 'CONFIRMED',
      });
      options.value = res.items.map((item) => ({
        label: `${item.reconciliation_no}（应付 ${item.total_amount} ${item.currency_code}）`,
        value: item.id,
      }));
    } finally {
      loading.value = false;
    }
  },
});
</script>

<template>
  <Modal title="发起付款申请" class="w-[560px]">
    <Spin :spinning="loading">
      <div class="space-y-4 px-1">
        <Alert
          message="只有已确认的对账单可以发起付款；付款金额受应付总额与人工复核通过的发票金额双重限制，审批通过后由授权人员根据外部凭证登记付款。"
          type="info"
          show-icon
        />
        <Empty
          v-if="options.length === 0 && !loading"
          description="当前没有已确认的对账单"
        />
        <Select
          v-else
          v-model:value="reconciliationId"
          :filter-option="filterByLabel"
          :options="options"
          class="w-full"
          placeholder="请选择已确认的对账单"
          show-search
        />
        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="mb-1 text-sm">
              付款金额 <span class="text-red-500">*</span>
            </div>
            <InputNumber
              v-model:value="amount"
              :min="0"
              :precision="2"
              class="w-full"
              placeholder="0.00"
            />
          </div>
          <div>
            <div class="mb-1 text-sm">付款方式</div>
            <Select
              v-model:value="paymentMethod"
              :options="PAYMENT_METHOD_DICT.options()"
              class="w-full"
            />
          </div>
        </div>
        <Input.TextArea
          v-model:value="note"
          :maxlength="1000"
          :rows="2"
          placeholder="备注（选填）"
        />
      </div>
    </Spin>
  </Modal>
</template>
