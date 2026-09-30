<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { Descriptions, DescriptionsItem, Empty, Spin } from 'antdv-next';

import {
  getInvoiceApi,
  getPaymentApi,
  getReconciliationApi,
  getSettlementApi,
} from '#/api';
import { formatDate, formatDateTime } from '#/utils/format';

type FinanceRecordKind = 'invoices' | 'payments' | 'reconciliations' | 'settlements';
interface FinanceRecordRequest {
  id: number;
  kind: FinanceRecordKind;
}

const record = ref<Record<string, unknown>>();
const recordKind = ref<FinanceRecordKind>();
const loading = ref(false);
const labels: Record<string, string> = {
  amount: '金额',
  amount_precision: '金额小数位',
  items_version: '对账明细版本',
  amount_excl_tax: '不含税金额',
  amount_incl_tax: '价税合计',
  approved_at: '审批时间',
  approved_by: '审批人 ID',
  cancel_reason: '取消原因',
  cancelled_at: '取消时间',
  closed_at: '关闭时间',
  confirmed_at: '确认时间',
  confirmed_by: '确认人 ID',
  created_at: '创建时间',
  created_by: '创建人 ID',
  created_by_id: '创建人 ID',
  currency_code: '币种',
  id: '记录 ID',
  invoice_code: '发票代码',
  invoice_date: '开票日期',
  invoice_no: '发票号',
  invoice_number: '发票号码',
  note: '备注',
  paid_at: '付款时间',
  paid_by: '付款登记人 ID',
  payment_method: '付款方式',
  payment_no: '付款单号',
  po_id: '采购订单 ID',
  reconciliation_id: '对账单 ID',
  reconciliation_no: '对账单号',
  reject_reason: '驳回原因',
  requested_by: '申请人 ID',
  settlement_amount: '结算金额',
  settlement_no: '结算单号',
  source_file_id: '来源文件 ID',
  status: '状态',
  submitted_by: '提交人 ID',
  supplier_id: '供应商 ID',
  tax_amount: '税额',
  total_amount: '对账金额',
  transaction_ref: '外部流水号',
  updated_at: '更新时间',
  verified_at: '人工核验时间',
  verified_by: '人工核验人 ID',
};
const items = computed(() =>
  Object.entries(record.value ?? {}).map(([key, value]) => ({
    key,
    label: labels[key] ?? key,
    value:
      typeof value === 'string' && /_at$/.test(key)
        ? formatDateTime(value)
        : typeof value === 'string' && /_date$/.test(key)
          ? formatDate(value)
        : value == null || value === ''
          ? '—'
          : String(value),
  })),
);
const title = computed(() => {
  const names: Record<FinanceRecordKind, string> = {
    invoices: '供应商发票',
    payments: '付款记录',
    reconciliations: '财务对账单',
    settlements: '采购结算单',
  };
  const key = recordKind.value;
  const numberField: Record<FinanceRecordKind, string> = {
    invoices: 'invoice_no',
    payments: 'payment_no',
    reconciliations: 'reconciliation_no',
    settlements: 'settlement_no',
  };
  return key ? `${names[key]} ${record.value?.[numberField[key]] ?? ''}` : '财务记录详情';
});

const [Drawer, drawerApi] = useVbenDrawer<null | FinanceRecordRequest>({
  footer: false,
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    const request = drawerApi.getData();
    record.value = undefined;
    recordKind.value = request?.kind;
    if (!request || !Number.isInteger(request.id) || request.id <= 0) return;
    loading.value = true;
    try {
      const fetchers: Record<FinanceRecordKind, (id: number) => Promise<unknown>> = {
        invoices: getInvoiceApi,
        payments: getPaymentApi,
        reconciliations: getReconciliationApi,
        settlements: getSettlementApi,
      };
      record.value = (await fetchers[request.kind](request.id)) as Record<string, unknown>;
    } finally {
      loading.value = false;
    }
  },
});

defineExpose({
  open: (request: FinanceRecordRequest) => drawerApi.setData(request).open(),
});
</script>

<template>
  <Drawer :title="title" class="w-[760px]">
    <Spin :spinning="loading">
      <Empty v-if="!record && !loading" description="未找到该财务记录或当前账号无权查看" />
      <Descriptions v-else-if="record" bordered :column="2" size="small">
        <DescriptionsItem v-for="item in items" :key="item.key" :label="item.label">
          {{ item.value }}
        </DescriptionsItem>
      </Descriptions>
    </Spin>
  </Drawer>
</template>
