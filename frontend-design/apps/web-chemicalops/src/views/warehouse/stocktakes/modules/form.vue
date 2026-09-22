<script lang="ts" setup>
import type { StocktakeApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { message, Select } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import {
  createStocktakeApi,
  getBalanceListApi,
  getLocationListApi,
  getProductListApi,
  getUnitListApi,
  getWarehouseListApi,
  updateStocktakeApi,
} from '#/api';
import ItemsEditor from '#/components/items-editor/index.vue';
import { formatQuantity } from '#/utils/format';

const emit = defineEmits(['success']);

/**
 * 盘点明细编辑行。
 * 批次来自所选仓库的库存余额；实盘数量在创建时录入，
 * 账面数量由后端在创建时快照，执行时按差额调整库存。
 */
interface StocktakeItemRow {
  balance_id?: number;
  batch_id?: number;
  counted_quantity?: number | string;
  location_id?: number;
  note?: string;
  product_id?: number;
  unit_id?: number;
}

const id = ref<number>();
const items = ref<StocktakeItemRow[]>([]);
// 仓库/库位放在表单外独立选择（与询价单的供应商选择同模式），
// 因为批次选项依赖仓库，需要在确认前联动重载。
const warehouseId = ref<number>();
const locationId = ref<number>();
const warehouseOptions = ref<Array<{ label: string; value: number }>>([]);
const locationOptions = ref<Array<{ label: string; value: number }>>([]);
const balanceOptions = ref<Array<{ label: string; value: number }>>([]);
const balanceMap = ref(
  new Map<
    number,
    {
      batch_id: number;
      location_id: number;
      product_id: number;
      unit_id: number;
      warehouse_id: number;
    }
  >(),
);

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  showDefaultActions: false,
  schema: [
    {
      component: 'Textarea',
      componentProps: {
        maxlength: 500,
        placeholder: '请说明盘点用途',
        rows: 2,
      },
      fieldName: 'purpose',
      label: '盘点用途',
      rules: 'required',
    },
  ],
});

const itemColumns = [
  {
    component: 'select' as const,
    componentProps: { placeholder: '选择库存批次' },
    field: 'balance_id',
    label: '库存批次',
    options: () => Promise.resolve(balanceOptions.value),
    required: true,
    width: 340,
  },
  {
    component: 'number' as const,
    componentProps: { min: 0, placeholder: '实盘数量' },
    field: 'counted_quantity',
    label: '实盘数量',
    required: true,
    width: 130,
  },
  {
    component: 'input' as const,
    componentProps: { maxlength: 200, placeholder: '备注' },
    field: 'note',
    label: '备注',
    width: 180,
  },
];

function createItemRow(): StocktakeItemRow {
  return {
    balance_id: undefined,
    counted_quantity: undefined,
    note: '',
  };
}

/** 仓库变化时重载库位与批次选项，并清空已选明细 */
async function reloadOptions(warehouse?: null | number) {
  locationId.value = undefined;
  locationOptions.value = [];
  balanceOptions.value = [];
  balanceMap.value.clear();
  items.value = warehouse ? [createItemRow()] : [];
  if (!warehouse) {
    return;
  }
  const [locations, balances, products, units] = await Promise.all([
    getLocationListApi(warehouse),
    getBalanceListApi({ page: 1, page_size: 100, warehouse_id: warehouse }),
    getProductListApi({ page: 1, page_size: 100, status: 'ACTIVE' }),
    getUnitListApi(),
  ]);
  locationOptions.value = locations.map((item) => ({
    label: item.location_name,
    value: item.id,
  }));
  const productMap = new Map(
    products.items.map((item) => [item.id, item.product_name]),
  );
  const unitMap = new Map(units.map((item) => [item.id, item.unit_name]));
  const locationMap = new Map(
    locations.map((item) => [item.id, item.location_name]),
  );
  for (const balance of balances.items) {
    if (balance.status !== 'AVAILABLE') {
      continue;
    }
    const productName =
      productMap.get(balance.product_id) ?? `#${balance.product_id}`;
    balanceOptions.value.push({
      label: `${productName} / ${locationMap.get(balance.location_id) ?? `#${balance.location_id}`} 批次${balance.batch_id} 账面${formatQuantity(balance.quantity)} ${unitMap.get(balance.unit_id) ?? ''}`.trim(),
      value: balance.id,
    });
    balanceMap.value.set(balance.id, {
      batch_id: Number(balance.batch_id),
      location_id: balance.location_id,
      product_id: balance.product_id,
      unit_id: balance.unit_id,
      warehouse_id: balance.warehouse_id,
    });
  }
}

async function onWarehouseChange(value?: null | number) {
  await reloadOptions(value ?? undefined);
}

const [Drawer, drawerApi] = useVbenDrawer<null | StocktakeApi.StocktakeRequest>(
  {
    async onConfirm() {
      const { valid } = await formApi.validate();
      if (!valid) {
        return;
      }
      if (!warehouseId.value) {
        message.warning('请选择盘点仓库');
        return;
      }
      if (items.value.length === 0) {
        message.warning('请至少添加一条盘点明细');
        return;
      }
      for (const [index, item] of items.value.entries()) {
        if (!item.balance_id) {
          message.warning(`第 ${index + 1} 行请选择库存批次`);
          return;
        }
        if (
          item.counted_quantity === undefined ||
          item.counted_quantity === null ||
          item.counted_quantity === ''
        ) {
          message.warning(`第 ${index + 1} 行请填写实盘数量`);
          return;
        }
        const balance = balanceMap.value.get(item.balance_id);
        if (balance && balance.warehouse_id !== warehouseId.value) {
          message.warning(`第 ${index + 1} 行的批次不属于所选仓库`);
          return;
        }
      }
      const values = await formApi.getValues<any>();
      const payload: StocktakeApi.Payload = {
        items: items.value.map((item) => {
          const balance = balanceMap.value.get(item.balance_id!)!;
          return {
            batch_id: balance.batch_id,
            counted_quantity: Number(item.counted_quantity),
            location_id: balance.location_id,
            note: item.note || undefined,
            product_id: balance.product_id,
            unit_id: balance.unit_id,
          };
        }),
        location_id: locationId.value ?? undefined,
        purpose: values.purpose,
        warehouse_id: warehouseId.value,
      };
      drawerApi.lock();
      try {
        if (id.value) {
          await updateStocktakeApi(id.value, payload);
        } else {
          await createStocktakeApi(payload);
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
      warehouseId.value = undefined;
      locationId.value = undefined;
      locationOptions.value = [];
      balanceOptions.value = [];
      items.value = [];

      if (warehouseOptions.value.length === 0) {
        const list = await getWarehouseListApi();
        warehouseOptions.value = list.map((item) => ({
          label: item.warehouse_name,
          value: item.id,
        }));
      }

      await nextTick();
      if (data) {
        formApi.setValues({ purpose: data.purpose });
        warehouseId.value = data.warehouse_id;
        locationId.value = data.location_id ?? undefined;
        await reloadOptions(data.warehouse_id);
        locationId.value = data.location_id ?? undefined;
        // 编辑回填：按仓库-库位-批次匹配现有余额选项
        items.value = (data.items ?? []).map((item) => ({
          balance_id: balanceOptions.value.find((option) => {
            const balance = balanceMap.value.get(option.value);
            return (
              balance?.batch_id === item.batch_id &&
              balance?.location_id === item.location_id
            );
          })?.value,
          batch_id: item.batch_id,
          counted_quantity: item.counted_quantity,
          location_id: item.location_id,
          note: item.note ?? '',
          product_id: item.product_id,
          unit_id: item.unit_id,
        }));
      } else {
        items.value = [];
      }
    },
  },
);

const title = computed(() => (id.value ? '编辑盘点申请' : '新建盘点申请'));

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[980px]">
    <div class="space-y-6">
      <Form />

      <!-- 盘点范围：仓库必选，库位可选（表单外独立控件） -->
      <div class="grid grid-cols-2 gap-3">
        <div>
          <div class="mb-2 text-sm">
            盘点仓库 <span class="text-red-500">*</span>
          </div>
          <Select
            v-model:value="warehouseId"
            :disabled="Boolean(id)"
            :options="warehouseOptions"
            class="w-full"
            placeholder="请选择盘点仓库"
            show-search
            @change="onWarehouseChange"
          />
        </div>
        <div>
          <div class="mb-2 text-sm">盘点库位</div>
          <Select
            v-model:value="locationId"
            :disabled="Boolean(id)"
            :options="locationOptions"
            allow-clear
            class="w-full"
            placeholder="留空表示整仓盘点"
          />
        </div>
      </div>

      <div v-if="!id">
        <div class="mb-3 flex items-center justify-between">
          <span class="font-medium">盘点明细</span>
          <span class="text-muted-foreground text-xs">
            选择仓库后列出可用批次；实盘数量即现场清点结果
          </span>
        </div>
        <div
          v-if="!warehouseId"
          class="text-muted-foreground rounded-md border border-dashed p-4 text-center text-sm"
        >
          请先选择盘点仓库
        </div>
        <template v-else>
          <ItemsEditor
            v-model="items"
            :columns="itemColumns"
            :create-row="createItemRow"
            :min-rows="0"
          />
          <div
            v-if="balanceOptions.length === 0"
            class="text-muted-foreground mt-2 text-xs"
          >
            该仓库暂无可用库存批次
          </div>
        </template>
      </div>
      <div v-else class="text-muted-foreground text-sm">
        编辑模式下批次不可更换，实盘数量与备注可调整。
      </div>
    </div>
  </Drawer>
</template>
