<script lang="ts" setup>
import type { SupplierPortalApi } from '#/api';

import { ref } from 'vue';

import { useAccess } from '@vben/access';
import { Button, Empty, Input, message, Modal, Spin, Tag } from 'antdv-next';

import { addSupplierReconciliationMessageApi, confirmSupplierReconciliationApi, disputeSupplierReconciliationApi, getSupplierReconciliationListApi, getSupplierReconciliationMessagesApi } from '#/api';
import { RECONCILIATION_STATUS_DICT } from '#/constants/dictionary';
import { formatAmount, formatDateTime } from '#/utils/format';
import SupplierRecordList from '../components/SupplierRecordList.vue';

defineOptions({ name: 'SupplierReconciliations' });

const { hasAccessByCodes } = useAccess();
const rows = ref<SupplierPortalApi.Reconciliation[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const keyword = ref('');
const status = ref('');
const loading = ref(false);
const drawerOpen = ref(false);
const active = ref<SupplierPortalApi.Reconciliation>();
const messages = ref<SupplierPortalApi.ReconciliationMessage[]>([]);
const draftMessage = ref('');
const reason = ref('');
const disputeOpen = ref(false);
const sending = ref(false);

const columns = [
  { key: 'reconciliation_no', title: '对账单号', width: 190 },
  { key: 'po_no', title: '采购订单', width: 180 },
  { key: 'total_amount', title: '对账金额', width: 170 },
  { key: 'items_version', title: '明细版本', width: 110 },
  { key: 'status', title: '对账状态', width: 120 },
  { key: 'updated_at', title: '更新时间', width: 180 },
  { key: '__action', title: '操作', width: 130 },
];
const statusOptions = [{ label: '全部状态', value: '' }, ...RECONCILIATION_STATUS_DICT.options()];
const canRespond = hasAccessByCodes(['supplier.portal.reconciliation.respond']);
const canMessage = hasAccessByCodes(['supplier.portal.reconciliation.message']);

async function load() {
  loading.value = true;
  try {
    const result = await getSupplierReconciliationListApi({ page: page.value, page_size: pageSize.value, keyword: keyword.value || undefined, status: status.value || undefined });
    rows.value = result.items;
    total.value = result.total;
  } finally { loading.value = false; }
}
async function openMessages(record: SupplierPortalApi.Reconciliation) {
  active.value = record;
  drawerOpen.value = true;
  await loadMessages();
}
async function loadMessages() {
  if (!active.value) return;
  const result = await getSupplierReconciliationMessagesApi(active.value.id);
  messages.value = result.items;
}
async function sendMessage() {
  if (!active.value || !draftMessage.value.trim() || sending.value) return;
  sending.value = true;
  try {
    await addSupplierReconciliationMessageApi(active.value.id, draftMessage.value.trim());
    draftMessage.value = '';
    await loadMessages();
    message.success('留言已发送');
  } finally { sending.value = false; }
}
async function confirm(record: SupplierPortalApi.Reconciliation) {
  Modal.confirm({
    title: '确认对账',
    content: `确认对账单 ${record.reconciliation_no} 的明细和金额？确认前系统会重新校验收货、验收及对账快照。`,
    okText: '确认对账',
    onOk: async () => {
      await confirmSupplierReconciliationApi(record.id);
      message.success('对账已确认');
      await load();
      if (active.value?.id === record.id) { active.value.status = 'CONFIRMED'; await loadMessages(); }
    },
  });
}
function openDispute(record: SupplierPortalApi.Reconciliation) {
  active.value = record;
  reason.value = '';
  disputeOpen.value = true;
}
async function submitDispute() {
  if (!active.value || !reason.value.trim()) { message.warning('请填写争议原因'); return; }
  sending.value = true;
  try {
    await disputeSupplierReconciliationApi(active.value.id, reason.value.trim());
    disputeOpen.value = false;
    drawerOpen.value = true;
    message.success('已提交对账争议');
    await load();
    await loadMessages();
  } finally { sending.value = false; }
}


</script>

<template>
  <SupplierRecordList
    export-permission="supplier.portal.reconciliation.export"
    v-model:keyword="keyword"
    v-model:status="status"
    :columns="columns"
    :fetch-records="load"
    :loading="loading"
    v-model:page="page"
    v-model:page-size="pageSize"
    :rows="rows"
    :status-options="statusOptions"
    :total="total"
    :scroll-x="1230"
    subtitle="查看本供应商订单的对账金额与状态，可确认、提出争议并和采购方留言协同。"
    title="对账协同"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'reconciliation_no'"><span>{{ record.reconciliation_no }}</span></template>
      <template v-else-if="column.key === 'po_no'">{{ record.po_no }}</template>
      <template v-else-if="column.key === 'total_amount'">{{ formatAmount(record.total_amount) }} {{ record.currency_code }}</template>
      <template v-else-if="column.key === 'items_version'">{{ record.items_version ? `第 ${record.items_version} 版` : '待生成' }}</template>
      <template v-else-if="column.key === 'status'"><Tag :color="RECONCILIATION_STATUS_DICT.color(record.status)">{{ RECONCILIATION_STATUS_DICT.label(record.status) }}</Tag></template>
      <template v-else-if="column.key === 'updated_at'">{{ formatDateTime(record.updated_at) }}</template>
      <template v-else-if="column.key === '__action'">
        <div class="flex flex-wrap gap-x-1">
          <Button size="small" type="link" @click="openMessages(record)">协同留言</Button>
          <Button v-if="canRespond && ['DRAFT', 'DISPUTED'].includes(record.status)" size="small" type="link" @click="confirm(record)">确认对账</Button>
          <Button v-if="canRespond && ['DRAFT', 'CONFIRMED'].includes(record.status)" size="small" type="link" danger @click="openDispute(record)">发起争议</Button>
        </div>
      </template>
    </template>
  </SupplierRecordList>

  <Modal v-model:open="drawerOpen" :footer="null" title="对账协同" width="720px">
    <div v-if="active" class="space-y-4 py-2">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div><div class="font-semibold">{{ active.reconciliation_no }}</div><div class="text-sm text-muted-foreground">订单 {{ active.po_no }} · {{ formatAmount(active.total_amount) }} {{ active.currency_code }}</div></div>
        <Tag :color="RECONCILIATION_STATUS_DICT.color(active.status)">{{ RECONCILIATION_STATUS_DICT.label(active.status) }}</Tag>
      </div>
      <Spin :spinning="sending">
        <div class="max-h-80 space-y-3 overflow-y-auto rounded-md bg-muted/30 p-3">
          <Empty v-if="messages.length === 0" description="暂无协同留言" />
          <div v-for="item in messages" :key="item.id" class="rounded-md border bg-background p-3">
            <div class="mb-1 flex justify-between gap-3 text-xs text-muted-foreground"><span>{{ item.author_type === 'SUPPLIER' ? '我方供应商' : '采购方' }}</span><span>{{ formatDateTime(item.created_at) }}</span></div>
            <div class="whitespace-pre-wrap text-sm">{{ item.message }}</div>
          </div>
        </div>
      </Spin>
      <div v-if="canMessage && !['CLOSED', 'CANCELLED'].includes(active.status)" class="flex items-end gap-2">
        <Input.TextArea v-model:value="draftMessage" :maxlength="2000" :rows="2" placeholder="输入需要和采购方确认的事项" />
        <Button type="primary" :loading="sending" :disabled="!draftMessage.trim()" @click="sendMessage">发送</Button>
      </div>
      <div v-if="canRespond && ['DRAFT', 'DISPUTED'].includes(active.status)" class="flex justify-end">
        <Button type="primary" @click="confirm(active)">确认对账</Button>
      </div>
    </div>
  </Modal>

  <Modal v-model:open="disputeOpen" :confirm-loading="sending" title="发起对账争议" @ok="submitDispute">
    <div class="py-2"><div class="mb-2 text-sm">争议原因 <span class="text-red-500">*</span></div><Input.TextArea v-model:value="reason" :maxlength="2000" :rows="4" placeholder="说明金额或对账明细的差异" /></div>
  </Modal>
</template>
