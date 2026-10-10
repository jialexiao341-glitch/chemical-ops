<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
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
} from 'antdv-next';

import { createInvoiceApi, getReconciliationListApi } from '#/api';
import { formatDate } from '#/utils/format';

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
const taxAmount = ref<null | number>(0);
const amountInclTax = ref<null | number>(null);
const note = ref('');
const options = ref<Array<{ label: string; value: number }>>([]);
const loading = ref(false);

/** antd Select 默认按 value（数字 id）过滤，show-search 需显式按 label 搜索 */
function filterByLabel(input: string, option: { label: string }) {
  return option.label.toLowerCase().includes(input.toLowerCase());
}

const [Modal, modalApi] = useVbenModal({
  async onConfirm() {
    if (!canWrite.value) return;
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
    if (!isOpen) {
      return;
    }
    reconciliationId.value = undefined;
    invoiceNumber.value = '';
    invoiceCode.value = '';
    invoiceDate.value = undefined;
    amountExclTax.value = null;
    taxAmount.value = 0;
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
          label: `${item.reconciliation_no}（应付 ${item.total_amount} ${item.currency_code}）`,
          value: item.id,
        }));
    } finally {
      loading.value = false;
    }
  },
});

/** 不含税或税额变化时自动带出价税合计 */
function recalcIncl() {
  if (amountExclTax.value === null) {
    return;
  }
  amountInclTax.value =
    Math.round(
      ((amountExclTax.value ?? 0) + (taxAmount.value ?? 0)) * 1_000_000,
    ) / 1_000_000;
}
</script>

<template>
  <Modal :show-confirm-button="canWrite" title="录入发票" class="w-[640px] max-w-[100vw]">
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
          :filter-option="filterByLabel"
          :options="options"
          class="w-full"
          placeholder="请选择对账单"
          show-search
        />
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
            :format="formatDate"
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
