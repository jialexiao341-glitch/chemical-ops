<script lang="ts" setup>
import type { TransferRequestApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenDrawer } from '@vben/common-ui';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import {
  createTransferApi,
  getBalanceListApi,
  getLocationListApi,
  getProductListApi,
  getUnitListApi,
  getWarehouseListApi,
  updateTransferApi,
} from '#/api';
import ItemsEditor from '#/components/items-editor/index.vue';
import { formatQuantity } from '#/utils/format';

const emit = defineEmits(['success']);
const { hasAccessByCodes } = useAccess();
const canWrite = computed(() => hasAccessByCodes(['warehouse.inventory.transfer.write']));

/**
 * 调拨明细编辑行。
 * 源端来自库存余额（一键带出产品/仓库/库位/批次/单位），
 * 目标端只选库位——库位归属仓库，提交时由库位反查目标仓库。
 */
interface TransferItemRow {
  available?: string;
  batch_id?: number;
  balance_id?: number;
  location_id?: number;
  note?: string;
  product_id?: number;
  requested_quantity?: number | string;
  source_location_id?: number;
  source_warehouse_id?: number;
  target_location_id?: number;
  target_warehouse_id?: number;
  unit_id?: number;
}

const id = ref<number>();
const items = ref<TransferItemRow[]>([]);
const balanceOptions = ref<Array<{ label: string; value: number }>>([]);
const balanceMap = ref(
  new Map<
    number,
    {
      available: string;
      batch_id: number;
      location_id: number;
      product_id: number;
      unit_id: number;
      warehouse_id: number;
    }
  >(),
);
/** 目标库位选项：location.id → 所属仓库（label 带仓库名前缀） */
const targetLocationOptions = ref<Array<{ label: string; value: number }>>([]);
const locationWarehouseMap = ref(new Map<number, number>());

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  showDefaultActions: false,
  schema: [
    {
      component: 'Textarea',
      componentProps: {
        maxlength: 500,
        placeholder: '请说明调拨用途',
        rows: 2,
      },
      fieldName: 'purpose',
      label: '调拨用途',
      rules: 'required',
    },
  ],
});

const itemColumns = [
  {
    component: 'select' as const,
    componentProps: { placeholder: '源库存批次' },
    field: 'balance_id',
    label: '源批次',
    options: () => Promise.resolve(balanceOptions.value),
    required: true,
    width: 300,
  },
  {
    component: 'select' as const,
    componentProps: { placeholder: '目标库位' },
    field: 'target_location_id',
    label: '目标库位',
    options: () => Promise.resolve(targetLocationOptions.value),
    required: true,
    width: 220,
  },
  {
    component: 'number' as const,
    componentProps: { min: 0, placeholder: '调拨数量' },
    field: 'requested_quantity',
    label: '调拨数量',
    required: true,
    width: 120,
  },
  {
    component: 'input' as const,
    componentProps: { maxlength: 200, placeholder: '备注' },
    field: 'note',
    label: '备注',
    width: 160,
  },
];

function createItemRow(): TransferItemRow {
  return {
    balance_id: undefined,
    note: '',
    requested_quantity: undefined,
    target_location_id: undefined,
  };
}

function expandRows() {
  for (const row of items.value) {
    const balance = row.balance_id
      ? balanceMap.value.get(row.balance_id)
      : undefined;
    if (balance) {
      row.batch_id = balance.batch_id;
      row.product_id = balance.product_id;
      row.source_location_id = balance.location_id;
      row.source_warehouse_id = balance.warehouse_id;
      row.unit_id = balance.unit_id;
      row.available = balance.available;
    }
    if (row.target_location_id) {
      row.target_warehouse_id =
        locationWarehouseMap.value.get(row.target_location_id);
    }
  }
}

const [Drawer, drawerApi] = useVbenDrawer<
  null | TransferRequestApi.TransferRequest
>({
  async onConfirm() {
    const record = drawerApi.getData();
    if (!canWrite.value || (record && !['DRAFT', 'REJECTED'].includes(record.status))) return;
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    if (items.value.length === 0) {
      message.warning('请至少添加一条调拨明细');
      return;
    }
    expandRows();
    for (const [index, item] of items.value.entries()) {
      if (!item.balance_id) {
        message.warning(`第 ${index + 1} 行请选择源批次`);
        return;
      }
      if (!item.target_location_id) {
        message.warning(`第 ${index + 1} 行请选择目标库位`);
        return;
      }
      if (!item.requested_quantity || Number(item.requested_quantity) <= 0) {
        message.warning(`第 ${index + 1} 行的调拨数量必须大于 0`);
        return;
      }
      if (Number(item.requested_quantity) > Number(item.available ?? 0)) {
        message.warning(
          `第 ${index + 1} 行调拨数量超过可用量 ${formatQuantity(item.available)}`,
        );
        return;
      }
      if (item.source_location_id === item.target_location_id) {
        message.warning(`第 ${index + 1} 行源库位与目标库位相同`);
        return;
      }
    }
    const values = await formApi.getValues<any>();
    const payload: TransferRequestApi.Payload = {
      items: items.value.map((item) => ({
        batch_id: Number(item.batch_id),
        note: item.note || undefined,
        product_id: Number(item.product_id),
        requested_quantity: Number(item.requested_quantity),
        source_location_id: Number(item.source_location_id),
        source_warehouse_id: Number(item.source_warehouse_id),
        target_location_id: Number(item.target_location_id),
        target_warehouse_id: Number(item.target_warehouse_id),
        unit_id: Number(item.unit_id),
      })),
      purpose: values.purpose,
    };
    drawerApi.lock();
    try {
      if (id.value) {
        await updateTransferApi(id.value, payload);
      } else {
        await createTransferApi(payload);
      }
      emit('success');
      drawerApi.close();
    } catch {
      // 请求层已统一弹出错误，保持抽屉打开
    } finally {
      drawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    const data = drawerApi.getData();
    formApi.reset();
    id.value = data?.id;
    items.value = [];

    if (balanceOptions.value.length === 0) {
      const [balances, products, warehouses, units] = await Promise.all([
        getBalanceListApi({ page: 1, page_size: 100 }),
        getProductListApi({ page: 1, page_size: 100 }),
        getWarehouseListApi(),
        getUnitListApi(),
      ]);
      const productMap = new Map(
        products.items.map((item) => [item.id, item.product_name]),
      );
      const warehouseMap = new Map(
        warehouses.map((item) => [item.id, item.warehouse_name]),
      );
      const unitMap = new Map(units.map((item) => [item.id, item.unit_name]));
      const locationPairs = await Promise.all(
        warehouses.map(async (warehouse) => {
          const locations = await getLocationListApi(warehouse.id);
          return { locations, warehouse };
        }),
      );
      const locationName = new Map<number, string>();
      for (const { locations, warehouse } of locationPairs) {
        for (const location of locations) {
          locationName.set(location.id, location.location_name);
          locationWarehouseMap.value.set(location.id, warehouse.id);
          targetLocationOptions.value.push({
            label: `${warehouse.warehouse_name}/${location.location_name}`,
            value: location.id,
          });
        }
      }

      for (const balance of balances.items) {
        if (balance.status !== 'AVAILABLE') {
          continue;
        }
        const available =
          Number(balance.quantity) - Number(balance.locked_quantity ?? 0);
        if (available <= 0) {
          continue;
        }
        const productName =
          productMap.get(balance.product_id) ?? `#${balance.product_id}`;
        const warehouseName =
          warehouseMap.get(balance.warehouse_id) ?? `#${balance.warehouse_id}`;
        balanceOptions.value.push({
          label: `${productName} @ ${warehouseName}/${locationName.get(balance.location_id) ?? `#${balance.location_id}`} 批次${balance.batch_id} 可用${formatQuantity(available)} ${unitMap.get(balance.unit_id) ?? ''}`.trim(),
          value: balance.id,
        });
        balanceMap.value.set(balance.id, {
          available: String(available),
          batch_id: Number(balance.batch_id),
          location_id: balance.location_id,
          product_id: balance.product_id,
          unit_id: balance.unit_id,
          warehouse_id: balance.warehouse_id,
        });
      }
    }

    await nextTick();
    if (data) {
      items.value = (data.items ?? []).map((item) => ({
        batch_id: item.batch_id,
        note: item.note ?? '',
        product_id: item.product_id,
        requested_quantity: item.requested_quantity,
        source_location_id: item.source_location_id,
        source_warehouse_id: item.source_warehouse_id,
        target_location_id: item.target_location_id,
        target_warehouse_id: item.target_warehouse_id,
        unit_id: item.unit_id,
      }));
      formApi.setValues({ purpose: data.purpose });
    } else {
      items.value = [createItemRow()];
    }
  },
});

const title = computed(() => (id.value ? '编辑调拨申请' : '新建调拨申请'));

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :show-confirm-button="canWrite" :title="title" class="w-[1080px] max-w-[100vw]">
    <div class="space-y-6">
      <Form />
      <div>
        <div class="mb-3 flex items-center justify-between">
          <span class="font-medium">调拨明细</span>
          <span class="text-muted-foreground text-xs">
            源批次来自库存台账可用余额；目标库位标签含所属仓库
          </span>
        </div>
        <ItemsEditor
          v-model="items"
          :columns="itemColumns"
          :create-row="createItemRow"
        />
      </div>
    </div>
  </Drawer>
</template>
