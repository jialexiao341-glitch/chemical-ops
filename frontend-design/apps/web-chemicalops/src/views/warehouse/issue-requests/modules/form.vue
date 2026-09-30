<script lang="ts" setup>
import type { IssueRequestApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import {
  createIssueApi,
  getBalanceListApi,
  getDepartmentListApi,
  getLocationListApi,
  getProductListApi,
  getUnitListApi,
  getWarehouseListApi,
  updateIssueApi,
} from '#/api';
import ItemsEditor from '#/components/items-editor/index.vue';
import { formatQuantity } from '#/utils/format';

const emit = defineEmits(['success']);

/** 领用明细的编辑行；批次选项直接来自库存余额（含库位与可用量） */
interface IssueItemRow {
  available?: string;
  batch_id?: number;
  balance_id?: number;
  location_id?: number;
  note?: string;
  product_id?: number;
  requested_quantity?: number | string;
  unit_id?: number;
  warehouse_id?: number;
}

const id = ref<number>();
const items = ref<IssueItemRow[]>([]);
/** 库存余额批次选项（label 含产品/仓库/库位/可用量） */
const balanceOptions = ref<Array<{ label: string; value: number }>>([]);
/** balance.id → 该余额的完整外键与可用量，提交时按选中的 balance 展开 */
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
/** 编辑回填用：仓库-库位-批次-产品 → balance.id（余额选项的 value 是 balance.id 而非 batch_id） */
const balanceIndex = ref(new Map<string, number>());

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  showDefaultActions: false,
  wrapperClass: 'grid-cols-1 sm:grid-cols-2',
  schema: [
    {
      component: 'Textarea',
      componentProps: {
        maxlength: 500,
        placeholder: '请说明领用用途',
        rows: 2,
      },
      fieldName: 'purpose',
      label: '领用用途',
      rules: 'required',
    },
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => {
          const res = await getDepartmentListApi({ page: 1, page_size: 100 });
          return res.items.map((item) => ({
            label: item.department_name,
            value: item.id,
          }));
        },
        class: 'w-full',
        placeholder: '默认申请人所在部门',
        showSearch: true,
      },
      fieldName: 'department_id',
      label: '领用部门',
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
    width: 320,
  },
  {
    component: 'number' as const,
    componentProps: { min: 0, placeholder: '领用数量' },
    field: 'requested_quantity',
    label: '领用数量',
    required: true,
    width: 130,
  },
  {
    component: 'input' as const,
    componentProps: { maxlength: 200, placeholder: '备注' },
    field: 'note',
    label: '备注',
    width: 200,
  },
];

function createItemRow(): IssueItemRow {
  return {
    balance_id: undefined,
    note: '',
    requested_quantity: undefined,
  };
}

/** 按选中的余额补全外键字段（提交 payload 需要它们） */
function expandRows() {
  for (const row of items.value) {
    const balance = row.balance_id
      ? balanceMap.value.get(row.balance_id)
      : undefined;
    if (balance) {
      row.batch_id = balance.batch_id;
      row.location_id = balance.location_id;
      row.product_id = balance.product_id;
      row.unit_id = balance.unit_id;
      row.warehouse_id = balance.warehouse_id;
      row.available = balance.available;
    }
  }
}

const [Drawer, drawerApi] = useVbenDrawer<null | IssueRequestApi.IssueRequest>({
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    if (items.value.length === 0) {
      message.warning('请至少添加一条领用明细');
      return;
    }
    expandRows();
    for (const [index, item] of items.value.entries()) {
      if (!item.balance_id) {
        message.warning(`第 ${index + 1} 行请选择库存批次`);
        return;
      }
      if (!item.requested_quantity || Number(item.requested_quantity) <= 0) {
        message.warning(`第 ${index + 1} 行的领用数量必须大于 0`);
        return;
      }
      const available = Number(item.available ?? 0);
      if (Number(item.requested_quantity) > available) {
        message.warning(
          `第 ${index + 1} 行领用数量超过可用量 ${formatQuantity(available)}`,
        );
        return;
      }
    }
    const values = await formApi.getValues<any>();
    const payload: IssueRequestApi.Payload = {
      department_id: values.department_id ?? undefined,
      items: items.value.map((item) => ({
        batch_id: Number(item.batch_id),
        location_id: Number(item.location_id),
        note: item.note || undefined,
        product_id: Number(item.product_id),
        requested_quantity: Number(item.requested_quantity),
        unit_id: Number(item.unit_id),
        warehouse_id: Number(item.warehouse_id),
      })),
      purpose: values.purpose,
    };
    drawerApi.lock();
    try {
      if (id.value) {
        await updateIssueApi(id.value, payload);
      } else {
        await createIssueApi(payload);
      }
      emit('success');
      drawerApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，保持抽屉打开。
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

    // 批次选项：拉库存余额 + 主数据名称拼 label
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
      // 库位名按仓库逐个拉取（仓库数量很少）
      const locationMaps = await Promise.all(
        warehouses.map(async (warehouse) => {
          const locations = await getLocationListApi(warehouse.id);
          return new Map(
            locations.map((location) => [location.id, location.location_name]),
          );
        }),
      );
      const locationName = (locationId: number, warehouseId: number) => {
        const index = warehouses.findIndex((w) => w.id === warehouseId);
        return locationMaps[index]?.get(locationId) ?? `#${locationId}`;
      };

      balanceOptions.value = [];
      balanceMap.value.clear();
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
        const label = `${productName} @ ${warehouseName}/${locationName(
          balance.location_id,
          balance.warehouse_id,
        )} 批次${balance.batch_id} 可用${formatQuantity(available)} ${
          unitMap.get(balance.unit_id) ?? ''
        }`.trim();
        balanceOptions.value.push({ label, value: balance.id });
        balanceMap.value.set(balance.id, {
          available: String(available),
          batch_id: Number(balance.batch_id),
          location_id: balance.location_id,
          product_id: balance.product_id,
          unit_id: balance.unit_id,
          warehouse_id: balance.warehouse_id,
        });
        balanceIndex.value.set(
          `${balance.warehouse_id}-${balance.location_id}-${balance.batch_id}-${balance.product_id}`,
          balance.id,
        );
      }
    }

    await nextTick();
    if (data) {
      items.value = (data.items ?? []).map((item) => ({
        balance_id:
          balanceIndex.value.get(
            `${item.warehouse_id}-${item.location_id}-${item.batch_id}-${item.product_id}`,
          ) ?? undefined,
        batch_id: item.batch_id,
        location_id: item.location_id,
        note: item.note ?? '',
        product_id: item.product_id,
        requested_quantity: item.requested_quantity,
        unit_id: item.unit_id,
        warehouse_id: item.warehouse_id,
      }));
      formApi.setValues({
        department_id: data.department_id ?? undefined,
        purpose: data.purpose,
      });
    } else {
      items.value = [createItemRow()];
    }
  },
});

const title = computed(() => (id.value ? '编辑领用申请' : '新建领用申请'));

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[980px] max-w-[100vw]">
    <div class="space-y-6">
      <Form />
      <div>
        <div class="mb-3 flex items-center justify-between">
          <span class="font-medium">领用明细</span>
          <span class="text-muted-foreground text-xs">
            批次来自库存台账的可用余额
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
