<script lang="ts" setup>
import type { QuoteItemRow } from '../data';

import { computed, onBeforeUnmount, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';

import {
  Alert,
  Button,
  DatePicker,
  Empty,
  Input,
  InputNumber,
  message,
  Modal as AntModal,
  Select,
  Spin,
  Table,
} from 'antdv-next';

import { createQuoteApi, getRfqApi, getUnitListApi, parseQuoteFileApi } from '#/api';
import { formatQuantity } from '#/utils/format';
import { getSupplierNameMap } from '#/utils/lookup';

import { replaceQuoteCandidate } from './quote-candidate';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['procurement.rfqs.quote']));
const emit = defineEmits(['success']);

/**
 * 录入供应商报价。
 *
 * 明细行由询价单带入、不可增删；比价时服务端还会复核所有已提交报价的覆盖情况。
 */
const rfqId = ref<number>();
const rfqNo = ref('');
const supplierId = ref<number>();
const supplierOptions = ref<Array<{ label: string; value: number }>>([]);
const quoteDate = ref<string>();
const validUntil = ref<string>();
const note = ref('');
const currencyCode = ref('');
const sourceFileId = ref<number>();
const parseCandidate = ref<Awaited<ReturnType<typeof parseQuoteFileApi>>>();
const parseLoading = ref(false);
const fileInput = ref<HTMLInputElement>();
const rows = ref<QuoteItemRow[]>([]);
const unitOptions = ref<Array<{ label: string; value: number }>>([]);
const loading = ref(false);
const submitting = ref(false);
const busy = computed(() => loading.value || parseLoading.value || submitting.value);
let contextVersion = 0;
let initialRows: QuoteItemRow[] = [];
let importConfirmation: ReturnType<typeof AntModal.confirm> | undefined;

onBeforeUnmount(() => {
  contextVersion += 1;
  importConfirmation?.destroy();
});

const [Modal, modalApi] = useVbenModal<null | { id: number; rfqNo: string }>({
  async onConfirm() {
    if (!canConfirm.value || busy.value) return;
    if (!supplierId.value) {
      message.warning('请选择报价供应商');
      return;
    }
    if (!/^[A-Z]{3}$/.test(currencyCode.value.trim().toUpperCase())) {
      message.warning('请填写三位大写币种代码，例如 CNY 或 USD');
      return;
    }
    const missing = rows.value.some(
      (row) => !row.unit_price || Number(row.unit_price) <= 0 || row.tax_basis == null || row.tax_rate == null,
    );
    if (missing) {
      message.warning('请为每条明细填写单价、税率并选择含税口径');
      return;
    }
    if (rows.value.length === 0 || rows.value.some((row) =>
      !Number.isFinite(Number(row.quoted_quantity)) || Number(row.quoted_quantity) <= 0 || !row.unit_id,
    )) {
      message.warning('请为每条明细填写有效的报价数量并选择报价单位');
      return;
    }
    if (!rfqId.value) {
      return;
    }
    const version = contextVersion;
    submitting.value = true;
    modalApi.lock();
    try {
      await createQuoteApi(rfqId.value, {
        currency_code: currencyCode.value.trim().toUpperCase(),
        items: rows.value.map((row) => ({
          lead_days: row.lead_days ?? undefined,
          freight_amount: row.freight_amount ?? undefined,
          freight_tax_rate: row.freight_tax_rate ?? undefined,
          freight_tax_included: row.freight_tax_basis == null ? undefined : row.freight_tax_basis === 'INCLUDED',
          moq_quantity: row.moq_quantity ?? undefined,
          moq_unit_id: row.moq_unit_id ?? undefined,
          note: row.note || undefined,
          payment_terms: row.payment_terms || undefined,
          quoted_quantity: Number(row.quoted_quantity),
          rfq_item_id: Number(row.rfq_item_id),
          supplier_model: row.supplier_model || undefined,
          tax_rate: row.tax_rate ?? undefined,
          tax_included: row.tax_basis === 'INCLUDED',
          unit_id: Number(row.unit_id),
          unit_price: Number(row.unit_price),
        })),
        note: note.value || undefined,
        quote_date: quoteDate.value,
        source_file_id: sourceFileId.value,
        supplier_id: supplierId.value,
        valid_until: validUntil.value,
      });
      if (version !== contextVersion) return;
      message.success('报价已录入');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，这里保持弹窗打开，
      // 让用户修正后重新提交；不吞掉异常会导致未捕获的 Promise 拒绝。
    } finally {
      if (version === contextVersion) {
        submitting.value = false;
        modalApi.unlock();
      }
    }
  },
  async onOpenChange(isOpen) {
    const version = ++contextVersion;
    importConfirmation?.destroy();
    importConfirmation = undefined;
    parseLoading.value = false;
    loading.value = false;
    submitting.value = false;
    modalApi.unlock();
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
    currencyCode.value = '';
    sourceFileId.value = undefined;
    parseCandidate.value = undefined;
    rows.value = [];
    initialRows = [];
    supplierOptions.value = [];
    unitOptions.value = [];
    if (!rfqId.value) {
      return;
    }
    loading.value = true;
    try {
      const [rfq, units, supplierMap] = await Promise.all([
        getRfqApi(rfqId.value),
        getUnitListApi({ silent: true }),
        getSupplierNameMap(),
      ]);
      if (version !== contextVersion) return;
      const unitMap = new Map(units.map((item) => [item.id, item.unit_name]));
      unitOptions.value = units
        .filter((item) => item.status === 'ACTIVE')
        .map((item) => ({ label: item.unit_name, value: item.id }));
      // 只允许在受邀名单里选择供应商
      supplierOptions.value = (rfq.suppliers ?? []).map((item) => ({
        label: supplierMap.get(item.supplier_id) ?? `供应商 #${item.supplier_id}`,
        value: item.supplier_id,
      }));
      rows.value = (rfq.items ?? []).map((item) => ({
        lead_days: undefined,
        freight_amount: undefined,
        freight_tax_rate: undefined,
        freight_tax_basis: null,
        moq_quantity: undefined,
        moq_unit_id: item.unit_id,
        note: '',
        payment_terms: '',
        quoted_quantity: Number(item.quantity),
        requestedName: item.requested_name,
        requestedQuantity: formatQuantity(item.quantity),
        rfq_item_id: item.id,
        supplier_model: '',
        tax_rate: undefined,
        tax_basis: null,
        unit_id: item.unit_id,
        unitName: unitMap.get(item.unit_id) ?? `#${item.unit_id}`,
        unit_price: undefined,
      }));
      initialRows = rows.value.map((row) => ({ ...row }));
    } catch {
      // 请求层显示加载错误；旧上下文不会写入新弹窗。
    } finally {
      if (version === contextVersion) loading.value = false;
    }
  },
});

async function parseQuoteFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file || !rfqId.value || busy.value || !canConfirm.value) return;
  const version = contextVersion;
  const id = rfqId.value;
  // Also block edits while the replacement confirmation is open.
  parseLoading.value = true;
  const hasInput = sourceFileId.value != null || supplierId.value != null
    || quoteDate.value || validUntil.value || note.value || currencyCode.value
    || JSON.stringify(rows.value) !== JSON.stringify(initialRows);
  if (hasInput) {
    importConfirmation = AntModal.confirm({
      title: '替换当前报价内容？',
      content: '成功解析后将替换当前全部报价字段，文件未提供的字段会清空，供应商需要重新选择。解析失败时保留当前内容。',
      okText: '确认替换',
      cancelText: '取消',
      keyboard: false,
      maskClosable: false,
      onOk: async () => {
        if (version !== contextVersion) return;
        importConfirmation?.update({ cancelButtonProps: { disabled: true } });
        await importQuoteFile(id, file, version);
        if (version === contextVersion) importConfirmation = undefined;
      },
      onCancel: () => {
        if (version !== contextVersion) return;
        parseLoading.value = false;
        importConfirmation = undefined;
      },
    });
    return;
  }
  await importQuoteFile(id, file, version);
}

async function importQuoteFile(id: number, file: File, version: number) {
  try {
    const candidate = await parseQuoteFileApi(id, file);
    if (version !== contextVersion) return;
    const replacement = replaceQuoteCandidate(initialRows, candidate, unitOptions.value);
    rows.value = replacement.rows;
    sourceFileId.value = replacement.sourceFileId;
    supplierId.value = replacement.supplierId;
    currencyCode.value = replacement.currencyCode;
    quoteDate.value = replacement.quoteDate;
    validUntil.value = replacement.validUntil;
    note.value = replacement.note;
    parseCandidate.value = { ...candidate, warnings: replacement.warnings };
    message.success('解析完成，请重新选择供应商并核对候选字段与原文依据');
  } catch {
    // 请求层显示后端错误；解析失败时保留用户已编辑的报价表单。
  } finally {
    if (version === contextVersion) parseLoading.value = false;
  }
}

const totalAmount = computed(() =>
  rows.value.reduce(
    (sum, row) =>
      sum + Number(row.unit_price || 0) * Number(row.quoted_quantity || 0),
    0,
  ),
);

const columns = [
  { key: 'requestedName', dataIndex: 'requestedName', title: '物料', minWidth: 160 },
  { key: 'requestedQuantity', dataIndex: 'requestedQuantity', title: '询价数量', width: 110 },
  { key: 'unit_id', title: '报价单位', width: 130 },
  { key: 'supplier_model', title: '供应商型号', width: 150 },
  { key: 'quoted_quantity', title: '报价数量', width: 140 },
  { key: 'unit_price', title: '单价', width: 140 },
  { key: 'tax_rate', title: '税率(%)', width: 110 },
  { key: 'tax_included', title: '价格口径', width: 120 },
  { key: 'lead_days', title: '交期(天)', width: 110 },
  { key: 'moq_quantity', title: '最小起订量', width: 130 },
  { key: 'moq_unit_id', title: 'MOQ单位', width: 120 },
  { key: 'freight_amount', title: '运费', width: 130 },
  { key: 'freight_tax_rate', title: '运费税率(%)', width: 120 },
  { key: 'freight_tax_included', title: '运费税口径', width: 130 },
  { key: 'payment_terms', title: '付款条件', width: 150 },
];

const title = computed(() => `录入报价 · ${rfqNo.value}`);
</script>

<template>
  <Modal :confirm-disabled="busy" :show-confirm-button="canConfirm" :title="title" class="w-[1200px] max-w-[100vw]">
    <Spin :spinning="loading || parseLoading">
      <div class="space-y-4 px-1">
        <Alert
          message="请核对报价、运费、税费和 MOQ 单位。未提供运费按未知处理；填写 0 表示明确无运费。"
          type="info"
          show-icon
        />
        <div class="flex flex-wrap items-center gap-3">
          <input
            ref="fileInput"
            accept=".pdf,.xlsx,.csv,.docx"
            class="hidden"
            type="file"
            @change="parseQuoteFile"
          />
          <Button v-if="canConfirm" :disabled="busy" :loading="parseLoading" @click="fileInput?.click()">
            上传并解析报价文件
          </Button>
          <span v-if="parseCandidate" class="text-xs text-muted-foreground">
            来源文件：{{ parseCandidate.file_name }}
          </span>
        </div>
        <Alert
          v-if="parseCandidate"
          :description="parseCandidate.warnings.join('；')"
          :message="`识别到供应商：${parseCandidate.supplier_name || '未识别'}。请人工选择供应商并核对以下候选值。`"
          type="warning"
          show-icon
        />
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <div class="mb-2 text-sm">
              报价供应商 <span class="text-red-500">*</span>
            </div>
            <Select
              :disabled="busy"
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
              :disabled="busy"
              v-model:value="quoteDate"
              class="w-full"
              value-format="YYYY-MM-DD"
            />
          </div>
          <div>
            <div class="mb-2 text-sm">有效期至</div>
            <DatePicker
              :disabled="busy"
              v-model:value="validUntil"
              class="w-full"
              value-format="YYYY-MM-DD"
            />
          </div>
          <div>
            <div class="mb-2 text-sm">币种</div>
            <Input :disabled="busy" v-model:value="currencyCode" :maxlength="3" />
          </div>
        </div>
        <div>
          <div class="mb-2 text-sm">备注</div>
          <Input :disabled="busy" v-model:value="note" :maxlength="500" />
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
                :disabled="busy"
                v-model:value="record.quoted_quantity"
                :min="0"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'unit_price'">
              <InputNumber
                :disabled="busy"
                v-model:value="record.unit_price"
                :min="0"
                :precision="6"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'tax_rate'">
              <InputNumber
                :disabled="busy"
                v-model:value="record.tax_rate"
                :max="100"
                :min="0"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'tax_included'">
              <Select
                :disabled="busy"
                v-model:value="record.tax_basis"
                :options="[
                  { label: '含税价', value: 'INCLUDED' },
                  { label: '未税价', value: 'EXCLUDED' },
                ]"
                class="w-full"
                placeholder="请选择"
              />
            </template>
            <template v-else-if="column.key === 'lead_days'">
              <InputNumber
                :disabled="busy"
                v-model:value="record.lead_days"
                :min="0"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'moq_quantity'">
              <InputNumber
                :disabled="busy"
                v-model:value="record.moq_quantity"
                :min="0"
                class="w-full"
              />
            </template>
            <template v-else-if="column.key === 'freight_amount'">
              <InputNumber :disabled="busy" v-model:value="record.freight_amount" :min="0" :precision="6" class="w-full" />
            </template>
            <template v-else-if="column.key === 'freight_tax_rate'">
              <InputNumber :disabled="busy" v-model:value="record.freight_tax_rate" :min="0" :max="100" class="w-full" />
            </template>
            <template v-else-if="column.key === 'freight_tax_included'">
              <Select :disabled="busy" v-model:value="record.freight_tax_basis" :options="[{ label: '含税', value: 'INCLUDED' }, { label: '未税', value: 'EXCLUDED' }]" class="w-full" placeholder="请选择" />
            </template>
            <template v-else-if="column.key === 'moq_unit_id'">
              <Select :disabled="busy" v-model:value="record.moq_unit_id" :options="unitOptions" class="w-full" />
            </template>
            <template v-else-if="column.key === 'supplier_model'">
              <Input :disabled="busy" v-model:value="record.supplier_model" :maxlength="100" />
            </template>
            <template v-else-if="column.key === 'unit_id'">
              <Select :disabled="busy" v-model:value="record.unit_id" :options="unitOptions" class="w-full" />
            </template>
            <template v-else-if="column.key === 'payment_terms'">
              <Input :disabled="busy" v-model:value="record.payment_terms" :maxlength="100" />
            </template>
          </template>
        </Table>

        <div v-if="parseCandidate" class="space-y-3 rounded-lg border border-border p-4">
          <div class="text-sm font-medium">解析来源依据</div>
          <div
            v-for="item in parseCandidate.evidence"
            :key="item.field"
            class="border-t border-border pt-2 first:border-0 first:pt-0"
          >
            <div class="text-xs text-muted-foreground">{{ item.field }} · {{ item.source_location }}</div>
            <div class="text-sm">{{ item.value }}：{{ item.source_quote }}</div>
          </div>
          <div
            v-for="(item, index) in parseCandidate.items"
            :key="`${item.source_location}-${index}`"
            class="border-t border-border pt-2"
          >
            <div class="text-xs text-muted-foreground">
              {{ item.product_label || '未识别物料' }} · {{ item.source_location }}
              <span v-if="!item.rfq_item_id" class="text-amber-600">· 未匹配询价明细</span>
              <span
                v-else-if="item.unit_name && unitOptions.find((unit) => unit.value === rows.find((row) => row.rfq_item_id === item.rfq_item_id)?.unit_id)?.label !== item.unit_name"
                class="text-amber-600"
              >· 报价单位与表格选择不同，请核对</span>
            </div>
            <div class="text-sm">{{ item.source_quote }}</div>
          </div>
        </div>

        <div v-if="rows.length > 0" class="text-right text-sm">
          报价合计（按报价单价与数量计算）：
          <span class="text-base font-semibold">
            {{ formatQuantity(totalAmount) }}
          </span>
        </div>
      </div>
    </Spin>
  </Modal>
</template>
