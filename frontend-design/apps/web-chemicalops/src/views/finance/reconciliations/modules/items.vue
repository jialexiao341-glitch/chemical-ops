<script lang="ts" setup>
import type { FinanceApi, ReconciliationItem, ReconciliationItems } from '#/api';
import { computed, ref } from 'vue';
import { useAccess } from '@vben/access';
import { useVbenDrawer } from '@vben/common-ui';
import { Alert, Button, Input, InputNumber, message, Select, Spin, Table } from 'antdv-next';
import { getReconciliationApi, getReconciliationItemsApi, refreshReconciliationItemsApi } from '#/api';
import { formatAmount, formatQuantity } from '#/utils/format';

const emit = defineEmits(['success']);
const { hasAccessByCodes } = useAccess();
const record = ref<FinanceApi.Reconciliation>();
const basis = ref<ReconciliationItems>();
const loading = ref(false);
const saving = ref(false);
const failed = ref(false);
const precision = ref(2);
const selectedVersion = ref<number>();
const editable = computed(() => !!record.value && hasAccessByCodes(['finance.reconciliations.write']) && ['DRAFT', 'DISPUTED'].includes(record.value.status) && basis.value?.version_no === record.value.items_version);
const rowWarnings = computed(() => basis.value?.items.flatMap(row => row.warnings.map(warning => `第 ${row.line_no} 行：${warning}`)) ?? []);
const treatments = [
  { label: '待确认', value: 'PENDING' },
  { label: '退货扣款', value: 'DEDUCT' },
  { label: '待补交（保留应付）', value: 'REPLACEMENT' },
];
const columns = [
  { title: '产品 / 单位', key: 'product', width: 170 },
  ...[
    ['ordered_quantity', '订购'], ['received_quantity', '实收'], ['accepted_quantity', '验收通过'],
    ['returned_quantity', '已退货'], ['reconciliation_quantity', '对账数量'],
  ].map(([key, title]) => ({ key, dataIndex: key, title, width: 110, align: 'right' as const })),
  { title: '单价 / 税率', key: 'price', width: 130, align: 'right' as const },
  { title: '不含税 / 税额 / 含税', key: 'amount', width: 170, align: 'right' as const },
  { title: '退货口径与依据', key: 'decision', width: 250 },
];
function quantityText(row: ReconciliationItem, key: unknown) {
  return formatQuantity(row[String(key) as keyof Pick<ReconciliationItem, 'ordered_quantity' | 'received_quantity' | 'accepted_quantity' | 'returned_quantity' | 'reconciliation_quantity'>]);
}
async function load(version?: number) {
  const id = drawerApi.getData();
  if (!id) return;
  loading.value = true;
  failed.value = false;
  try {
    const [header, items] = await Promise.all([getReconciliationApi(id), getReconciliationItemsApi(id, version)]);
    record.value = header;
    basis.value = items;
    precision.value = items.amount_precision;
    selectedVersion.value = items.version_no || undefined;
  } catch { failed.value = true; } finally { loading.value = false; }
}
async function save() {
  if (!basis.value || !record.value || !editable.value || saving.value) return;
  if (basis.value.items.some(row => ['DEDUCT', 'REPLACEMENT'].includes(row.return_treatment) && !row.treatment_note?.trim())) {
    message.warning('选择退货扣款或待补交时，请填写依据');
    return;
  }
  saving.value = true;
  drawerApi.lock();
  try {
    await refreshReconciliationItemsApi(record.value.id, {
      amount_precision: precision.value,
      decisions: basis.value.items.filter(row => Number(row.returned_quantity) > 0).map(row => ({ po_item_id: row.po_item_id, return_treatment: row.return_treatment, treatment_note: row.treatment_note?.trim() })),
    });
    await load();
    emit('success');
    message.success('已保存新版本，对账金额已更新');
  } catch { /* 请求层显示错误，保留输入 */ } finally { saving.value = false; drawerApi.unlock(); }
}
const [Drawer, drawerApi] = useVbenDrawer<number>({ onOpenChange(open) { if (open) { basis.value = undefined; record.value = undefined; void load(); } } });
</script>

<template>
  <Drawer title="订单行对账明细" class="w-full max-w-full sm:w-[1100px]" :footer="false">
    <Spin :spinning="loading">
      <div v-if="failed" class="space-y-3 py-4"><Alert message="明细加载失败，请重试" type="error" /><Button @click="load()">重试</Button></div>
      <div v-else-if="basis && record" class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div><div class="font-semibold">{{ record.reconciliation_no }}</div><div class="text-muted-foreground">{{ basis.currency_code }} · 含税合计 {{ formatAmount(basis.total_amount, basis.amount_precision) }}</div></div>
          <Select v-if="basis.available_versions.length" :value="selectedVersion" :disabled="loading || saving" class="w-40" :options="basis.available_versions.map(v => ({ label: `第 ${v} 版${v === record?.items_version ? '（当前）' : ''}`, value: v }))" @change="value => load(Number(value))" />
        </div>
        <Alert v-if="basis.source_changed" type="warning" show-icon message="来源已变化或尚未建立明细，请核查后重新生成。历史版本金额保持原值。" />
        <Alert v-for="warning in basis.warnings" :key="warning" :message="warning" type="warning" show-icon />
        <Alert v-for="warning in rowWarnings" :key="warning" :message="warning" type="warning" show-icon />
        <div class="flex flex-wrap items-center gap-3">
          <label for="amount-precision">金额小数位</label><InputNumber id="amount-precision" v-model:value="precision" :min="0" :max="6" :precision="0" :disabled="!editable || saving" />
          <span class="text-muted-foreground text-xs">不含税金额和税额逐行四舍五入，再汇总含税金额。</span>
          <Button v-if="editable" type="primary" :loading="saving" :disabled="loading" @click="save">按最新来源保存新版本</Button>
        </div>
        <Alert v-if="editable" type="info" message="扣款减少应付；待补交保留应付且必须填写依据。修改口径后保存新版本，金额才会更新。未处理的问题会阻止确认。" />
        <Table :columns="columns" :data-source="basis.items" row-key="id" :pagination="false" :scroll="{ x: 1270 }" size="small">
          <template #bodyCell="{ column, record: row }">
            <template v-if="column.key === 'product'">{{ row.product_name }}<div class="text-muted-foreground">第 {{ row.line_no }} 行 · {{ row.unit_name }}</div></template>
            <template v-else-if="String(column.key).endsWith('_quantity')">{{ quantityText(row, column.key) }}</template>
            <template v-else-if="column.key === 'price'">{{ formatAmount(row.unit_price, 6) }}<div>{{ row.tax_rate }}%</div></template>
            <template v-else-if="column.key === 'amount'">{{ formatAmount(row.amount_excl_tax, basis.amount_precision) }} / {{ formatAmount(row.tax_amount, basis.amount_precision) }}<div class="font-semibold">{{ formatAmount(row.amount_incl_tax, basis.amount_precision) }}</div></template>
            <template v-else-if="column.key === 'decision'">
              <template v-if="Number(row.returned_quantity) > 0">
                <Select v-model:value="row.return_treatment" :options="treatments" :disabled="!editable || saving" class="mb-2 w-full" aria-label="退货金额处理口径" />
                <Input.TextArea v-model:value="row.treatment_note" :disabled="!editable || saving" :rows="2" :maxlength="1000" placeholder="填写扣款或待补交依据" />
              </template><span v-else>无已完成退货</span>
            </template>
          </template>
          <template #expandedRowRender="{ record: row }">
            <div class="space-y-2">
              <div v-for="receipt in row.basis_json.receipts" :key="receipt.delivery_no + receipt.quantity">到货 {{ receipt.delivery_no }} · 实收 {{ formatQuantity(receipt.quantity) }} {{ row.unit_name }} · {{ receipt.status === 'ACCEPTED' ? '验收通过' : receipt.status }}</div>
              <div v-for="returned in row.basis_json.returns" :key="returned.return_no">退货 {{ returned.return_no }} · 已退 {{ formatQuantity(returned.returned_quantity) }} {{ row.unit_name }} · {{ returned.status === 'COMPLETED' ? '已完成' : '处理中' }}</div>
              <Alert v-for="warning in row.warnings" :key="warning" :message="warning" type="warning" />
            </div>
          </template>
        </Table>
      </div>
    </Spin>
  </Drawer>
</template>
