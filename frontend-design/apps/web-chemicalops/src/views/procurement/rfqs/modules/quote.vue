<script lang="ts" setup>
import type { QuoteItemRow } from '../data';

import { computed, ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import {
  Alert,
  DatePicker,
  Empty,
  Input,
  InputNumber,
  message,
  Select,
  Spin,
  Table,
} from 'antdv-next';

import { createQuoteApi, getRfqApi } from '#/api';
import { formatQuantity } from '#/utils/format';
import { getSupplierNameMap, getUnitNameMap } from '#/utils/lookup';

const emit = defineEmits(['success']);

/**
 * 录入供应商报价。
 *
 * 报价必须覆盖询价单的全部明细，因此明细行由询价单带入、不可增删。
 */
const rfqId = ref<number>();
const rfqNo = ref('');
const supplierId = ref<number>();
const supplierOptions = ref<Array<{ label: string; value: number }>>([]);
const quoteDate = ref<string>();
const validUntil = ref<string>();
const note = ref('');
const rows = ref<QuoteItemRow[]>([]);
const loading = ref(false);

const [Modal, modalApi] = useVbenModal<null | { id: number; rfqNo: string }>({
  async onConfirm() {
    if (!supplierId.value) {
      message.warning('请选择报价供应商');
      return;
    }
    const missing = rows.value.some(
      (row) => !row.unit_price || Number(row.unit_price) <= 0,
    );
    if (missing) {
      message.warning('请为每条明细填写大于 0 的单价');
      return;
    }
    if (!rfqId.value) {
      return;
    }
    modalApi.lock();
    try {
      await createQuoteApi(rfqId.value, {
        currency_code: 'CNY',
        items: rows.value.map((row) => ({
          lead_days: row.lead_days ?? undefined,
          moq_quantity: row.moq_quantity ?? undefined,
          note: row.note || undefined,
          payment_terms: row.payment_terms || undefined,
          quoted_quantity: Number(row.quoted_quantity),
          rfq_item_id: Number(row.rfq_item_id),
          supplier_model: row.supplier_model || undefined,
          tax_rate: row.tax_rate ?? undefined,
          unit_id: Number(row.unit_id),
          unit_price: Number(row.unit_price),
        })),
        note: note.value || undefined,
        quote_date: quoteDate.value,
        supplier_id: supplierId.value,
        valid_until: validUntil.value,
      });
      message.success('报价已录入');
      emit('success');
      modalApi.close();
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    const data = modalApi.getData();
    rfqId.value = data?.id;
    rfqNo.value = data?.rfqNo ?? '';
    supplierId.value = undefined;
    quoteDate.value = undefined;
    validUntil.value = undefined;
    note.value = '';
    rows.value = [];
    if (!rfqId.value) {
      return;
    }
    loading.value = true;
    try {
      const [rfq, unitMap, supplierMap] = await Promise.all([
        getRfqApi(rfqId.value),
        getUnitNameMap(),
        getSupplierNameMap(),
      ]);
      // 只允许在受邀名单里选择供应商
      supplierOptions.value = (rfq.suppliers ?? []).map((item) => ({
        label: supplierMap.get(item.supplier_id) ?? `供应商 #${item.supplier_id}`,
        value: item.supplier_id,
      }));
      rows.value = (rfq.items ?? []).map((item) => ({
        lead_days: undefined,
        moq_quantity: undefined,
        note: '',
        payment_terms: '',
        quoted_quantity: Number(item.quantity),
        requestedName: item.requested_name,
        requestedQuantity: formatQuantity(item.quantity),
        rfq_item_id: item.id,
        supplier_model: '',
        tax_rate: undefined,
        unit_id: item.unit_id,
        unitName: unitMap.get(item.unit_id) ?? `#${item.unit_id}`,
        unit_price: undefined,
      }));
    } finally {
      loading.value = false;
    }
  },
});

const totalAmount = computed(() =>
  rows.value.reduce(
    (sum, row) =>
      sum + Number(row.unit_price || 0) * Number(row.quoted_quantity || 0),
    0,
  ),
);

const columns = [
  { key: 'requestedName', title: '物料', minWidth: 160 },
  { key: 'requestedQuantity', title: '询价数量', width: 110 },
  { key: 'unitName', title: '单位', width: 80 },
  { key: 'supplier_model', title: '供应商型号', width: 150 },
  { key: 'quoted_quantity', title: '报价数量', width: 140 },
  { key: 'unit_price', title: '单价', width: 140 },
  { key: 'tax_rate', title: '税率(%)', width: 110 },
  { key: 'lead_days', title: '交期(天)', width: 110 },
  { key: 'moq_quantity', title: '最小起订量', width: 130 },
  { key: 'payment_terms', title: '付款条件', width: 150 },
];

const title = computed(() => `录入报价 · ${rfqNo.value}`);
</script>

<template>
  <Modal :title="title" class="w-[1200px]">
    <Spin :spinning="loading">
      <div class="space-y-4 px-1">
        <Alert
          message="报价必须覆盖询价单的全部明细，否则后端会拒绝录入。"
          type="info"
          show-icon
        />
        <div class="grid grid-cols-3 gap-3">
          <div>
            <div class="mb-2 text-sm">
              报价供应商 <span class="text-red-500">*</span>
            </div>
            <Select
              v-model:value="supplierId"
              :options="supplierOptions"
              class="w-full"
              placeholder="请选择受邀供应商"
              show-search
            />
          </div>
          <div>
            <div class="mb-2 text-sm">报价日期</div>
            <DatePicker
              v-model:value="quoteDate"
              class="w-full"
              value-format="YYYY-MM-DD"
            />
          </div>
          <div>
            <div class="mb-2 text-sm">有效期至</div>
            <DatePicker
              v-model:value="validUntil"
              class="w-full"
              value-format="YYYY-MM-DD"
            />
          </div>
        </div>
        <div>
          <div class="mb-2 text-sm">备注</div>
          <Input v-model:value="note" :maxlength="500" />
        </div>

        <Empty v-if="rows.length === 0 && !loading" description="该询价单没有明细" />
        <Table
          v-else
          :columns="columns"
          :data-source="rows"
          :pagination="false"
          :scroll="{ x: 1300 }"
          row-key="rfq_item_id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'quoted_quantity'">
              <InputNumber
                v-model:value="record.quoted_quantity"
                :min="0"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'unit_price'">
              <InputNumber
                v-model:value="record.unit_price"
                :min="0"
                :precision="6"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'tax_rate'">
              <InputNumber
                v-model:value="record.tax_rate"
                :max="100"
                :min="0"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'lead_days'">
              <InputNumber
                v-model:value="record.lead_days"
                :min="0"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'moq_quantity'">
              <InputNumber
                v-model:value="record.moq_quantity"
                :min="0"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'supplier_model'">
              <Input v-model:value="record.supplier_model" :maxlength="100" />
            </template>
            <template v-else-if="column.key === 'payment_terms'">
              <Input v-model:value="record.payment_terms" :maxlength="100" />
            </template>
          </template>
        </Table>

        <div v-if="rows.length > 0" class="text-right text-sm">
          报价合计（未含税）：
          <span class="text-base font-semibold">
            {{ formatQuantity(totalAmount) }}
          </span>
        </div>
      </div>
    </Spin>
  </Modal>
</template>
