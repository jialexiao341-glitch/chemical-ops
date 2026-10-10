<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';

import { Alert, Empty, message, Select, Spin } from 'antdv-next';

import { createAcceptanceApi, getAcceptanceAssignmentOptionsApi } from '#/api';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['quality.acceptances.assign']));
const emit = defineEmits(['success']);

/**
 * 创建质量验收记录。
 * 只有「已收货」的到货单可以送检，创建后到货单进入检验中。
 */
const deliveryId = ref<number>();
const inspectorId = ref<number>();
const inspectorOptions = ref<Array<{ label: string; value: number }>>([]);
const options = ref<Array<{ label: string; value: number }>>([]);
const loading = ref(false);

const [Modal, modalApi] = useVbenModal({
  async onConfirm() {
    if (!canConfirm.value) return;
    if (!deliveryId.value) {
      message.warning('请选择需要送检的到货单');
      return;
    }
    if (!inspectorId.value) {
      message.warning('请选择负责办理的检验员');
      return;
    }
    modalApi.lock();
    try {
      await createAcceptanceApi(deliveryId.value, inspectorId.value);
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
    inspectorId.value = undefined;
    options.value = [];
    inspectorOptions.value = [];
    loading.value = true;
    try {
      const res = await getAcceptanceAssignmentOptionsApi();
      inspectorOptions.value = res.inspectors.map((item) => ({
        label: `${item.display_name}（${item.username}）`, value: item.id,
      }));
      options.value = res.deliveries.map((item) => ({
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
  <Modal :show-confirm-button="canConfirm" title="创建质量验收" class="w-[540px] max-w-[100vw]">
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
        <Select
          v-model:value="inspectorId"
          :options="inspectorOptions"
          class="w-full"
          placeholder="请选择负责办理的检验员"
          show-search
          option-filter-prop="label"
        />
      </div>
    </Spin>
  </Modal>
</template>
