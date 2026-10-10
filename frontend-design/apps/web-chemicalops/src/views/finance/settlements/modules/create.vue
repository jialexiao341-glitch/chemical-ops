<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';

import {
  Alert,
  Empty,
  Input,
  message,
  Select,
  Spin,
} from 'antdv-next';

import { createSettlementApi, getReconciliationListApi } from '#/api';

const emit = defineEmits(['success']);
const { hasAccessByCodes } = useAccess();
const canWrite = computed(() => hasAccessByCodes(['finance.settlements.write']));

/**
 * 创建采购结算单。
 * 后端校验：仅已确认且未关闭、且实际付款达到应付总额的对账单可结算；
 * 确认结算单时会关闭对账单。
 */
const reconciliationId = ref<number>();
const note = ref('');
const options = ref<Array<{ label: string; value: number }>>([]);
const loading = ref(false);

/** antd Select 默认按 value（数字 id）过滤，show-search 需显式按 label 搜索 */
function filterByLabel(input: string, option: { label: string }) {
  return option.label.toLowerCase().includes(input.toLowerCase());
}

const [Modal, modalApi] = useVbenModal({
  async onConfirm() {
    if (!canWrite.value) return;
    if (!reconciliationId.value) {
      message.warning('请选择对账单');
      return;
    }
    modalApi.lock();
    try {
      await createSettlementApi({
        note: note.value.trim() || undefined,
        reconciliation_id: reconciliationId.value,
      });
      message.success('结算单已创建（草稿）');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层已弹出后端中文错误（如未足额付款），保持弹窗打开
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    reconciliationId.value = undefined;
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
  <Modal :show-confirm-button="canWrite" title="创建结算单" class="w-[560px] max-w-[100vw]">
    <Spin :spinning="loading">
      <div class="space-y-4 px-1">
        <Alert
          message="只有已确认、未关闭且已足额付款的对账单可以结算；确认结算单会同时关闭对账单。"
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
