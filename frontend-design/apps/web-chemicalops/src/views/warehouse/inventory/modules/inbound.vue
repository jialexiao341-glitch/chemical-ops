<script lang="ts" setup>
import { ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { Alert, Input, message, Select, Spin } from 'antdv-next';

import {
  createInboundApi,
  getDeliveryListApi,
  getLocationListApi,
  getWarehouseListApi,
} from '#/api';

const emit = defineEmits(['success']);

/**
 * 库存入库。
 * 后端只允许「质量验收通过（ACCEPTED）」的到货单入库，
 * 并且同一到货明细只能生成一次入库流水。
 */
const deliveryId = ref<number>();
const warehouseId = ref<number>();
const locationId = ref<number>();
const note = ref('');

const deliveries = ref<Array<{ label: string; value: number }>>([]);
const warehouses = ref<Array<{ label: string; value: number }>>([]);
const locations = ref<Array<{ label: string; value: number }>>([]);
const loadingRefs = ref(false);
const submitting = ref(false);

const [Modal, modalApi] = useVbenModal({
  async onConfirm() {
    if (!deliveryId.value || !warehouseId.value || !locationId.value) {
      message.warning('请先选择到货单、仓库和库位');
      return;
    }
    submitting.value = true;
    modalApi.lock();
    try {
      const result = await createInboundApi({
        delivery_id: deliveryId.value,
        location_id: locationId.value,
        note: note.value || undefined,
        warehouse_id: warehouseId.value,
      });
      message.success(`入库完成，生成 ${result.transaction_count} 条库存流水`);
      emit('success');
      modalApi.close();
    } finally {
      submitting.value = false;
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    deliveryId.value = undefined;
    warehouseId.value = undefined;
    locationId.value = undefined;
    note.value = '';
    locations.value = [];
    loadingRefs.value = true;
    try {
      const [deliveryRes, warehouseList] = await Promise.all([
        // 仅展示已通过验收、可以入库的到货单
        getDeliveryListApi({ page: 1, page_size: 100, status: 'ACCEPTED' }),
        getWarehouseListApi(),
      ]);
      deliveries.value = deliveryRes.items.map((item) => ({
        label: `${item.delivery_no}（到货单 #${item.id}）`,
        value: item.id,
      }));
      warehouses.value = warehouseList.map((item) => ({
        label: `${item.warehouse_name} (${item.warehouse_code})`,
        value: item.id,
      }));
    } finally {
      loadingRefs.value = false;
    }
  },
});

async function onWarehouseChange(value: number) {
  locationId.value = undefined;
  locations.value = [];
  if (!value) {
    return;
  }
  const list = await getLocationListApi(value);
  locations.value = list.map((item) => ({
    label: `${item.location_name} (${item.location_code})`,
    value: item.id,
  }));
}
</script>

<template>
  <Modal title="库存入库" class="w-[560px]">
    <Spin :spinning="loadingRefs">
      <div class="space-y-4 px-1">
        <Alert
          message="只有状态为「验收通过」的到货单可以入库；同一到货明细只能入库一次。"
          type="info"
          show-icon
        />
        <div>
          <div class="mb-2 text-sm">到货单</div>
          <Select
            v-model:value="deliveryId"
            :options="deliveries"
            class="w-full"
            placeholder="请选择待入库的到货单"
            show-search
          />
        </div>
        <div>
          <div class="mb-2 text-sm">入库仓库</div>
          <Select
            v-model:value="warehouseId"
            :options="warehouses"
            class="w-full"
            placeholder="请选择仓库"
            show-search
            @change="onWarehouseChange"
          />
        </div>
        <div>
          <div class="mb-2 text-sm">库位</div>
          <Select
            v-model:value="locationId"
            :disabled="!warehouseId"
            :options="locations"
            class="w-full"
            :placeholder="warehouseId ? '请选择库位' : '请先选择仓库'"
            show-search
          />
        </div>
        <div>
          <div class="mb-2 text-sm">备注</div>
          <Input.TextArea
            v-model:value="note"
            :maxlength="500"
            :rows="2"
            placeholder="选填"
          />
        </div>
      </div>
    </Spin>
  </Modal>
</template>
