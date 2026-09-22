<script lang="ts" setup>
import type { RfqApi } from '#/api';

import type { RfqItemRow } from '../data';

import { computed, nextTick, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { message, Select } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import {
  createRfqApi,
  getProductListApi,
  getPurchaseRequestListApi,
  getSupplierListApi,
  getUnitListApi,
  updateRfqApi,
} from '#/api';
import ItemsEditor from '#/components/items-editor/index.vue';

const emit = defineEmits(['success']);

const id = ref<number>();
const items = ref<RfqItemRow[]>([]);
const supplierIds = ref<number[]>([]);
const supplierOptions = ref<Array<{ label: string; value: number }>>([]);

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  showDefaultActions: false,
  wrapperClass: 'grid-cols-2',
  schema: [
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => {
          const res = await getPurchaseRequestListApi({
            page: 1,
            page_size: 100,
            status: 'APPROVED',
          });
          return res.items.map((item) => ({
            label: `${item.request_no} · ${item.purpose}`,
            value: item.id,
          }));
        },
        class: 'w-full',
        help: '可选。关联已批准的采购申请后，明细会带上申请中的物料。',
        placeholder: '不关联则为独立询价',
        showSearch: true,
      },
      fieldName: 'source_request_id',
      label: '来源采购申请',
    },
    {
      component: 'DatePicker',
      componentProps: { class: 'w-full', showTime: true, valueFormat: 'YYYY-MM-DDTHH:mm:ss' },
      fieldName: 'quote_deadline',
      label: '报价截止时间',
    },
    {
      component: 'DatePicker',
      componentProps: { class: 'w-full', valueFormat: 'YYYY-MM-DD' },
      fieldName: 'requested_delivery_date',
      label: '要求到货日期',
    },
    {
      component: 'Textarea',
      componentProps: { maxlength: 500, rows: 2 },
      fieldName: 'delivery_requirements',
      label: '交付要求',
    },
  ],
});

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
      const res = await getProductListApi({
        page: 1,
        page_size: 100,
        status: 'ACTIVE',
      });
      return res.items.map((item) => ({
        label: item.product_name,
        value: item.id,
      }));
    },
    width: 170,
  },
  {
    component: 'input' as const,
    componentProps: { maxlength: 100, placeholder: '规格型号' },
    field: 'specification',
    label: '规格',
    width: 140,
  },
  {
    component: 'number' as const,
    componentProps: { min: 0 },
    field: 'quantity',
    label: '数量',
    required: true,
    width: 110,
  },
  {
    component: 'select' as const,
    componentProps: { placeholder: '单位' },
    field: 'unit_id',
    label: '单位',
    options: async () => {
      const units = await getUnitListApi();
      return units
        .filter((item) => !item.status || item.status === 'ACTIVE')
        .map((item) => ({ label: item.unit_name, value: item.id }));
    },
    required: true,
    width: 100,
  },
  {
    component: 'date' as const,
    field: 'required_delivery_date',
    label: '要求到货',
    width: 150,
  },
  {
    component: 'input' as const,
    componentProps: { maxlength: 200, placeholder: '技术要求' },
    field: 'technical_requirements',
    label: '技术要求',
    width: 180,
  },
];

function createItemRow(): RfqItemRow {
  return {
    product_id: undefined,
    quantity: undefined,
    requested_name: '',
    required_delivery_date: undefined,
    specification: '',
    technical_requirements: '',
    unit_id: undefined,
  };
}

const [Drawer, drawerApi] = useVbenDrawer<null | RfqApi.Rfq>({
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    if (items.value.length === 0) {
      message.warning('请至少添加一条询价明细');
      return;
    }
    if (supplierIds.value.length === 0) {
      message.warning('请至少邀请一家供应商');
      return;
    }
    const values = await formApi.getValues<any>();
    drawerApi.lock();
    try {
      const payload = {
        ...values,
        items: items.value.map((item) => ({
          product_id: item.product_id ?? undefined,
          quantity: Number(item.quantity),
          requested_name: item.requested_name,
          required_delivery_date: item.required_delivery_date ?? undefined,
          specification: item.specification || undefined,
          technical_requirements: item.technical_requirements || undefined,
          unit_id: Number(item.unit_id),
        })),
        supplier_ids: supplierIds.value,
      };
      if (id.value) {
        // 供应商邀请使用联合主键，更新时同样提交完整列表
        await updateRfqApi(id.value, payload as RfqApi.RfqPayload);
      } else {
        await createRfqApi(payload as RfqApi.RfqPayload);
      }
      emit('success');
      drawerApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，这里保持弹窗打开，
      // 让用户修正后重新提交；不吞掉异常会导致未捕获的 Promise 拒绝。
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
    supplierIds.value = [];
    supplierOptions.value = [];

    // 供应商列表按需加载一次，只列合作中的（后端拒绝非 ACTIVE 供应商询价）
    getSupplierListApi({ page: 1, page_size: 100, status: 'ACTIVE' }).then(
      (res) => {
        supplierOptions.value = res.items.map((item) => ({
          label: item.supplier_name,
          value: item.id,
        }));
      },
    );

    await nextTick();
    if (data) {
      items.value = (data.items ?? []).map((item) => ({
        product_id: item.product_id ?? undefined,
        quantity: item.quantity,
        requested_name: item.requested_name,
        required_delivery_date: item.required_delivery_date ?? undefined,
        specification: item.specification ?? '',
        technical_requirements: item.technical_requirements ?? '',
        unit_id: item.unit_id,
      }));
      supplierIds.value = (data.suppliers ?? []).map((item) => item.supplier_id);
      formApi.setValues({
        delivery_requirements: data.delivery_requirements ?? undefined,
        quote_deadline: data.quote_deadline ?? undefined,
        requested_delivery_date: data.requested_delivery_date ?? undefined,
        source_request_id: data.source_request_id ?? undefined,
      });
    } else {
      items.value = [createItemRow()];
    }
  },
});

const title = computed(() => (id.value ? '编辑询价单' : '新建询价单'));

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[1100px]">
    <div class="space-y-6">
      <Form />

      <div>
        <div class="mb-3 font-medium">
          邀请供应商 <span class="text-red-500">*</span>
        </div>
        <Select
          v-model:value="supplierIds"
          :options="supplierOptions"
          class="w-full"
          mode="multiple"
          placeholder="请选择需要询价的供应商"
          show-search
        />
      </div>

      <div>
        <div class="mb-3 font-medium">询价明细</div>
        <ItemsEditor
          v-model="items"
          :columns="itemColumns"
          :create-row="createItemRow"
        />
      </div>
    </div>
  </Drawer>
</template>
