<script lang="ts" setup>
import type { DeliveryFollowup } from '#/api/delivery-followups';
import type { Dayjs } from 'dayjs';

import { ref } from 'vue';
import { Button, DatePicker, Empty, Input, message, Modal, Table, Tag } from 'antdv-next';
import { getDeliveryFollowupsApi, replyDeliveryFollowupApi } from '#/api/delivery-followups';
import { formatDate, formatDateTime } from '#/utils/format';

const props = defineProps<{ supplierMode?: boolean }>();
const emit = defineEmits<{ changed: [] }>();
const visible = ref(false);
const loading = ref(false);
const saving = ref(false);
const error = ref(false);
const orderId = ref<number>();
const rows = ref<DeliveryFollowup[]>([]);
const total = ref(0);
const page = ref(1);
const replyOpen = ref(false);
const replying = ref<DeliveryFollowup>();
const note = ref('');
const expectedDate = ref<Dayjs>();
let requestKey = '';
let generation = 0;
const columns = [
  { key: 'message', title: '催办内容', width: 310 },
  { key: 'sent_at', title: '发送时间', width: 170 },
  { key: 'status', title: '状态', width: 100 },
  { key: 'reply', title: '供应商回复', width: 260 },
  { key: '__action', title: '操作', width: 100 },
];

async function load() {
  if (!orderId.value) return;
  const current = ++generation;
  loading.value = true;
  error.value = false;
  rows.value = [];
  total.value = 0;
  try {
    const result = await getDeliveryFollowupsApi(orderId.value, Boolean(props.supplierMode), page.value);
    if (current !== generation) return;
    rows.value = result.items;
    total.value = result.total;
  } catch {
    if (current === generation) error.value = true;
  } finally { if (current === generation) loading.value = false; }
}
async function open(id: number) {
  if (saving.value) return;
  orderId.value = id;
  page.value = 1;
  replyOpen.value = false;
  replying.value = undefined;
  visible.value = true;
  await load();
}
function startReply(row: DeliveryFollowup) {
  if (!row.can_reply || saving.value) return;
  replying.value = row;
  note.value = '';
  expectedDate.value = undefined;
  requestKey = crypto.randomUUID();
  replyOpen.value = true;
}
async function saveReply() {
  if (!orderId.value || !replying.value || saving.value) return;
  if (!note.value.trim()) { message.warning('请填写回复说明'); return; }
  saving.value = true;
  try {
    await replyDeliveryFollowupApi(orderId.value, replying.value.id, {
      request_key: requestKey, message: note.value.trim(), expected_date: expectedDate.value?.format('YYYY-MM-DD'),
    });
    replyOpen.value = false;
    message.success('催办回复已提交');
    emit('changed');
  } catch {
    // 请求结果未知时先刷新事实，保留请求键用于同一内容的安全重试。
    message.warning('回复未确认成功，请刷新状态后核对');
  } finally {
    saving.value = false;
    await load();
    const current = rows.value.find((row) => row.id === replying.value?.id);
    if (!current?.can_reply) replyOpen.value = false;
  }
}
defineExpose({ open });
</script>

<template>
  <Modal v-model:open="visible" title="交期催办记录" :footer="null" width="960px" :closable="!saving" :mask-closable="!saving" :keyboard="!saving">
    <div class="space-y-4 py-2">
      <div class="flex items-center justify-between gap-3">
        <span class="text-sm text-muted-foreground">{{ props.supplierMode ? '查看采购催办并反馈交付安排；每条催办可正式回复一次。' : '已发送的催办及供应商正式回复。' }}</span>
        <Button :loading="loading" :disabled="saving" @click="load">刷新</Button>
      </div>
      <div v-if="error" role="alert" class="text-sm text-muted-foreground">催办记录读取失败，请核对权限与订单状态后刷新。</div>
      <Empty v-else-if="!loading && !rows.length" description="暂无催办记录" />
      <Table v-else :loading="loading" :columns="props.supplierMode ? columns : columns.filter((column) => column.key !== '__action')" :data-source="rows" row-key="id" :scroll="{ x: 840 }" :pagination="{ current: page, pageSize: 20, total, onChange: (value: number) => { page = value; load(); } }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'message'"><div class="whitespace-pre-wrap break-words">{{ record.message }}</div></template>
          <template v-else-if="column.key === 'sent_at'">{{ formatDateTime(record.sent_at) }}</template>
          <template v-else-if="column.key === 'status'"><Tag :color="record.status === 'REPLIED' ? 'success' : 'warning'">{{ record.status === 'REPLIED' ? '已回复' : '待回复' }}</Tag></template>
          <template v-else-if="column.key === 'reply'">
            <div class="whitespace-pre-wrap break-words">{{ record.reply_message || '—' }}</div>
            <div v-if="record.reply_expected_date" class="mt-1 text-sm text-muted-foreground">预计到货：{{ formatDate(record.reply_expected_date) }}</div>
            <div v-if="record.replied_at" class="mt-1 text-sm text-muted-foreground">{{ formatDateTime(record.replied_at) }}</div>
          </template>
          <template v-else-if="column.key === '__action'"><Button v-if="record.can_reply" type="link" :disabled="saving" @click="startReply(record)">回复催办</Button></template>
        </template>
      </Table>
    </div>
  </Modal>
  <Modal v-model:open="replyOpen" title="回复交期催办" :confirm-loading="saving" :closable="!saving" :mask-closable="!saving" :keyboard="!saving" @ok="saveReply">
    <div v-if="replying" class="space-y-4 py-2">
      <div><div class="mb-1 text-sm text-muted-foreground">采购订单</div><div class="font-medium">{{ replying.po_no }}</div></div>
      <div><div class="mb-1 text-sm text-muted-foreground">回复说明</div><Input.TextArea v-model:value="note" :disabled="saving" :maxlength="1000" :rows="3" placeholder="填写交付安排或延期原因" /></div>
      <div><div class="mb-1 text-sm text-muted-foreground">预计到货日期（可选）</div><DatePicker v-model:value="expectedDate" :disabled="saving" class="w-full" /><div class="mt-1 text-sm text-muted-foreground">填写后将同时更新订单及未收明细的预计交期；留空仅保存回复。</div></div>
    </div>
  </Modal>
</template>
