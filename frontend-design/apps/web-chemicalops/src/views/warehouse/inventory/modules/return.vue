<script lang="ts" setup>
import type { InventoryApi, ReturnSource } from '#/api';
import { computed, ref } from 'vue';
import { useVbenModal } from '@vben/common-ui';
import { Alert, Button, Input, InputNumber, message, Select, Spin } from 'antdv-next';
import { createInventoryReturnApi, getReturnSourcesApi } from '#/api';
import { formatQuantity } from '#/utils/format';

const emit = defineEmits(['success']);
const balance = ref<InventoryApi.InventoryBalance>();
const sources = ref<ReturnSource[]>([]);
const selected = ref<number>();
const reason = ref('');
const quantity = ref<number | null>(null);
const loading = ref(false);
const submitting = ref(false);
const failed = ref(false);
const source = computed(() => sources.value.find(row => row.source_delivery_item_id === selected.value));
const maxQuantity = computed(() => Math.max(0, Math.min(Number(balance.value?.quantity ?? 0) - Number(balance.value?.locked_quantity ?? 0), Number(source.value?.received_quantity ?? 0) - Number(source.value?.returned_quantity ?? 0))));
async function load() {
  if (!balance.value) return;
  loading.value = true;
  failed.value = false;
  try {
    sources.value = await getReturnSourcesApi(balance.value.id);
    selected.value = sources.value.length === 1 ? sources.value[0]?.source_delivery_item_id : undefined;
  } catch { failed.value = true; } finally { loading.value = false; }
}
const [Modal, modalApi] = useVbenModal<InventoryApi.InventoryBalance>({
  async onOpenChange(open) {
    if (!open) return;
    balance.value = modalApi.getData();
    sources.value = []; selected.value = undefined; reason.value = ''; quantity.value = null;
    await load();
  },
  async onConfirm() {
    if (loading.value || submitting.value || !balance.value || !source.value || !balance.value.batch_id) return;
    if (!reason.value.trim() || !quantity.value || quantity.value <= 0 || quantity.value > maxQuantity.value) {
      message.warning('请选择来源、填写原因，并输入不超过可退数量的正数'); return;
    }
    submitting.value = true;
    modalApi.lock();
    try {
      const row = balance.value;
      await createInventoryReturnApi({ supplier_id: source.value.supplier_id, reason: reason.value.trim(), items: [{
        product_id: row.product_id, warehouse_id: row.warehouse_id, location_id: row.location_id,
        batch_id: row.batch_id!, unit_id: row.unit_id, source_delivery_item_id: source.value.source_delivery_item_id,
        source_po_item_id: source.value.source_po_item_id, requested_quantity: String(quantity.value),
      }] });
      message.success('退货草稿已创建，请在供应商退货中提交审批'); emit('success'); modalApi.close();
    } catch { /* 保留输入，错误由请求层显示 */ } finally { submitting.value = false; modalApi.unlock(); }
  },
});
</script>

<template>
  <Modal title="申请供应商退货" class="w-full max-w-full sm:w-[580px]" confirm-text="创建草稿">
    <Spin :spinning="loading">
      <div class="space-y-4">
        <Alert message="退货申请需审批后再执行出库。财务将按订单行单独确认扣款或待补交口径。" type="info" show-icon />
        <div v-if="failed"><Alert message="来源加载失败，请重试" type="error" /><Button @click="load">重试</Button></div>
        <Alert v-else-if="!loading && !sources.length" type="warning" message="该批次没有可核对的到货明细，请先核实历史来源。" />
        <div><label class="mb-2 block">原始到货明细</label><Select v-model:value="selected" class="w-full" :disabled="loading" :options="sources.map(row => ({ value: row.source_delivery_item_id, label: `${row.delivery_no} / 第${row.line_no}行 / ${row.product_name}` }))" placeholder="选择来源" /></div>
        <div v-if="source" class="text-muted-foreground text-sm">{{ source.supplier_name }} · {{ source.po_no }} · 批次 {{ source.batch_no }}<br />可退 {{ formatQuantity(maxQuantity) }} {{ source.unit_name }}（库存可用量与来源剩余收货量取较小值）</div>
        <div><label class="mb-2 block">退货数量</label><InputNumber v-model:value="quantity" :min="0.000001" :max="maxQuantity" :precision="6" :disabled="!source || loading" class="w-full" /></div>
        <div><label class="mb-2 block">退货原因</label><Input.TextArea v-model:value="reason" :maxlength="1000" :rows="3" placeholder="请填写退货原因" /></div>
      </div>
    </Spin>
  </Modal>
</template>
