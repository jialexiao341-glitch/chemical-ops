<script lang="ts" setup>
import { ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { Alert, Empty, message, Select, Spin } from 'antdv-next';

import { createAcceptanceApi, getDeliveryListApi } from '#/api';

const emit = defineEmits(['success']);

/**
 * 创建质量验收记录。
 * 只有「已收货」的到货单可以送检，创建后到货单进入检验中。
 */
const deliveryId = ref<number>();
const options = ref<Array<{ label: string; value: number }>>([]);
const loading = ref(false);

const [Modal, modalApi] = useVbenModal({
  async onConfirm() {
    if (!deliveryId.value) {
      message.warning('请选择需要送检的到货单');
      return;
    }
    modalApi.lock();
    try {
      await createAcceptanceApi(deliveryId.value);
      message.success('已创建质量验收记录');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，这里保持弹窗打开，
      // 让用户修正后重新提交；不吞掉异常会导致未捕获的 Promise 拒绝。
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    deliveryId.value = undefined;
    loading.value = true;
    try {
      const res = await getDeliveryListApi({
        page: 1,
        page_size: 100,
        status: 'RECEIVED',
      });
      options.value = res.items.map((item) => ({
        label: `${item.delivery_no}（到货单 #${item.id}）`,
        value: item.id,
      }));
    } finally {
      loading.value = false;
    }
  },
});
</script>

<template>
  <Modal title="创建质量验收" class="w-[540px] max-w-[100vw]">
    <Spin :spinning="loading">
      <div class="space-y-4 px-1">
        <Alert
          message="只有状态为「已收货」的到货单可以送检；创建后到货单会进入检验中。"
          type="info"
          show-icon
        />
        <Empty
          v-if="options.length === 0 && !loading"
          description="当前没有待送检的到货单"
        />
        <Select
          v-else
          v-model:value="deliveryId"
          :options="options"
          class="w-full"
          placeholder="请选择待送检的到货单"
          show-search
        />
      </div>
    </Spin>
  </Modal>
</template>
