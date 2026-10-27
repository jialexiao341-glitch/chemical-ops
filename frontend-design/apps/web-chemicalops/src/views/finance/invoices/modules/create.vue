<script lang="ts" setup>
import { computed, ref, watch } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';

import {
  Alert,
  Button,
  DatePicker,
  Empty,
  Input,
  InputNumber,
  Modal as AntModal,
  message,
  Select,
  Spin,
} from 'antdv-next';

import { createInvoiceApi, getReconciliationListApi, parseInvoiceFileApi } from '#/api';
import type { InvoiceParseCandidate } from '#/api/finance';
import { formatAmount } from '#/utils/format';
import { candidateAmount } from './invoice-candidate';

const emit = defineEmits(['success']);
const { hasAccessByCodes } = useAccess();
const canWrite = computed(() => hasAccessByCodes(['finance.invoices.write']));

/**
 * 录入供应商发票。
 * 后端校验：价税合计 = 不含税 + 税额，且累计发票不超过对账应付总额；
 * 已关闭/已取消的对账单不能录入，这里按状态过滤出候选。
 */
const reconciliationId = ref<number>();
const invoiceNumber = ref('');
const invoiceCode = ref('');
const invoiceDate = ref<string>();
const amountExclTax = ref<null | number>(null);
const taxAmount = ref<null | number>(null);
const amountInclTax = ref<null | number>(null);
const note = ref('');
const options = ref<Array<{ label: string; value: number }>>([]);
const loading = ref(false);
const parseLoading = ref(false);
const fileInput = ref<HTMLInputElement>();
const candidate = ref<InvoiceParseCandidate>();
const sourceFileId = ref<number>();
let contextVersion = 0;
const fieldLabels: Record<string, string> = {
  invoice_number: '发票号码', invoice_code: '发票代码', invoice_date: '开票日期',
  amount_excl_tax: '不含税金额', tax_amount: '税额', amount_incl_tax: '价税合计',
};
watch(reconciliationId, () => { contextVersion++; candidate.value = undefined; sourceFileId.value = undefined; });

async function parseFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file || !reconciliationId.value || parseLoading.value || !canWrite.value) return;
  const version = contextVersion;
  const id = reconciliationId.value;
  parseLoading.value = true;
  try {
    const result = await parseInvoiceFileApi(id, file);
    if (version !== contextVersion) return;
    candidate.value = result;
    message.success('解析完成，请核对候选值及原文依据');
  } catch {
    // 解析失败不改变当前表单或已应用来源。
  } finally {
    if (version === contextVersion) parseLoading.value = false;
  }
}
function applyCandidate() {
  const value = candidate.value;
  if (!value || parseLoading.value) return;
  const version = contextVersion;
  AntModal.confirm({
    title: '带入发票候选字段？',
    content: '识别到的字段会覆盖当前对应内容，未识别的字段保持不变。请在提交前逐项核对。',
    okText: '确认带入', cancelText: '取消',
    onOk: () => {
      if (version !== contextVersion || candidate.value !== value) return;
      if (value.invoice_number !== null) invoiceNumber.value = value.invoice_number;
      if (value.invoice_code !== null) invoiceCode.value = value.invoice_code;
      if (value.invoice_date !== null) invoiceDate.value = value.invoice_date;
      const rejected: string[] = [];
      function amount(raw: null | string, label: string): null | number {
        const result = candidateAmount(raw);
        if (!result.valid) rejected.push(label);
        return result.value;
      }
      const excl = amount(value.amount_excl_tax, '不含税金额');
      const tax = amount(value.tax_amount, '税额');
      const incl = amount(value.amount_incl_tax, '价税合计');
      if (excl !== null) amountExclTax.value = excl;
      if (tax !== null) taxAmount.value = tax;
      if (incl !== null) amountInclTax.value = incl;
      if (rejected.length) message.warning(`${rejected.join('、')}超出控件精度，请人工核对录入`);
      sourceFileId.value = value.file_id;
    },
  });
}

/** antd Select 默认按 value（数字 id）过滤，show-search 需显式按 label 搜索 */
function filterByLabel(input: string, option: { label: string }) {
  return option.label.toLowerCase().includes(input.toLowerCase());
}

const [Modal, modalApi] = useVbenModal({
  async onConfirm() {
    if (!canWrite.value || parseLoading.value) return;
    if (!reconciliationId.value) {
      message.warning('请选择对账单');
      return;
    }
    if (!invoiceNumber.value.trim()) {
      message.warning('请填写发票号码');
      return;
    }
    if (!invoiceDate.value) {
      message.warning('请选择开票日期');
      return;
    }
    if (amountExclTax.value === null || amountExclTax.value < 0) {
      message.warning('请填写不含税金额');
      return;
    }
    if (taxAmount.value === null || taxAmount.value < 0) {
      message.warning('请填写税额，无税时填写 0');
      return;
    }
    if (amountInclTax.value === null || amountInclTax.value <= 0) {
      message.warning('请填写价税合计金额');
      return;
    }
    const expected = Math.round(
      ((amountExclTax.value ?? 0) + (taxAmount.value ?? 0)) * 1_000_000,
    ) / 1_000_000;
    if (Math.abs(expected - amountInclTax.value) > 0.0000009) {
      message.warning('价税合计必须等于不含税金额加税额');
      return;
    }
    modalApi.lock();
    try {
      await createInvoiceApi({
        amount_excl_tax: amountExclTax.value,
        amount_incl_tax: amountInclTax.value,
        invoice_code: invoiceCode.value.trim() || undefined,
        invoice_date: invoiceDate.value,
        invoice_number: invoiceNumber.value.trim(),
        note: note.value.trim() || undefined,
        reconciliation_id: reconciliationId.value,
        source_file_id: sourceFileId.value,
        tax_amount: taxAmount.value ?? 0,
      });
      message.success('发票已录入（草稿）');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层已弹出后端中文错误，保持弹窗打开
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    contextVersion++;
    candidate.value = undefined;
    sourceFileId.value = undefined;
    parseLoading.value = false;
    if (!isOpen) {
      return;
    }
    reconciliationId.value = undefined;
    invoiceNumber.value = '';
    invoiceCode.value = '';
    invoiceDate.value = undefined;
    amountExclTax.value = null;
    taxAmount.value = null;
    amountInclTax.value = null;
    note.value = '';
    loading.value = true;
    try {
      const res = await getReconciliationListApi({
        page: 1,
        page_size: 100,
      });
      options.value = res.items
        .filter((item) => !['CANCELLED', 'CLOSED'].includes(item.status))
        .map((item) => ({
          label: `${item.reconciliation_no}（应付 ${formatAmount(item.total_amount)} ${item.currency_code}）`,
          value: item.id,
        }));
    } finally {
      loading.value = false;
    }
  },
});

/** 不含税或税额变化时自动带出价税合计 */
function recalcIncl() {
  if (amountExclTax.value === null || taxAmount.value === null) {
    return;
  }
  amountInclTax.value =
    Math.round(
      ((amountExclTax.value ?? 0) + (taxAmount.value ?? 0)) * 1_000_000,
    ) / 1_000_000;
}
</script>

<template>
  <Modal :confirm-disabled="parseLoading" :show-confirm-button="canWrite" title="录入发票" class="w-[640px] max-w-[100vw]">
    <Spin :spinning="loading">
      <div class="space-y-4 px-1">
        <Alert
          message="价税合计 = 不含税 + 税额；发票累计金额不能超过对账应付总额。录入后为草稿，提交核验后才能被付款引用。"
          type="info"
          show-icon
        />
        <Empty
          v-if="options.length === 0 && !loading"
          description="当前没有可录入发票的对账单"
        />
        <Select
          v-else
          v-model:value="reconciliationId"
          :disabled="parseLoading"
          :filter-option="filterByLabel"
          :options="options"
          class="w-full"
          placeholder="请选择对账单"
          show-search
        />
        <div class="flex flex-wrap items-center gap-3">
          <input ref="fileInput" accept=".pdf,.png,.jpg,.jpeg,.xlsx,.csv,.docx,.txt" class="hidden" type="file" @change="parseFile" />
          <Button v-if="canWrite" :disabled="!reconciliationId || parseLoading" :loading="parseLoading" @click="fileInput?.click()">上传并解析发票文件</Button>
          <span v-if="candidate" class="text-xs text-muted-foreground">来源文件：{{ candidate.file_name }}</span>
        </div>
        <template v-if="candidate">
          <Alert :description="candidate.warnings.join('；')" message="请核对候选字段和原文依据" type="warning" show-icon />
          <div class="space-y-2">
            <div v-for="item in candidate.evidence" :key="item.field" class="text-sm">
              <strong>{{ fieldLabels[item.field] || item.field }}：</strong>{{ item.value }}
              <span class="text-muted-foreground">（{{ item.source_location }}：{{ item.source_quote }}）</span>
            </div>
          </div>
          <Button :disabled="parseLoading" @click="applyCandidate">带入候选字段</Button>
        </template>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <div class="mb-1 text-sm">
              发票号码 <span class="text-red-500">*</span>
            </div>
            <Input
              v-model:value="invoiceNumber"
              :maxlength="64"
              placeholder="发票号码"
            />
          </div>
          <div>
            <div class="mb-1 text-sm">发票代码</div>
            <Input
              v-model:value="invoiceCode"
              :maxlength="32"
              placeholder="发票代码（选填）"
            />
          </div>
        </div>
        <div>
          <div class="mb-1 text-sm">
            开票日期 <span class="text-red-500">*</span>
          </div>
          <DatePicker
            v-model:value="invoiceDate"
            class="w-full"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
          />
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <div class="mb-1 text-sm">
              不含税 <span class="text-red-500">*</span>
            </div>
            <InputNumber
              v-model:value="amountExclTax"
              :min="0"
              :precision="6"
              class="w-full"
              placeholder="0.00"
              @change="recalcIncl"
            />
          </div>
          <div>
            <div class="mb-1 text-sm">税额</div>
            <InputNumber
              v-model:value="taxAmount"
              :min="0"
              :precision="6"
              class="w-full"
              placeholder="0.00"
              @change="recalcIncl"
            />
          </div>
          <div>
            <div class="mb-1 text-sm">
              价税合计 <span class="text-red-500">*</span>
            </div>
            <InputNumber
              v-model:value="amountInclTax"
              :min="0"
              :precision="6"
              class="w-full"
              placeholder="0.00"
            />
          </div>
        </div>
        <Input.TextArea
          v-model:value="note"
          :maxlength="1000"
          :rows="2"
          placeholder="备注（选填）"
        />
      </div>
    </Spin>
  </Modal>
</template>
