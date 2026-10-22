<script lang="ts" setup>
import type { AiApi } from '#/api/ai';

import { computed, reactive, watch } from 'vue';
import dayjs, { type Dayjs } from 'dayjs';
import { Button, DatePicker, Input, InputNumber, Select, Tag } from 'antdv-next';
import { PRIORITY_DICT } from '#/constants/dictionary';

const props = defineProps<{
  busy?: boolean;
  proposal: AiApi.ActionProposalRead;
}>();
const emit = defineEmits<{
  cancel: [];
  confirm: [];
  revise: [payload: Record<string, unknown>];
}>();

const revisionValues = reactive<Record<string, unknown>>({});
const editing = reactive({ value: false });
const canEdit = computed(() => props.proposal.requires_user_confirmation &&
  props.proposal.availability === 'AVAILABLE' && Object.keys(props.proposal.revision_values).length > 0);

const actionLabels: Record<string, string> = {
  'purchase_request.update_draft': '修改采购申请',
  'purchase_request.submit': '提交采购申请',
  'rfq.create_draft': '创建询价草稿',
  'rfq.send': '发送询价',
  'rfq.select_quote': '确认中选报价',
  'purchase_order.create_draft': '生成采购订单草稿',
};
const statusLabels: Record<AiApi.ActionProposalRead['status'], string> = {
  CANCELLED: '已取消',
  EXECUTED: '已执行',
  EXPIRED: '已过期',
  INVALIDATED: '资源已变化',
  PENDING: '待确认',
};
const availabilityLabels: Record<AiApi.ActionProposalRead['availability'], string> = {
  AVAILABLE: '',
  PERMISSION_REVOKED: '当前账号已无此动作的写入权限',
  RESOURCE_UNAVAILABLE: '关联单据当前不可访问',
};
const fieldLabels: Record<string, string> = {
  budget_amount: '预算金额',
  currency_code: '币种',
  delivery_requirements: '交付要求',
  expected_date: '期望日期',
  priority: '优先级',
  purpose: '用途',
  quote_deadline: '报价截止时间',
  requested_delivery_date: '期望交付日期',
  selected_quote: '中选报价',
  selection_reason: '中选理由',
  status: '询价状态',
  supplier: '供应商',
  items: '订单明细与条款',
  delivery_address: '收货地址',
  expected_arrival_date: '预计到货日期',
  note: '备注',
};
const dateFields = new Set(['expected_date', 'requested_delivery_date', 'quote_deadline', 'expected_arrival_date']);
const statusColor: Record<AiApi.ActionProposalRead['status'], string> = {
  CANCELLED: 'default', EXECUTED: 'success', EXPIRED: 'warning', INVALIDATED: 'error', PENDING: 'processing',
};

watch(() => props.proposal.revision_values, (values) => {
  for (const key of Object.keys(revisionValues)) delete revisionValues[key];
  Object.assign(revisionValues, values);
}, { immediate: true });

function dateValue(value: unknown): Dayjs | undefined {
  if (typeof value !== 'string' || !value) return undefined;
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed : undefined;
}

function updateDate(field: string, value?: Dayjs | Dayjs[] | null) {
  const date = Array.isArray(value) ? value[0] : value;
  revisionValues[field] = date?.isValid()
    ? (field === 'quote_deadline' ? date.format('YYYY-MM-DDTHH:mm:ss') : date.format('YYYY-MM-DD'))
    : null;
}

function updateNumber(field: string, value: number | string | null) {
  revisionValues[field] = value;
}

function startEditing() {
  Object.assign(revisionValues, props.proposal.revision_values);
  editing.value = true;
}

function saveRevision() {
  const payload = props.proposal.action_type === 'purchase_request.update_draft'
    ? { changes: { ...revisionValues } }
    : { ...revisionValues };
  emit('revise', payload);
  editing.value = false;
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '—';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

function orderTermsLines(evidence: Record<string, unknown>) {
  return Array.isArray(evidence.items)
    ? evidence.items.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    : [];
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <span class="font-medium">{{ actionLabels[proposal.action_type] || proposal.action_type }}</span>
      <Tag :color="statusColor[proposal.status]">{{ statusLabels[proposal.status] }}</Tag>
      <Tag v-if="proposal.availability !== 'AVAILABLE'" color="error">{{ availabilityLabels[proposal.availability] }}</Tag>
      <span v-if="proposal.business_reference" class="text-sm text-muted-foreground">单号 {{ proposal.business_reference }}</span>
      <RouterLink v-if="proposal.source_route" :to="proposal.source_route" class="text-sm text-primary">返回原单据 ↗</RouterLink>
    </div>

    <div class="grid grid-cols-1 gap-2 rounded-md border border-border p-3 text-sm sm:grid-cols-2">
      <div>提案编号：{{ proposal.confirmation_id }}</div>
      <div>预览版本：{{ proposal.preview_version }}</div>
      <div>风险级别：{{ proposal.risk_level }}</div>
      <div>过期时间：{{ dayjs(proposal.expires_at).format('YYYY-MM-DD HH:mm:ss') }}</div>
    </div>

    <div v-if="proposal.unavailable_reason" role="status" class="rounded-md bg-muted p-3 text-sm">
      {{ proposal.unavailable_reason }}
    </div>
    <section>
      <h3 class="mb-2 font-medium">变更差异</h3>
      <div v-if="proposal.diff.length" class="overflow-x-auto rounded-md border border-border">
        <div v-for="(item, index) in proposal.diff" :key="`${String(item.field)}-${index}`" class="grid grid-cols-[140px_minmax(0,1fr)] gap-3 border-b border-border p-3 text-sm last:border-0">
          <strong>{{ fieldLabels[String(item.field)] || String(item.field) }}</strong>
          <span class="min-w-0 break-words">{{ formatValue(item.before) }} → {{ formatValue(item.after) }}</span>
        </div>
      </div>
      <div v-else class="text-sm text-muted-foreground">没有字段差异。</div>
    </section>

    <section v-if="proposal.evidence.length">
      <h3 class="mb-2 font-medium">证据</h3>
      <ul class="list-disc space-y-1 pl-5 text-sm">
        <li v-for="(item, index) in proposal.evidence" :key="index">
          <template v-if="item.type === 'purchase_order_terms_check'">
            <div class="mb-1 text-muted-foreground">比价单 {{ formatValue(item.comparison_no) }} · 报价 {{ formatValue(item.quote_no) }} · 申请 {{ formatValue(item.request_no) }}</div>
            <div v-for="line in orderTermsLines(item)" :key="formatValue(line.line_no)" class="border-b border-border py-2 last:border-0">
              <div class="font-medium">第 {{ formatValue(line.line_no) }} 行 · {{ formatValue(line.product) }}</div>
              <div class="text-muted-foreground">数量 {{ formatValue(line.quantity) }} / 单位 {{ formatValue(line.unit_name || `#${formatValue(line.unit_id)}`) }} · 单价 {{ formatValue(line.unit_price) }} {{ formatValue(line.currency_code) }} · 税率 {{ line.tax_rate == null ? '未提供' : `${formatValue(line.tax_rate)}%` }}</div>
              <div class="text-muted-foreground">交期 {{ line.lead_days == null ? '未提供' : `${formatValue(line.lead_days)} 天` }} · 付款条件 {{ formatValue(line.payment_terms || '报价未提供') }} · 申请剩余量 {{ formatValue(line.available_request_quantity ?? '无法核对') }}</div>
              <div class="text-muted-foreground">要求到货 {{ formatValue(line.required_delivery_date || '未提供') }}</div>
            </div>
          </template>
          <span v-else>{{ formatValue(item) }}</span>
        </li>
      </ul>
    </section>

    <section v-if="proposal.warnings.length || proposal.blockers.length" class="space-y-2">
      <div v-if="proposal.warnings.length">
        <h3 class="mb-1 font-medium">提示</h3>
        <ul class="list-disc pl-5 text-sm text-amber-700"><li v-for="warning in proposal.warnings" :key="warning">{{ warning }}</li></ul>
      </div>
      <div v-if="proposal.blockers.length" role="alert">
        <h3 class="mb-1 font-medium">阻塞项</h3>
        <ul class="list-disc pl-5 text-sm text-destructive"><li v-for="blocker in proposal.blockers" :key="blocker">{{ blocker }}</li></ul>
      </div>
    </section>

    <section v-if="editing.value" class="space-y-3 border-t border-border pt-4">
      <h3 class="font-medium">修改提案字段</h3>
      <div v-for="(value, field) in revisionValues" :key="field" class="space-y-1">
        <div class="text-sm text-muted-foreground">{{ fieldLabels[field] || field }}</div>
        <Select v-if="field === 'priority'" v-model:value="revisionValues[field]" :aria-label="fieldLabels[field]" :options="PRIORITY_DICT.options()" class="w-full" />
        <DatePicker v-else-if="dateFields.has(field)" :aria-label="fieldLabels[field]" :show-time="field === 'quote_deadline'" :value="dateValue(value)" class="w-full" @change="updateDate(field, $event)" />
        <InputNumber v-else-if="field === 'budget_amount'" :aria-label="fieldLabels[field]" :value="typeof value === 'number' || typeof value === 'string' ? Number(value) : null" :min="0" class="w-full" @change="updateNumber(field, $event)" />
        <Input.TextArea v-else-if="['purpose', 'delivery_requirements', 'selection_reason', 'delivery_address', 'note'].includes(field)" v-model:value="revisionValues[field]" :aria-label="fieldLabels[field]" :rows="2" :maxlength="field === 'selection_reason' ? 2000 : field === 'delivery_address' ? 500 : 1000" />
        <Input v-else v-model:value="revisionValues[field]" :aria-label="fieldLabels[field] || field" />
      </div>
    </section>

    <div class="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
      <template v-if="editing.value">
        <Button :disabled="busy" @click="editing.value = false">返回</Button>
        <Button type="primary" :loading="busy" :disabled="busy" @click="saveRevision">保存新预览</Button>
      </template>
      <template v-else>
        <Button v-if="proposal.requires_user_confirmation" danger :disabled="busy" @click="emit('cancel')">取消提案</Button>
        <Button v-if="canEdit" :disabled="busy" @click="startEditing">修改</Button>
        <Button v-if="proposal.requires_user_confirmation" type="primary" :loading="busy" :disabled="busy" @click="emit('confirm')">确认执行</Button>
      </template>
    </div>
  </div>
</template>
