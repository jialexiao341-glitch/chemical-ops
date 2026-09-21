<script lang="ts" setup>
import type { PurchaseRequestApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import {
  createPurchaseRequestApi,
  getDepartmentListApi,
  getProductListApi,
  getUnitListApi,
  updatePurchaseRequestApi,
} from '#/api';
import ItemsEditor from '#/components/items-editor/index.vue';
import { PRIORITY_DICT } from '#/constants/dictionary';

import type { RequestItemRow } from '../data';

const emit = defineEmits(['success']);

const id = ref<number>();
const items = ref<RequestItemRow[]>([]);
const submitting = ref(false);

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  showDefaultActions: false,
  wrapperClass: 'grid-cols-2',
  schema: [
    {
      component: 'Textarea',
      componentProps: {
        maxlength: 500,
        placeholder: '请说明采购用途',
        rows: 2,
      },
      fieldName: 'purpose',
      label: '采购用途',
      rules: 'required',
    },
    {
      component: 'Select',
      componentProps: {
        options: PRIORITY_DICT.options(),
        placeholder: '请选择优先级',
      },
      defaultValue: 'NORMAL',
      fieldName: 'priority',
      label: '优先级',
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
        placeholder: '请选择申请部门',
        showSearch: true,
      },
      fieldName: 'department_id',
      label: '申请部门',
    },
    {
      component: 'DatePicker',
      componentProps: { class: 'w-full', valueFormat: 'YYYY-MM-DD' },
      fieldName: 'expected_date',
      label: '期望到货日期',
    },
    {
      component: 'InputNumber',
      componentProps: { class: 'w-full', min: 0, precision: 2 },
      fieldName: 'budget_amount',
      label: '预算金额',
    },
    {
      component: 'Input',
      componentProps: { maxlength: 3 },
      defaultValue: 'CNY',
      fieldName: 'currency_code',
      label: '币种',
    },
  ],
});

/** 明细列定义，产品与单位下拉按需异步加载 */
const itemColumns = [
  {
    component: 'input' as const,
    componentProps: { maxlength: 100, placeholder: '物料名称' },
    field: 'requested_name',
    label: '物料名称',
    required: true,
    width: 180,
  },
  {
    component: 'select' as const,
    componentProps: { placeholder: '可关联已有产品' },
    field: 'product_id',
    label: '关联产品',
    options: async () => {
      const res = await getProductListApi({ page: 1, page_size: 100 });
      return res.items.map((item) => ({
        label: item.product_name,
        value: item.id,
      }));
    },
    width: 180,
  },
  {
    component: 'number' as const,
    componentProps: { min: 0, placeholder: '数量' },
    field: 'quantity',
    label: '数量',
    required: true,
    width: 120,
  },
  {
    component: 'select' as const,
    componentProps: { placeholder: '单位' },
    field: 'unit_id',
    label: '单位',
    options: async () => {
      const units = await getUnitListApi();
      return units.map((item) => ({
        label: item.unit_name,
        value: item.id,
      }));
    },
    required: true,
    width: 110,
  },
  {
    component: 'number' as const,
    componentProps: { min: 0, placeholder: '预算单价' },
    field: 'budget_price',
    label: '预算单价',
    width: 120,
  },
  {
    component: 'date' as const,
    field: 'expected_date',
    label: '期望到货',
    width: 150,
  },
  {
    component: 'input' as const,
    componentProps: { maxlength: 200, placeholder: '技术要求' },
    field: 'technical_requirements',
    label: '技术要求',
    width: 200,
  },
];

function createItemRow(): RequestItemRow {
  return {
    budget_price: undefined,
    expected_date: undefined,
    product_id: undefined,
    quantity: undefined,
    requested_name: '',
    technical_requirements: '',
    unit_id: undefined,
  };
}

function validateItems() {
  if (items.value.length === 0) {
    return '请至少添加一条采购明细';
  }
  for (const [index, item] of items.value.entries()) {
    if (!item.requested_name?.trim()) {
      return `第 ${index + 1} 行缺少物料名称`;
    }
    if (!item.quantity || Number(item.quantity) <= 0) {
      return `第 ${index + 1} 行的数量必须大于 0`;
    }
    if (!item.unit_id) {
      return `第 ${index + 1} 行缺少计量单位`;
    }
  }
  return null;
}

const [Drawer, drawerApi] = useVbenDrawer<null | PurchaseRequestApi.PurchaseRequest>({
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    const itemError = validateItems();
    if (itemError) {
      // 明细校验不通过时不提交，保持抽屉打开
      message.warning(itemError);
      return;
    }
    const values = await formApi.getValues<any>();
    submitting.value = true;
    drawerApi.lock();
    try {
      const payload = {
        ...values,
        items: items.value.map((item) => ({
          budget_price: item.budget_price ?? undefined,
          expected_date: item.expected_date ?? undefined,
          product_id: item.product_id ?? undefined,
          quantity: Number(item.quantity),
          requested_name: item.requested_name,
          technical_requirements: item.technical_requirements || undefined,
          unit_id: Number(item.unit_id),
        })),
      };
      if (id.value) {
        await updatePurchaseRequestApi(id.value, payload);
      } else {
        await createPurchaseRequestApi(
          payload as PurchaseRequestApi.RequestPayload,
        );
      }
      emit('success');
      drawerApi.close();
    } finally {
      submitting.value = false;
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

    await nextTick();
    if (data) {
      // 列表接口已经带了明细，直接回填，避免额外请求
      items.value = (data.items ?? []).map((item) => ({
        budget_price: item.budget_price ?? undefined,
        expected_date: item.expected_date ?? undefined,
        product_id: item.product_id ?? undefined,
        quantity: item.quantity,
        requested_name: item.requested_name,
        technical_requirements: item.technical_requirements ?? '',
        unit_id: item.unit_id,
      }));
      formApi.setValues({
        budget_amount: data.budget_amount ?? undefined,
        currency_code: data.currency_code ?? 'CNY',
        department_id: data.department_id ?? undefined,
        expected_date: data.expected_date ?? undefined,
        priority: data.priority,
        purpose: data.purpose,
      });
    } else {
      items.value = [createItemRow()];
    }
  },
});

const title = computed(() =>
  id.value ? '编辑采购申请' : '新建采购申请',
);

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[1080px]">
    <div class="space-y-6">
      <Form />
      <div>
        <div class="mb-3 flex items-center justify-between">
          <span class="font-medium">采购明细</span>
          <span class="text-muted-foreground text-xs">
            数量与单位会作为后续询价、订单的基础
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
