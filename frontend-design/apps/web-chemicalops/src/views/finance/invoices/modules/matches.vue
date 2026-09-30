<script lang="ts" setup>
import type { FinanceApi, InvoiceMatchAllocation, InvoiceMatches } from '#/api';
import { computed, ref } from 'vue';
import { useAccess } from '@vben/access';
import { useVbenDrawer } from '@vben/common-ui';
import { Alert, Button, Input, message, Select, Spin, Table } from 'antdv-next';
import { getInvoiceApi, getInvoiceMatchesApi, saveInvoiceMatchesApi } from '#/api';
import { formatAmount } from '#/utils/format';

const emit = defineEmits(['success']);
const { hasAccessByCodes } = useAccess();
const invoice = ref<FinanceApi.Invoice>();
const result = ref<InvoiceMatches>();
const allocations = ref<InvoiceMatchAllocation[]>([]);
const selectedVersion = ref<number>();
const loading = ref(false);
const saving = ref(false);
const failed = ref(false);
const editable = computed(() => !!invoice.value && !result.value?.legacy && !result.value?.source_changed && ['DRAFT', 'REJECTED'].includes(invoice.value.status) && hasAccessByCodes(['finance.invoices.write']) && selectedVersion.value === result.value?.versions[0]?.version_no);
const columns = [
  { key: 'product', title: '对账行 / 产品', width: 190 },
  { key: 'balance', title: '行应付 / 其他发票占用后可匹配', width: 200 },
  { key: 'amount_excl_tax', title: '本票不含税金额', width: 160 },
  { key: 'tax_amount', title: '本票税额', width: 140 },
  { key: 'difference_note', title: '税额、尾差处理说明', width: 240 },
];
const selected = computed(() => result.value?.versions.find(row => row.version_no === selectedVersion.value));
function chooseVersion() {
  const saved = selected.value;
  if (!result.value) return;
  if (saved && saved !== result.value.versions[0]) {
    allocations.value = saved.allocations.map(row => ({ ...row }));
  } else {
    allocations.value = result.value.items.map(row => ({ ...row, amount_excl_tax: '0', tax_amount: '0', difference_note: '', ...saved?.allocations.find(item => item.reconciliation_item_id === row.reconciliation_item_id) }));
  }
}
function basisRow(id: number) { return result.value?.items.find(row => row.reconciliation_item_id === id); }
async function load() {
  const id = drawerApi.getData();
  if (!id) return;
  loading.value = true;
  failed.value = false;
  try {
    const [header, matches] = await Promise.all([getInvoiceApi(id), getInvoiceMatchesApi(id)]);
    invoice.value = header;
    result.value = matches;
    selectedVersion.value = matches.versions[0]?.version_no;
    chooseVersion();
  } catch { failed.value = true; } finally { loading.value = false; }
}
async function save() {
  if (!invoice.value || !result.value || !editable.value || saving.value) return;
  const rows = allocations.value.filter(row => Number(row.amount_excl_tax) + Number(row.tax_amount) > 0);
  if (!rows.length) { message.warning('请至少填写一条匹配金额'); return; }
  if (allocations.value.some(row => !/^\d+(\.\d{1,6})?$/.test(row.amount_excl_tax) || !/^\d+(\.\d{1,6})?$/.test(row.tax_amount))) {
    message.warning('金额须为非负数，最多六位小数'); return;
  }
  saving.value = true;
  drawerApi.lock();
  try {
    const saved = await saveInvoiceMatchesApi(invoice.value.id, { reconciliation_version: result.value.reconciliation_version, allocations: rows });
    result.value = saved;
    selectedVersion.value = saved.versions[0]?.version_no;
    chooseVersion();
    emit('success');
    message.success(saved.warnings.length ? '已保存草稿，请处理列出的差异后提交核验' : '匹配已保存，可提交核验');
  } catch { /* 请求层显示错误，保留输入 */ } finally { saving.value = false; drawerApi.unlock(); }
}
const [Drawer, drawerApi] = useVbenDrawer<number>({ onOpenChange(open) { if (open) { invoice.value = undefined; result.value = undefined; allocations.value = []; void load(); } } });
</script>

<template>
  <Drawer title="发票行匹配与差异处理" class="w-full max-w-full sm:w-[1000px]" :footer="false">
    <Spin :spinning="loading">
      <div v-if="failed" class="space-y-3 py-4"><Alert type="error" message="匹配加载失败，请重试" /><Button @click="load">重试</Button></div>
      <div v-else-if="invoice && result" class="space-y-4">
        <div class="font-semibold">{{ invoice.invoice_no }} · {{ invoice.invoice_number }}</div>
        <div>{{ invoice.currency_code }} · 不含税 {{ formatAmount(invoice.amount_excl_tax, 6) }} · 税额 {{ formatAmount(invoice.tax_amount, 6) }} · 价税合计 {{ formatAmount(invoice.amount_incl_tax, 6) }}</div>
        <Alert type="info" show-icon message="按实际发票手工分配。不含税与税额合计须分别等于票面金额；税额比例和尾差不同须填写处理说明。提交后由另一名财务人员复核，付款仍按单据管理。" />
        <Alert v-for="warning in result.warnings" :key="warning" type="warning" show-icon :message="warning" />
        <div v-if="!result.legacy" class="flex flex-wrap items-center gap-3">
          <span>对账版本 {{ selected?.reconciliation_version ?? result.reconciliation_version }}</span>
          <Select v-if="result.versions.length" v-model:value="selectedVersion" aria-label="匹配历史版本" class="w-60" :options="result.versions.map(row => ({ value: row.version_no, label: `匹配版本 ${row.version_no} · ${row.created_at}` }))" @change="chooseVersion" />
          <Button v-if="editable" type="primary" :loading="saving" @click="save">保存匹配新版本</Button>
        </div>
        <Table v-if="!result.legacy" :data-source="allocations" :columns="columns" :pagination="false" :scroll="{ x: 930 }" row-key="reconciliation_item_id">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'product'">第 {{ record.line_no }} 行<br />{{ record.product_name }}</template>
            <template v-else-if="column.key === 'balance'"><span v-if="selectedVersion === result.versions[0]?.version_no">{{ formatAmount(basisRow(record.reconciliation_item_id)?.amount_incl_tax, 6) }} / {{ formatAmount(basisRow(record.reconciliation_item_id)?.remaining_amount, 6) }}</span><span v-else class="text-muted-foreground">历史版本不回算当前额度</span></template>
            <template v-else-if="column.key === 'amount_excl_tax'"><Input v-model:value="record.amount_excl_tax" inputmode="decimal" :disabled="!editable" :aria-label="`第 ${record.line_no} 行不含税金额`" /></template>
            <template v-else-if="column.key === 'tax_amount'"><Input v-model:value="record.tax_amount" inputmode="decimal" :disabled="!editable" :aria-label="`第 ${record.line_no} 行税额`" /></template>
            <template v-else-if="column.key === 'difference_note'"><Input.TextArea v-model:value="record.difference_note" :disabled="!editable" :rows="2" :maxlength="1000" :aria-label="`第 ${record.line_no} 行差异处理说明`" /></template>
          </template>
        </Table>
        <div v-if="selected" class="text-muted-foreground">匹配人 #{{ selected.created_by }} · {{ selected.created_at }} · {{ selected.note || '未填写整单备注' }}</div>
        <div v-if="invoice.verified_by" class="text-muted-foreground">复核人 #{{ invoice.verified_by }} · {{ invoice.verified_at }}</div>
      </div>
    </Spin>
  </Drawer>
</template>
