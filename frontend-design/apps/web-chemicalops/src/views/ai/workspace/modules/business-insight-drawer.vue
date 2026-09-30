<script lang="ts" setup>
import type { BusinessInsightApi } from '#/api';

import { ref } from 'vue';
import { useRouter } from 'vue-router';

import { useVbenDrawer } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { useUserStore } from '@vben/stores';

import { Alert, Button, Empty, Input, Select, Spin, Tag, message } from 'antdv-next';

import { createBatchChecksApi, createBatchRecallReportApi, createFinanceChecksApi, decideExceptionActionApi, getBatchAssigneesApi, getBatchCheckEventsApi, getBatchChecksApi, getBatchRecallReportsApi, getBusinessInsightApi, getExceptionDecisionApi, getExceptionDecisionEventsApi, getFinanceAssigneesApi, getFinanceCheckEventsApi, getFinanceChecksApi, getInsightSnapshotsApi, getRecallReportOwnersApi, saveInsightSnapshotApi, updateBatchCheckApi, updateFinanceCheckApi, updateRecallReportWorkflowApi } from '#/api';

const emit = defineEmits(['changed']);
const router = useRouter();
const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();
const result = ref<BusinessInsightApi.Insight>();
const liveResult = ref<BusinessInsightApi.Insight>();
const loading = ref(false);
const loadError = ref(false);
const targetKind = ref('');
const targetId = ref(0);
const snapshots = ref<BusinessInsightApi.Snapshot[]>([]);
const selectedSnapshotId = ref<null | number>(null);
const checks = ref<BusinessInsightApi.CheckItem[]>([]);
const assignees = ref<Record<number, { id: number; name: string }[]>>({});
const findings = ref<Record<number, string>>({});
const events = ref<Record<number, BusinessInsightApi.CheckEvent[]>>({});
const busy = ref(false);
const exceptionDecision = ref<BusinessInsightApi.ExceptionDecision | null>(null);
const exceptionEvents = ref<BusinessInsightApi.ExceptionDecisionEvent[]>([]);
const decisionReason = ref('');
const financeChecks = ref<BusinessInsightApi.FinanceCheck[]>([]);
const financeAssignees = ref<{ id: number; name: string }[]>([]);
const recallReports = ref<BusinessInsightApi.RecallReportSnapshot[]>([]);
const selectedRecallReport = ref<BusinessInsightApi.RecallReportSnapshot | null>(null);
const recallOwners = ref<{ id: number; name: string }[]>([]);
const recallConclusion = ref('');
const recallReviewReason = ref('');
const recallOwnersLoading = ref(false);

const [Drawer, drawerApi] = useVbenDrawer<{ kind: string; objectId: number }>({
  footer: false,
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    const target = drawerApi.getData();
    result.value = undefined;
    loadError.value = false;
    if (!target) return;
    targetKind.value = target.kind;
    targetId.value = target.objectId;
    snapshots.value = [];
    selectedSnapshotId.value = null;
    checks.value = [];
    assignees.value = {};
    events.value = {};
    exceptionDecision.value = null;
    exceptionEvents.value = [];
    decisionReason.value = '';
    financeChecks.value = [];
    financeAssignees.value = [];
    recallReports.value = [];
    selectedRecallReport.value = null;
    recallOwners.value = [];
    recallConclusion.value = '';
    recallReviewReason.value = '';
    findings.value = {};
    loading.value = true;
    try {
      result.value = await getBusinessInsightApi(target.kind, target.objectId);
      liveResult.value = result.value;
      snapshots.value = await getInsightSnapshotsApi(target.kind, target.objectId);
      if (target.kind === 'batch-impact') {
        [checks.value, recallReports.value] = await Promise.all([getBatchChecksApi(target.objectId), getBatchRecallReportsApi(target.objectId)]);
        findings.value = Object.fromEntries(checks.value.map((item) => [item.id, item.finding ?? '']));
        if (hasAccessByCodes(['warehouse.inventory.write'])) assignees.value = await getBatchAssigneesApi(target.objectId);
      }
      if (target.kind === 'exception-action') {
        [exceptionDecision.value, exceptionEvents.value] = await Promise.all([
          getExceptionDecisionApi(target.objectId),
          getExceptionDecisionEventsApi(target.objectId),
        ]);
      }
      if (target.kind === 'finance-difference') {
        financeChecks.value = await getFinanceChecksApi(target.objectId);
        findings.value = Object.fromEntries(financeChecks.value.map((item) => [item.id, item.finding ?? '']));
        if (hasAccessByCodes(['finance.reconciliations.write'])) financeAssignees.value = await getFinanceAssigneesApi(target.objectId);
      }
    } catch {
      loadError.value = true;
    } finally {
      loading.value = false;
    }
  },
});

async function saveSnapshot() {
  busy.value = true;
  try {
    const snapshot = await saveInsightSnapshotApi(targetKind.value, targetId.value);
    snapshots.value.unshift(snapshot);
    message.success('分析结果已保存');
  } catch {
    message.error('保存失败，请检查权限或稍后重试');
  } finally {
    busy.value = false;
  }
}

async function createRecallReport() {
  busy.value = true;
  try {
    const report = await createBatchRecallReportApi(targetId.value);
    recallReports.value.unshift(report);
    await selectRecallReport(report);
    message.success('召回演练报告已保存');
  } catch {
    message.error('生成报告失败，请检查批次和库存权限');
  } finally {
    busy.value = false;
  }
}

async function selectRecallReport(report: BusinessInsightApi.RecallReportSnapshot) {
  selectedRecallReport.value = report;
  recallConclusion.value = report.workflow.conclusion ?? '';
  recallReviewReason.value = '';
  recallOwners.value = [];
  if (!hasAccessByCodes(['warehouse.inventory.write']) || report.workflow.status === 'COMPLETED') return;
  recallOwnersLoading.value = true;
  try {
    const owners = await getRecallReportOwnersApi(targetId.value, report.id);
    if (selectedRecallReport.value?.id === report.id) recallOwners.value = owners;
  } catch {
    message.error('可指派的负责人暂时无法加载');
  } finally {
    recallOwnersLoading.value = false;
  }
}

async function changeRecallWorkflow(action: 'ASSIGN' | 'COMPLETE' | 'RETURN' | 'SUBMIT', ownerId?: number) {
  const report = selectedRecallReport.value;
  if (!report) return;
  if (action === 'SUBMIT' && !recallConclusion.value.trim()) {
    message.warning('请填写最终核查结论');
    return;
  }
  if ((action === 'COMPLETE' || action === 'RETURN') && !recallReviewReason.value.trim()) {
    message.warning('请填写复核意见');
    return;
  }
  busy.value = true;
  try {
    const updated = await updateRecallReportWorkflowApi(targetId.value, report.id, { action, owner_id: ownerId, conclusion: recallConclusion.value.trim(), reason: recallReviewReason.value.trim() });
    recallReports.value = recallReports.value.map((row) => row.id === updated.id ? updated : row);
    selectedRecallReport.value = updated;
    recallReviewReason.value = '';
    message.success(action === 'COMPLETE' ? '演练报告已确认完成' : action === 'RETURN' ? '报告已退回负责人' : action === 'SUBMIT' ? '报告已提交，等待另一人复核' : '负责人已更新');
  } catch {
    message.error('操作未完成，请核对负责人、复核权限及报告是否需要重新生成');
  } finally {
    busy.value = false;
  }
}

function canAssignRecall(report: BusinessInsightApi.RecallReportSnapshot) {
  const userId = Number(userStore.userInfo?.userId);
  return hasAccessByCodes(['warehouse.inventory.write']) && ['DRAFT', 'RETURNED'].includes(report.workflow.status) && (report.created_by === userId || report.workflow.owner_id === userId);
}

function canSubmitRecall(report: BusinessInsightApi.RecallReportSnapshot) {
  return hasAccessByCodes(['warehouse.inventory.write']) && ['DRAFT', 'RETURNED'].includes(report.workflow.status) && report.workflow.owner_id === Number(userStore.userInfo?.userId);
}

function canReviewRecall(report: BusinessInsightApi.RecallReportSnapshot) {
  const userId = Number(userStore.userInfo?.userId);
  return hasAccessByCodes(['warehouse.inventory.write']) && report.workflow.status === 'SUBMITTED' && report.workflow.owner_id !== userId && report.workflow.submitted_by !== userId;
}

async function startChecks() {
  busy.value = true;
  try {
    const snapshot = await saveInsightSnapshotApi(targetKind.value, targetId.value);
    snapshots.value.unshift(snapshot);
    checks.value = await createBatchChecksApi(targetId.value, snapshot.id);
    findings.value = Object.fromEntries(checks.value.map((item) => [item.id, item.finding ?? '']));
    assignees.value = await getBatchAssigneesApi(targetId.value);
    message.success('核查清单已建立');
  } catch {
    message.error('建立核查清单失败，请检查库存操作权限');
  } finally {
    busy.value = false;
  }
}

async function changeCheck(item: BusinessInsightApi.CheckItem, data: { assignee_id?: null | number; finding?: string; status?: string }) {
  busy.value = true;
  try {
    const updated = await updateBatchCheckApi(targetId.value, item.id, data);
    checks.value = checks.value.map((row) => row.id === item.id ? updated : row);
    if (events.value[item.id]) events.value[item.id] = await getBatchCheckEventsApi(targetId.value, item.id);
    message.success('核查记录已更新');
  } catch {
    message.error('更新失败，请核对负责人、处理说明和复核条件');
  } finally {
    busy.value = false;
  }
}

async function showEvents(item: BusinessInsightApi.CheckItem) {
  try {
    events.value[item.id] = await getBatchCheckEventsApi(targetId.value, item.id);
  } catch {
    message.error('处理记录暂时无法加载');
  }
}

async function decideException(decision: 'ADOPTED' | 'REJECTED') {
  if (!decisionReason.value.trim()) {
    message.warning('请填写采纳或驳回原因');
    return;
  }
  busy.value = true;
  try {
    exceptionDecision.value = await decideExceptionActionApi(targetId.value, decision, decisionReason.value.trim());
    exceptionEvents.value = await getExceptionDecisionEventsApi(targetId.value);
    decisionReason.value = '';
    message.success(decision === 'ADOPTED' ? '已建立关联处理任务' : '已记录驳回原因');
    emit('changed');
  } catch {
    message.error('处理建议失败，请检查异常负责人、状态和关联任务');
  } finally {
    busy.value = false;
  }
}

async function startFinanceChecks() {
  busy.value = true;
  try {
    const snapshot = await saveInsightSnapshotApi(targetKind.value, targetId.value);
    snapshots.value.unshift(snapshot);
    financeChecks.value = await createFinanceChecksApi(targetId.value, snapshot.id);
    findings.value = Object.fromEntries(financeChecks.value.map((item) => [item.id, item.finding ?? '']));
    financeAssignees.value = await getFinanceAssigneesApi(targetId.value);
    message.success('财务核查清单已建立');
  } catch {
    message.error('建立财务核查清单失败，请检查订单和财务权限');
  } finally {
    busy.value = false;
  }
}

async function changeFinanceCheck(item: BusinessInsightApi.FinanceCheck, data: { assignee_id?: null | number; finding?: string; status?: string }) {
  busy.value = true;
  try {
    const updated = await updateFinanceCheckApi(targetId.value, item.id, data);
    financeChecks.value = financeChecks.value.map((row) => row.id === item.id ? updated : row);
    if (events.value[item.id]) events.value[item.id] = await getFinanceCheckEventsApi(targetId.value, item.id);
    message.success('财务核查记录已更新');
  } catch {
    message.error('更新失败，请核对负责人、处理说明和复核条件');
  } finally {
    busy.value = false;
  }
}

async function showFinanceEvents(item: BusinessInsightApi.FinanceCheck) {
  try {
    events.value[item.id] = await getFinanceCheckEventsApi(targetId.value, item.id);
  } catch {
    message.error('处理记录暂时无法加载');
  }
}

function checkEvidence(item: BusinessInsightApi.CheckItem) {
  if (item.balance_id === null) return undefined;
  return liveResult.value?.evidence.find((evidence) => evidence.source === `库存余额 #${item.balance_id}`);
}

function showSnapshot(snapshot?: BusinessInsightApi.Snapshot) {
  selectedSnapshotId.value = snapshot?.id ?? null;
  result.value = snapshot?.result_json ?? liveResult.value;
}

/** 从分析结果跳回对应业务页面继续核实来源。 */
function openSource(path?: null | string) {
  if (path) void router.push(path);
}

/** 打开指定业务对象的分析抽屉。 */
function open(kind: string, objectId: number) {
  drawerApi.setData({ kind, objectId }).open();
}

function downloadCsv(filename: string, rows: string[][]) {
  const cell = (value: string) => {
    const safe = /^[=+\-@]/.test(value) ? `'${value}` : value;
    return `"${safe.replaceAll('"', '""')}"`;
  };
  const csv = `\uFEFF${rows.map((row) => row.map(cell).join(',')).join('\r\n')}`;
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** 将证据、建议和范围说明导出为本地 CSV 核查清单。 */
function exportChecklist() {
  if (!result.value) return;
  const rows = [
    ['类别', '内容', '来源'],
    ...result.value.evidence.map((item) => ['核查依据', `${item.label}：${item.value}`, item.source]),
    ...result.value.suggestions.map((item) => ['建议核查', item, '']),
    ...result.value.limitations.map((item) => ['数据范围', item, '']),
    ...(selectedSnapshotId.value === null ? checks.value.map((item) => ['批次核查', `${item.target_label}；状态 ${item.status}；负责人 #${item.assignee_id ?? '未指定'}；处理说明 ${item.finding ?? ''}`, `核查项 #${item.id}`]) : []),
    ...(selectedSnapshotId.value === null ? financeChecks.value.map((item) => ['财务核查', `${item.target_label}；状态 ${item.status}；负责人 #${item.assignee_id ?? '未指定'}；处理说明 ${item.finding ?? ''}`, `核查项 #${item.id}`]) : []),
  ];
  downloadCsv(`${result.value.kind}-核查清单.csv`, rows);
}

function exportRecallReport() {
  const saved = selectedRecallReport.value;
  if (!saved) return;
  const report = saved.result_json;
  downloadCsv(`批次-${report.batch_no}-召回演练-${saved.id}.csv`, [
    ['类别', '对象', '数量/状态', '来源或说明'],
    ['报告', report.batch_no, report.status, `生成时间 ${saved.created_at}；可见流水 ${report.visible_transaction_count}`],
    ['完成确认', recallWorkflowStatus(saved.workflow.status), saved.workflow.owner_name ?? '未指定负责人', `提交人 ${saved.workflow.submitted_by_name ?? '未提交'}；提交时间 ${saved.workflow.submitted_at ?? ''}；复核人 ${saved.workflow.reviewed_by_name ?? '未复核'}；完成时间 ${saved.workflow.completed_at ?? ''}`],
    ['最终结论', saved.workflow.conclusion ?? '', '', saved.workflow.review_reason ?? ''],
    ...report.slots.map((row) => ['库位数量', `仓库 #${row.warehouse_id} / 库位 #${row.location_id} / 单位 #${row.unit_id}`, `余额 ${row.quantity ?? '缺失'}；流水净额 ${row.movement_net}；差额 ${row.difference ?? '无法判定'}`, `${row.status}；核查 ${row.check_status}`]),
    ...report.outflows.map((row) => ['出库去向', row.transaction_no, `${row.quantity} / 单位 #${row.unit_id}；${recallCheckStatus(row.check_status)}`, `${sourceTypeLabel(row.source_type)} #${row.source_id ?? '缺失'}；${row.source_reason ?? (row.source_found ? '来源单据已找到' : '来源缺失')}；${row.finding ?? ''}`]),
    ...(report.source_matches ?? []).map((row) => ['来源明细匹配', row.transaction_no, `${row.quantity} / 单位 #${row.unit_id}；明细执行量 ${row.expected_quantity ?? '无法确认'}；${sourceMatchStatus(row.status)}`, `${sourceTypeLabel(row.source_type)} #${row.source_id ?? '缺失'} / 明细 #${row.item_id ?? '未定位'}；${row.reason}`]),
    ...(report.transfer_pairs ?? []).map((row) => ['调拨两端核对', `申请 #${row.request_id} / 明细 #${row.item_id}`, `出库 ${row.outbound_quantity ?? '超出权限'}；入库 ${row.inbound_quantity ?? '超出权限'} / 单位 #${row.unit_id}`, `${transferPairStatus(row.status)}；${row.review_status === 'VERIFIED' ? '两端已复核' : '两端复核未完成'}；出库流水 ${row.outbound_ids.join('、')}；入库流水 ${row.inbound_ids.join('、')}`]),
    ...report.transfer_differences.map((row) => ['调拨差异', `申请 #${row.request_id}`, `净额 ${row.net} / 单位 #${row.unit_id}`, '需核对调拨两端']),
    ...report.limitations.map((item) => ['范围与结论', item, '', '']),
    ...(report.checks ?? []).map((item) => ['生成时核查记录', `核查项 #${item.id}`, recallCheckStatus(item.status), `负责人 #${item.assignee_id ?? '未指定'}；核查人 #${item.checked_by ?? '未核查'}；复核人 #${item.reviewed_by ?? '未复核'}；${item.finding ?? ''}`]),
    ...saved.workflow.events.map((event) => ['报告确认记录', event.created_at, `${recallWorkflowAction(event.action)} · ${event.actor_name}`, `${event.conclusion ?? ''}；${event.review_reason ?? ''}`]),
  ]);
}

function recallSlotStatus(status: string) {
  const labels: Record<string, string> = { MATCHED: '数量相符', DIFFERENCE: '数量有差异', UNKNOWN: '方向待核实', MISSING_BALANCE: '缺少余额记录' };
  return labels[status] ?? status;
}

function recallCheckStatus(status: string) {
  const labels: Record<string, string> = { NOT_CREATED: '未建核查', OPEN: '待核查', CHECKED: '待复核', NEEDS_ACTION: '需处理', VERIFIED: '已复核' };
  return labels[status] ?? status;
}

function sourceTypeLabel(type: null | string) {
  const labels: Record<string, string> = { DELIVERY: '到货单', ISSUE_REQUEST: '领用单', INVENTORY_RETURN: '退货单', INVENTORY_STOCKTAKE: '盘点单', INVENTORY_TRANSFER: '调拨单' };
  return labels[type ?? ''] ?? '未知来源';
}

function sourceMatchStatus(status: string) {
  const labels: Record<string, string> = { MATCHED: '明细相符', MISSING: '来源缺失', CONFLICT: '明细冲突', AMBIGUOUS: '无法唯一匹配', DUPLICATE: '重复流水' };
  return labels[status] ?? status;
}

function transferPairStatus(status: string) {
  const labels: Record<string, string> = { MATCHED: '两端相符', MISSING_SIDE: '缺少一端流水', DUPLICATE: '存在重复流水', CONFLICT: '两端明细冲突', OUT_OF_SCOPE: '另一端超出权限范围' };
  return labels[status] ?? status;
}

function recallWorkflowStatus(status: string) {
  const labels: Record<string, string> = { DRAFT: '待提交', SUBMITTED: '待最终复核', RETURNED: '已退回', COMPLETED: '演练已完成' };
  return labels[status] ?? status;
}

function recallWorkflowAction(action: string) {
  const labels: Record<string, string> = { ASSIGN: '指派负责人', SUBMIT: '提交结论', RETURN: '退回修改', COMPLETE: '确认完成' };
  return labels[action] ?? action;
}

defineExpose({ open });
</script>

<template>
  <Drawer :title="result?.title ?? '业务分析'" class="w-[760px] max-w-[100vw]">
    <Spin :spinning="loading">
      <Empty v-if="loadError" description="分析暂时无法加载，请检查权限或稍后重试" />
      <Empty v-else-if="!result && !loading" description="没有可展示的分析结果" />
      <div v-else-if="result" class="space-y-4 pb-6">
        <Alert show-icon type="info" :message="result.summary" :description="`适用人员：${result.audience}；分析证据供人工核查，正式业务处理仍在原单据完成。`" />
        <div class="flex justify-end">
          <Button class="mr-2" :loading="busy" @click="saveSnapshot">保存本次分析</Button>
          <Button size="small" @click="exportChecklist">导出核查清单</Button>
        </div>

        <section v-if="snapshots.length">
          <h3 class="mb-2 font-medium">历史分析</h3>
          <div class="flex flex-wrap gap-2">
            <Button size="small" :type="selectedSnapshotId === null ? 'primary' : 'default'" @click="showSnapshot()">查看当前</Button>
            <Button v-for="snapshot in snapshots" :key="snapshot.id" size="small" :type="selectedSnapshotId === snapshot.id ? 'primary' : 'default'" @click="showSnapshot(snapshot)">
              {{ new Date(snapshot.created_at).toLocaleString() }}
            </Button>
          </div>
          <div v-if="selectedSnapshotId !== null" class="mt-2 text-xs text-muted-foreground">正在查看保存时的分析证据；下方核查清单展示当前处理状态。</div>
        </section>

        <section v-if="targetKind === 'batch-impact'" class="space-y-3">
          <div class="flex items-center justify-between">
            <h3 class="font-medium">批次核查清单</h3>
            <Button v-if="hasAccessByCodes(['warehouse.inventory.write'])" :loading="busy" @click="startChecks">{{ checks.length ? '补充新记录' : '建立核查清单' }}</Button>
          </div>
          <div v-for="item in checks" :key="item.id" class="space-y-2 rounded-lg border p-3 text-sm">
            <div class="flex items-center justify-between">
              <span>{{ checkEvidence(item)?.label ?? item.target_label }}</span>
              <Tag :color="item.status === 'VERIFIED' ? 'green' : item.status === 'NEEDS_ACTION' ? 'red' : 'blue'">{{ { OPEN: '待核查', CHECKED: '待复核', NEEDS_ACTION: '需处理', VERIFIED: '已复核' }[item.status] ?? item.status }}</Tag>
            </div>
            <div class="text-muted-foreground">{{ checkEvidence(item)?.value ?? item.target_label }} · 来源快照 #{{ item.snapshot_id }}</div>
            <Select
              v-if="hasAccessByCodes(['warehouse.inventory.write'])"
              :value="item.assignee_id ?? undefined"
              :options="(assignees[item.id] ?? []).map((person) => ({ label: person.name, value: person.id }))"
              allow-clear
              class="w-full"
              placeholder="指派核查人员"
              :disabled="busy"
              @change="(value) => changeCheck(item, { assignee_id: typeof value === 'number' ? value : null })"
            />
            <Input.TextArea v-if="hasAccessByCodes(['warehouse.inventory.write'])" v-model:value="findings[item.id]" :rows="2" :maxlength="2000" placeholder="记录核查发现和来源" />
            <div v-else-if="item.finding" class="whitespace-pre-wrap text-muted-foreground">{{ item.finding }}</div>
            <div v-if="hasAccessByCodes(['warehouse.inventory.write'])" class="flex flex-wrap gap-2">
              <Button v-if="item.status === 'OPEN' || item.status === 'NEEDS_ACTION'" size="small" :disabled="busy" @click="changeCheck(item, { status: 'CHECKED', finding: findings[item.id] })">提交核查</Button>
              <Button v-if="item.status === 'OPEN' || item.status === 'CHECKED'" size="small" :disabled="busy" @click="changeCheck(item, { status: 'NEEDS_ACTION', finding: findings[item.id] })">标记需处理</Button>
              <Button v-if="item.status === 'CHECKED'" size="small" type="primary" :disabled="busy" @click="changeCheck(item, { status: 'VERIFIED', finding: findings[item.id] })">复核通过</Button>
              <Button v-if="item.status !== 'OPEN'" size="small" :disabled="busy" @click="changeCheck(item, { status: 'OPEN', finding: findings[item.id] })">重新核查</Button>
            </div>
            <div v-if="item.checked_at" class="text-xs text-muted-foreground">核查人 #{{ item.checked_by }} · {{ item.checked_at }}<span v-if="item.reviewed_at">；复核人 #{{ item.reviewed_by }} · {{ item.reviewed_at }}</span></div>
            <Button size="small" type="link" @click="showEvents(item)">查看处理记录</Button>
            <div v-for="event in events[item.id] ?? []" :key="event.id" class="border-t pt-2 text-xs text-muted-foreground">
              {{ event.created_at }} · 操作人 #{{ event.actor_id }} · {{ event.status }} · {{ event.finding || '无说明' }}
            </div>
          </div>
          <div class="space-y-3 border-t pt-4">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <h3 class="font-medium">召回演练报告</h3>
              <Button :loading="busy" @click="createRecallReport">生成并保存报告</Button>
            </div>
            <div v-if="recallReports.length" class="flex flex-wrap gap-2">
              <Button v-for="report in recallReports" :key="report.id" size="small" :disabled="busy" :type="selectedRecallReport?.id === report.id ? 'primary' : 'default'" @click="selectRecallReport(report)">
                {{ new Date(report.created_at).toLocaleString() }}
              </Button>
            </div>
            <div v-if="selectedRecallReport" class="space-y-3 rounded-lg border p-3 text-sm">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div>批次 {{ selectedRecallReport.result_json.batch_no }} · <Tag :color="selectedRecallReport.workflow.status === 'COMPLETED' ? 'green' : 'gold'">{{ selectedRecallReport.workflow.status === 'COMPLETED' ? '演练已完成' : selectedRecallReport.result_json.status === 'READY_FOR_REVIEW' ? '待人工确认' : '核查未完成' }}</Tag></div>
                <Button size="small" @click="exportRecallReport">导出报告 CSV</Button>
              </div>
              <div class="space-y-2 border-t pt-3">
                <div class="flex flex-wrap items-center justify-between gap-2"><h4 class="font-medium">完成确认</h4><span>{{ recallWorkflowStatus(selectedRecallReport.workflow.status) }}</span></div>
                <div class="text-muted-foreground">负责人：{{ selectedRecallReport.workflow.owner_name ?? '未指定' }}</div>
                <Select v-if="canAssignRecall(selectedRecallReport)" :value="selectedRecallReport.workflow.owner_id ?? undefined" :options="recallOwners.map((person) => ({ label: person.name, value: person.id }))" class="w-full" placeholder="指定报告负责人" :loading="recallOwnersLoading" :disabled="busy || recallOwnersLoading" @change="(value) => { if (typeof value === 'number') changeRecallWorkflow('ASSIGN', value); }" />
                <div v-if="selectedRecallReport.result_json.version !== 2" class="text-muted-foreground">此报告未保存完整确认依据，请重新生成后提交。</div>
                <div v-else-if="selectedRecallReport.result_json.status !== 'READY_FOR_REVIEW'" class="text-muted-foreground">请先处理下方差异并完成核查复核，再生成报告提交。</div>
                <template v-if="canSubmitRecall(selectedRecallReport)">
                  <label class="block text-sm" for="recall-conclusion">最终核查结论</label>
                  <Input.TextArea id="recall-conclusion" v-model:value="recallConclusion" :rows="3" :maxlength="2000" :disabled="busy" placeholder="说明影响范围、数量核对结果、处置结论及系统外范围" />
                  <Button type="primary" :loading="busy" :disabled="selectedRecallReport.result_json.version !== 2 || selectedRecallReport.result_json.status !== 'READY_FOR_REVIEW'" @click="changeRecallWorkflow('SUBMIT')">提交给另一人复核</Button>
                </template>
                <div v-else-if="selectedRecallReport.workflow.conclusion" class="whitespace-pre-wrap break-words">最终结论：{{ selectedRecallReport.workflow.conclusion }}</div>
                <div v-if="selectedRecallReport.workflow.submitted_at" class="text-xs text-muted-foreground">提交人：{{ selectedRecallReport.workflow.submitted_by_name }} · {{ selectedRecallReport.workflow.submitted_at }}</div>
                <template v-if="canReviewRecall(selectedRecallReport)">
                  <label class="block text-sm" for="recall-review-reason">最终复核意见</label>
                  <Input.TextArea id="recall-review-reason" v-model:value="recallReviewReason" :rows="2" :maxlength="2000" :disabled="busy" placeholder="记录复核依据；退回时说明需要补充的内容" />
                  <div class="flex flex-wrap gap-2"><Button type="primary" :loading="busy" @click="changeRecallWorkflow('COMPLETE')">复核并确认演练完成</Button><Button :disabled="busy" @click="changeRecallWorkflow('RETURN')">退回负责人</Button></div>
                </template>
                <div v-if="selectedRecallReport.workflow.review_reason" class="whitespace-pre-wrap break-words">复核意见：{{ selectedRecallReport.workflow.review_reason }}</div>
                <div v-if="selectedRecallReport.workflow.reviewed_at" class="text-xs text-muted-foreground">复核人：{{ selectedRecallReport.workflow.reviewed_by_name }} · {{ selectedRecallReport.workflow.reviewed_at }}</div>
                <div v-if="selectedRecallReport.workflow.completed_at" class="text-sm">演练完成时间：{{ selectedRecallReport.workflow.completed_at }}</div>
                <details v-if="selectedRecallReport.workflow.events.length" class="text-xs text-muted-foreground">
                  <summary class="cursor-pointer py-1">查看确认记录（{{ selectedRecallReport.workflow.events.length }}）</summary>
                  <div v-for="event in selectedRecallReport.workflow.events" :key="event.id" class="mt-2 border-t pt-2">{{ event.created_at }} · {{ event.actor_name }} · {{ recallWorkflowAction(event.action) }}<div class="mt-1 whitespace-pre-wrap break-words">{{ event.conclusion }} {{ event.review_reason }}</div></div>
                </details>
              </div>
              <div class="text-muted-foreground">可见流水 {{ selectedRecallReport.result_json.visible_transaction_count }} 条 · 来源缺失 {{ selectedRecallReport.result_json.missing_source_count }} 条 · 明细冲突 {{ selectedRecallReport.result_json.conflict_source_count === undefined ? '未评估' : `${selectedRecallReport.result_json.conflict_source_count} 条` }} · 未复核 {{ selectedRecallReport.result_json.open_check_count }} 项 · 未建核查 {{ selectedRecallReport.result_json.missing_check_count }} 项</div>
              <div class="font-medium">库位数量对账</div>
              <div v-for="row in selectedRecallReport.result_json.slots" :key="`${row.warehouse_id}-${row.location_id}-${row.unit_id}`" class="border-t pt-2">
                仓库 #{{ row.warehouse_id }} · 库位 #{{ row.location_id }} · 单位 #{{ row.unit_id }}：余额 {{ row.quantity ?? '缺失' }}，流水净额 {{ row.movement_net }}，差额 {{ row.difference ?? '无法判定' }} · {{ recallSlotStatus(row.status) }} · {{ recallCheckStatus(row.check_status) }}
              </div>
              <div class="font-medium">出库去向</div>
              <div v-for="row in selectedRecallReport.result_json.outflows" :key="row.transaction_id" class="border-t pt-2">
                {{ row.transaction_no }} · {{ row.quantity }} / 单位 #{{ row.unit_id }} · {{ sourceTypeLabel(row.source_type) }} #{{ row.source_id ?? '缺失' }} · {{ row.source_status ? sourceMatchStatus(row.source_status) : row.source_found ? '来源单据已找到' : '来源缺失' }} · {{ recallCheckStatus(row.check_status) }}
                <div v-if="row.finding" class="text-muted-foreground">{{ row.finding }}</div>
              </div>
              <template v-if="selectedRecallReport.result_json.source_matches?.length">
                <h4 class="font-medium">来源明细匹配</h4>
                <div v-for="row in selectedRecallReport.result_json.source_matches" :key="row.transaction_id" class="border-t pt-2">
                  <div class="flex flex-wrap items-center justify-between gap-2"><span>{{ row.transaction_no }} · {{ sourceTypeLabel(row.source_type) }} #{{ row.source_id ?? '缺失' }} · 明细 #{{ row.item_id ?? '未定位' }}</span><Tag :color="row.status === 'MATCHED' ? 'green' : 'gold'">{{ sourceMatchStatus(row.status) }}</Tag></div>
                  <div class="mt-1 break-words text-muted-foreground">流水 {{ row.quantity }} / 单位 #{{ row.unit_id }} · 明细执行量 {{ row.expected_quantity ?? '无法确认' }}；{{ row.reason }}</div>
                </div>
              </template>
              <template v-if="selectedRecallReport.result_json.transfer_pairs?.length">
                <h4 class="font-medium">调拨两端核对</h4>
                <div v-for="row in selectedRecallReport.result_json.transfer_pairs" :key="row.item_id" class="border-t pt-2">
                  <div class="flex flex-wrap items-center justify-between gap-2"><span>调拨申请 #{{ row.request_id }} · 明细 #{{ row.item_id }} · 单位 #{{ row.unit_id }}</span><Tag :color="row.status === 'MATCHED' ? 'green' : 'gold'">{{ transferPairStatus(row.status) }}</Tag></div>
                  <div class="mt-1 text-muted-foreground">出库 {{ row.outbound_quantity ?? '超出权限' }}（流水 {{ row.outbound_ids.join('、') || '缺失' }}）· 入库 {{ row.inbound_quantity ?? '超出权限' }}（流水 {{ row.inbound_ids.join('、') || '缺失' }}）· {{ row.review_status === 'VERIFIED' ? '两端已复核' : '两端复核未完成' }}</div>
                </div>
              </template>
              <template v-if="!selectedRecallReport.result_json.transfer_pairs">
                <div v-for="row in selectedRecallReport.result_json.transfer_differences" :key="`${row.request_id}-${row.unit_id}`" class="border-t pt-2">调拨申请 #{{ row.request_id }} · 单位 #{{ row.unit_id }} · 出入库净差 {{ row.net }}，需核对调拨两端。</div>
              </template>
              <div v-for="item in selectedRecallReport.result_json.limitations" :key="item" class="border-t pt-2 text-muted-foreground">{{ item }}</div>
            </div>
          </div>
        </section>

        <section v-if="targetKind === 'finance-difference'" class="space-y-3">
          <div class="flex items-center justify-between">
            <h3 class="font-medium">财务核查清单</h3>
            <Button v-if="hasAccessByCodes(['finance.reconciliations.write'])" :loading="busy" @click="startFinanceChecks">{{ financeChecks.length ? '补充订单行与发票' : '建立核查清单' }}</Button>
          </div>
          <Alert show-icon type="info" message="订单行核对到货；发票、付款和退货保持单据级口径，不自动分摊到产品行。" />
          <div v-for="item in financeChecks" :key="item.id" class="space-y-2 rounded-lg border p-3 text-sm">
            <div class="flex items-center justify-between">
              <span>{{ item.target_label }}</span>
              <Tag :color="item.status === 'VERIFIED' ? 'green' : item.status === 'NEEDS_ACTION' ? 'red' : 'blue'">{{ { OPEN: '待核查', CHECKED: '待复核', NEEDS_ACTION: '需处理', VERIFIED: '已复核' }[item.status] ?? item.status }}</Tag>
            </div>
            <div class="text-xs text-muted-foreground">来源快照 #{{ item.snapshot_id }}</div>
            <Select
              v-if="hasAccessByCodes(['finance.reconciliations.write'])"
              :value="item.assignee_id ?? undefined"
              :options="financeAssignees.map((person) => ({ label: person.name, value: person.id }))"
              allow-clear
              class="w-full"
              placeholder="指派财务核查人员"
              :disabled="busy || item.status === 'VERIFIED'"
              @change="(value) => changeFinanceCheck(item, { assignee_id: typeof value === 'number' ? value : null })"
            />
            <Input.TextArea v-if="hasAccessByCodes(['finance.reconciliations.write'])" v-model:value="findings[item.id]" :disabled="item.status === 'VERIFIED'" :rows="2" :maxlength="2000" placeholder="记录差异来源、处理办法、关联单据编号和处理结论" />
            <div v-else-if="item.finding" class="whitespace-pre-wrap text-muted-foreground">{{ item.finding }}</div>
            <div v-if="hasAccessByCodes(['finance.reconciliations.write'])" class="flex flex-wrap gap-2">
              <Button v-if="item.status === 'OPEN' || item.status === 'NEEDS_ACTION'" size="small" :disabled="busy" @click="changeFinanceCheck(item, { status: 'CHECKED', finding: findings[item.id] })">提交核查</Button>
              <Button v-if="item.status === 'OPEN' || item.status === 'CHECKED'" size="small" :disabled="busy" @click="changeFinanceCheck(item, { status: 'NEEDS_ACTION', finding: findings[item.id] })">标记需处理</Button>
              <Button v-if="item.status === 'CHECKED'" size="small" type="primary" :disabled="busy" @click="changeFinanceCheck(item, { status: 'VERIFIED', finding: findings[item.id] })">复核通过</Button>
              <Button v-if="item.status !== 'OPEN'" size="small" :disabled="busy" @click="changeFinanceCheck(item, { status: 'OPEN', finding: findings[item.id] })">重新核查</Button>
            </div>
            <div v-if="item.checked_at" class="text-xs text-muted-foreground">核查人 #{{ item.checked_by }} · {{ item.checked_at }}<span v-if="item.reviewed_at">；复核人 #{{ item.reviewed_by }} · {{ item.reviewed_at }}</span></div>
            <Button size="small" type="link" @click="showFinanceEvents(item)">查看处理记录</Button>
            <div v-for="event in events[item.id] ?? []" :key="event.id" class="border-t pt-2 text-xs text-muted-foreground">
              {{ event.created_at }} · 操作人 #{{ event.actor_id }} · {{ event.status }} · {{ event.finding || '无说明' }}
            </div>
          </div>
        </section>

        <section>
          <h3 class="mb-2 font-medium">核查依据</h3>
          <div v-if="result.evidence.length" class="divide-y rounded-lg border">
            <div v-for="(item, index) in result.evidence" :key="`${item.source}-${index}`" class="flex flex-wrap items-start justify-between gap-3 px-3 py-3 text-sm">
              <div class="min-w-0 flex-1">
                <div class="font-medium">{{ item.label }}</div>
                <div class="mt-1 whitespace-pre-wrap break-words text-muted-foreground">{{ item.value }}</div>
                <div class="mt-1 text-xs text-muted-foreground">来源：{{ item.source }}</div>
              </div>
              <Button v-if="item.path" size="small" type="link" @click="openSource(item.path)">打开来源</Button>
            </div>
          </div>
          <Empty v-else description="当前没有可核查记录" />
        </section>

        <section v-if="result.suggestions.length">
          <h3 class="mb-2 font-medium">建议核查</h3>
          <ul class="list-disc space-y-1 pl-5 text-sm">
            <li v-for="item in result.suggestions" :key="item">{{ item }}</li>
          </ul>
        </section>

        <section v-if="targetKind === 'exception-action'" class="space-y-3 rounded-lg border p-3">
          <h3 class="font-medium">处置决定</h3>
          <div v-if="exceptionDecision" class="text-sm">
            当前决定：<Tag :color="exceptionDecision.decision === 'ADOPTED' ? 'blue' : 'default'">{{ exceptionDecision.decision === 'ADOPTED' ? '已采纳' : '已驳回' }}</Tag>
            <span v-if="exceptionDecision.task_id">关联任务 #{{ exceptionDecision.task_id }}</span>
            <div class="mt-1 text-muted-foreground">{{ exceptionDecision.reason }}</div>
          </div>
          <div v-if="hasAccessByCodes(['operations.exceptions.write'])" class="space-y-2">
            <Input.TextArea v-model:value="decisionReason" :rows="2" :maxlength="2000" placeholder="说明采纳依据或驳回原因；采纳前须在异常详情指定负责人" />
            <div class="flex flex-wrap gap-2">
              <Button type="primary" :loading="busy" :disabled="exceptionDecision?.decision === 'ADOPTED'" @click="decideException('ADOPTED')">采纳并建立任务</Button>
              <Button :loading="busy" :disabled="exceptionDecision?.decision === 'REJECTED'" @click="decideException('REJECTED')">驳回建议</Button>
            </div>
          </div>
          <div v-if="exceptionEvents.length" class="space-y-1 border-t pt-2 text-xs text-muted-foreground">
            <div v-for="event in exceptionEvents" :key="event.id">{{ event.created_at }} · 操作人 #{{ event.actor_id }} · {{ event.decision === 'ADOPTED' ? '采纳' : '驳回' }} · {{ event.reason }}</div>
          </div>
        </section>

        <section v-if="result.limitations.length" class="space-y-2">
          <h3 class="font-medium">数据范围</h3>
          <div v-for="item in result.limitations" :key="item" class="text-sm text-muted-foreground">
            <Tag color="gold">需留意</Tag>{{ item }}
          </div>
        </section>
      </div>
    </Spin>
  </Drawer>
</template>
