<script lang="ts" setup>
import type { InventoryReturn } from '#/api';
import { onMounted, ref } from 'vue';
import { useAccess } from '@vben/access';
import { Page } from '@vben/common-ui';
import { Alert, Button, Input, message, Modal, Select, Table, Tag } from 'antdv-next';
import { actInventoryReturnApi, getInventoryReturnsApi } from '#/api';
import { formatQuantity } from '#/utils/format';

defineOptions({ name: 'InventoryReturns' });
const { hasAccessByCodes } = useAccess();
const rows = ref<InventoryReturn[]>([]);
const loading = ref(false);
const busy = ref(false);
const failed = ref(false);
const page = ref(1);
const total = ref(0);
const status = ref<string>();
const rejectRow = ref<InventoryReturn>();
const reason = ref('');
const rejectVisible = ref(false);
const statuses: Record<string, string> = { DRAFT: '草稿', SUBMITTED: '待审批', APPROVED: '已审批', REJECTED: '已驳回', CANCELLED: '已取消', COMPLETED: '已完成' };
const columns = [
  { title: '退货单号', dataIndex: 'return_no', key: 'return_no', width: 190 },
  { title: '退货原因', dataIndex: 'reason', key: 'reason', width: 260 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 110 },
  { title: '操作', key: 'actions', width: 220 },
];
async function load() {
  loading.value = true; failed.value = false;
  try { const result = await getInventoryReturnsApi({ page: page.value, page_size: 20, status: status.value }); rows.value = result.items; total.value = result.total; }
  catch { failed.value = true; } finally { loading.value = false; }
}
async function act(row: InventoryReturn, action: 'approve' | 'cancel' | 'execute' | 'reject' | 'submit', note?: string) {
  if (busy.value) return;
  busy.value = true;
  try { await actInventoryReturnApi(row.id, action, note); message.success('操作成功'); rejectVisible.value = false; await load(); }
  catch { /* 错误由请求层显示，保持驳回原因 */ } finally { busy.value = false; }
}
function confirmAction(row: InventoryReturn, action: 'approve' | 'cancel' | 'execute' | 'submit') {
  Modal.confirm({ title: action === 'execute' ? '确认退货出库' : '确认操作', content: action === 'execute' ? `执行 ${row.return_no} 将扣减库存并记录退货成本，请确认实物已完成退货。` : `确认处理退货单 ${row.return_no}？`, onOk: () => act(row, action) });
}
function reject(row: InventoryReturn) { rejectRow.value = row; reason.value = ''; rejectVisible.value = true; }
function submitReject() {
  if (!reason.value.trim()) { message.warning('请填写驳回原因'); return; }
  if (rejectRow.value) void act(rejectRow.value, 'reject', reason.value.trim());
}
onMounted(load);
</script>

<template>
  <Page title="供应商退货">
    <div class="space-y-4">
      <Alert type="info" message="从库存台账的“申请退货”创建草稿。展开退货单可查看产品、数量及原始到货和采购订单。" />
      <div class="flex flex-wrap gap-3"><Select v-model:value="status" allow-clear class="w-40" placeholder="全部状态" :options="Object.entries(statuses).map(([value, label]) => ({ value, label }))" @change="page = 1; load()" /><Button :loading="loading" @click="load">刷新</Button></div>
      <Alert v-if="failed" type="error" message="退货列表加载失败，请刷新重试" />
      <Table :columns="columns" :data-source="rows" :loading="loading" row-key="id" :scroll="{ x: 800 }" :pagination="{ current: page, pageSize: 20, total, showSizeChanger: false }" @change="pagination => { page = pagination.current ?? 1; load(); }">
        <template #bodyCell="{ column, record: row }">
          <template v-if="column.key === 'status'"><Tag>{{ statuses[row.status] ?? row.status }}</Tag></template>
          <template v-else-if="column.key === 'actions'">
            <template v-if="hasAccessByCodes(['warehouse.inventory.return.write'])">
              <Button v-if="['DRAFT', 'REJECTED'].includes(row.status)" type="link" :disabled="busy" @click="confirmAction(row, 'submit')">提交审批</Button>
              <Button v-if="['DRAFT', 'REJECTED'].includes(row.status)" type="link" :disabled="busy" @click="confirmAction(row, 'cancel')">取消</Button>
              <Button v-if="row.status === 'APPROVED'" type="link" :disabled="busy" @click="confirmAction(row, 'execute')">执行出库</Button>
            </template>
            <template v-if="row.status === 'SUBMITTED' && hasAccessByCodes(['warehouse.inventory.return.approve'])"><Button type="link" :disabled="busy" @click="confirmAction(row, 'approve')">审批通过</Button><Button danger type="link" :disabled="busy" @click="reject(row)">驳回</Button></template>
          </template>
        </template>
        <template #expandedRowRender="{ record: row }">
          <div class="space-y-2">
            <Alert v-if="row.reject_reason" type="warning" :message="`驳回原因：${row.reject_reason}`" />
            <div v-for="item in row.items" :key="item.id" class="border-border border-b py-2">
              <div>{{ item.product_name || '产品名称未记录' }} · 申请 {{ formatQuantity(item.requested_quantity) }} / 已退 {{ formatQuantity(item.returned_quantity) }} {{ item.unit_name }}</div>
              <div class="text-muted-foreground">{{ item.source_po_no || '订单行来源待核查' }} · {{ item.source_delivery_no || '到货明细来源未记录' }}</div>
            </div>
          </div>
        </template>
      </Table>
      <Modal v-model:open="rejectVisible" title="驳回退货申请" :confirm-loading="busy" @ok="submitReject"><Input.TextArea v-model:value="reason" :rows="3" :maxlength="1000" placeholder="填写驳回原因" /></Modal>
    </div>
  </Page>
</template>
