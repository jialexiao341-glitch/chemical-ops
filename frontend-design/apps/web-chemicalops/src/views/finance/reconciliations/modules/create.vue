<script lang="ts" setup>
import { ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { Alert, Empty, Input, message, Select, Spin } from 'antdv-next';

import { createReconciliationApi, getPurchaseOrderListApi } from '#/api';

const emit = defineEmits(['success']);

/**
 * 创建财务对账单。
 * 只有「收货与质量验收全部完成」的订单可建，后端强校验；
 * 这里按订单状态 COMPLETED 过滤出候选，失败提示由请求层透出。
 */
const poId = ref<number>();
const note = ref('');
const options = ref<Array<{ label: string; value: number }>>([]);
const loading = ref(false);

/** antd Select 默认按 value（数字 id）过滤，show-search 需显式按 label 搜索 */
function filterByLabel(input: string, option: { label: string }) {
  return option.label.toLowerCase().includes(input.toLowerCase());
}

const [Modal, modalApi] = useVbenModal({
  async onConfirm() {
    if (!poId.value) {
      message.warning('请选择需要对账的采购订单');
      return;
    }
    modalApi.lock();
    try {
      await createReconciliationApi({
        note: note.value.trim() || undefined,
        po_id: poId.value,
      });
      message.success('已创建对账单');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层已弹出后端中文错误，保持弹窗打开以便换单重试
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    poId.value = undefined;
    note.value = '';
    loading.value = true;
    try {
      const res = await getPurchaseOrderListApi({
        page: 1,
        page_size: 100,
        status: 'COMPLETED',
      });
      options.value = res.items.map((item) => ({
        label: `${item.po_no}（${item.order_amount}）`,
        value: item.id,
      }));
    } finally {
      loading.value = false;
    }
  },
});
</script>

<template>
  <Modal title="创建对账单" class="w-[540px]">
    <Spin :spinning="loading">
      <div class="space-y-4 px-1">
        <Alert
          message="只有收货与质量验收全部完成的订单可以创建对账单；创建后为草稿，确认后才能录入发票和发起付款。"
          type="info"
          show-icon
        />
        <Empty
          v-if="options.length === 0 && !loading"
          description="当前没有已完成的采购订单"
        />
        <Select
          v-else
          v-model:value="poId"
          :filter-option="filterByLabel"
          :options="options"
          class="w-full"
          placeholder="请选择已完成的采购订单"
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
