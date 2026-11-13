<script lang="ts" setup>
import type { AgentApi } from '#/api';

import { computed, onMounted, ref } from 'vue';
import { Button, Checkbox, Modal, Select, Table, Tag, message } from 'antdv-next';

import {
  createRegressionCasesBatchApi,
  getRegressionCaseCandidatesApi,
  getRegressionCaseOptionsApi,
  getRegressionCasePageApi,
  reviewRegressionCasesBatchApi,
  reviewRegressionCaseApi,
} from '#/api';
import RegressionCaseModal from '#/views/ai/tasks/RegressionCaseModal.vue';

defineOptions({ name: 'RegressionCases' });

const rows = ref<AgentApi.RegressionCase[]>([]);
const options = ref<AgentApi.RegressionCaseOptions>();
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const status = ref<string>();
const loading = ref(false);
const reviewingId = ref<number>();
const candidatesOpen = ref(false);
const candidatesLoading = ref(false);
const candidates = ref<AgentApi.RegressionCaseCandidate[]>([]);
const candidateTotal = ref(0);
const candidateDays = ref(7);
const candidateIncludeInfra = ref(false);
const createOpen = ref(false);
const activeCandidate = ref<AgentApi.RegressionCaseCandidate>();
const selectedKeys = ref<string[]>([]);
const batchOpen = ref(false);
const batchSaving = ref(false);
const batchConfirmed = ref(false);
const selectedCaseIds = ref<number[]>([]);
const approveOpen = ref(false);
const approveSaving = ref(false);
const approveConfirmed = ref(false);
const statusOptions = [
  { label: '草稿', value: 'DRAFT' },
  { label: '已批准', value: 'APPROVED' },
  { label: '已归档', value: 'ARCHIVED' },
];
const statusLabels: Record<AgentApi.RegressionCase['status'], string> = {
  APPROVED: '已批准',
  ARCHIVED: '已归档',
  DRAFT: '草稿',
};
const statusColors: Record<AgentApi.RegressionCase['status'], string> = {
  APPROVED: 'success',
  ARCHIVED: 'default',
  DRAFT: 'warning',
};
const modeLabels: Record<string, string> = {
  agent: 'Agent 只读任务',
  batch: '多意图批次',
  document: '文档问答',
  none: '不执行',
  query: '统计查询',
};
const taskLabels = computed(() => Object.fromEntries(
  (options.value?.tasks ?? []).map((item) => [item.key, item.label])));
const candidateDayOptions = [
  { label: '最近 7 天', value: 7 },
  { label: '最近 30 天', value: 30 },
  { label: '最近 90 天', value: 90 },
];
const sourceLabels: Record<string, string> = { failure: '失败任务', feedback: '差评' };
const stageLabels: Record<string, string> = {
  budget: '预算', confirm: '证据与确认', context: '上下文', infra: '基础设施',
  planner: '规划生成', routing: '路由识别', tool: '工具调用', unknown: '未归类',
};

const columns = [
  { dataIndex: 'case_key', key: 'case_key', title: '用例编号', width: 140 },
  { dataIndex: 'status', key: 'status', title: '状态', width: 90 },
  { dataIndex: 'expected_execution_mode', key: 'mode', title: '执行模式', width: 130 },
  { dataIndex: 'expected_tasks', key: 'tasks', title: '任务', width: 180 },
  { dataIndex: 'question', key: 'question', title: '脱敏后的问题', ellipsis: true },
  { dataIndex: 'source_prompt_version', key: 'prompt', title: '来源 prompt', width: 190, ellipsis: true },
  { dataIndex: 'created_at', key: 'created_at', title: '提交时间', width: 170 },
  { key: 'operation', title: '操作', width: 130, fixed: 'right' as const },
];

const candidateColumns = [
  { dataIndex: 'source', key: 'source', title: '来源', width: 90 },
  { dataIndex: 'question', key: 'question', title: '问题（自动脱敏预览）', ellipsis: true },
  { dataIndex: 'task_status', key: 'task_status', title: '任务状态', width: 100 },
  { dataIndex: 'error_code', key: 'error', title: '错误码 / 失败阶段', width: 190 },
  { dataIndex: 'feedback_reason_code', key: 'reason', title: '差评原因', width: 110 },
  { dataIndex: 'existing_case_id', key: 'existing', title: '已入库', width: 90 },
  { key: 'operation', title: '操作', width: 100, fixed: 'right' as const },
];

const batchColumns = [
  { dataIndex: 'question', key: 'question', title: '脱敏后的问题（将保存）', ellipsis: true },
  { dataIndex: 'tasks', key: 'tasks', title: '任务', width: 150 },
  { dataIndex: 'findings', key: 'findings', title: '自动脱敏命中', width: 180 },
];

const redactionLabels: Record<string, string> = {
  bank_card: '银行卡',
  company: '单位名称',
  contact: '联系人',
  email: '邮箱',
  id_card: '身份证',
  ip: 'IP',
  landline: '座机',
  mobile: '手机号',
};

const selectedCandidates = computed(() => candidates.value.filter(
  (item) => selectedKeys.value.includes(item.case_key) && !item.existing_case_id));
const batchPreview = computed(() => selectedCandidates.value.map((item) => ({
  case_key: item.case_key,
  findings: findingsText(item.redaction_findings),
  question: item.redacted_question,
  tasks: candidateTaskText(item),
})));

const approveColumns = [
  { dataIndex: 'case_key', key: 'case_key', title: '用例编号', width: 140 },
  { dataIndex: 'question', key: 'question', title: '脱敏后的问题', ellipsis: true },
  { dataIndex: 'tasks', key: 'tasks', title: '任务', width: 150 },
];

const selectedCases = computed(() => rows.value.filter(
  (item) => selectedCaseIds.value.includes(item.id) && item.status === 'DRAFT'));
const approvePreview = computed(() => selectedCases.value.map((row) => ({
  case_key: row.case_key,
  question: row.question,
  tasks: taskText(row),
})));

async function load() {
  loading.value = true;
  try {
    const result = await getRegressionCasePageApi({
      page: page.value,
      page_size: pageSize.value,
      status: status.value,
    });
    rows.value = result.items;
    total.value = result.total;
    selectedCaseIds.value = [];
  } catch {
    message.error('读取回归用例失败，请确认管理员权限');
  } finally {
    loading.value = false;
  }
}

function search() {
  page.value = 1;
  void load();
}

function reset() {
  status.value = undefined;
  search();
}

function onTableChange(pagination: { current?: number; pageSize?: number }) {
  page.value = pagination.current ?? 1;
  pageSize.value = pagination.pageSize ?? pageSize.value;
  void load();
}

function taskText(row: AgentApi.RegressionCase) {
  if (!row.expected_tasks.length) return '—';
  return row.expected_tasks.map((key) => taskLabels.value[key] ?? key).join('、');
}

function candidateTaskText(row: AgentApi.RegressionCaseCandidate) {
  if (!row.expected_tasks.length) return '—';
  return row.expected_tasks.map((key) => taskLabels.value[key] ?? key).join('、');
}

function candidateStageText(row: AgentApi.RegressionCaseCandidate) {
  if (!row.error_code) return '—';
  const stage = row.failure_stage ? (stageLabels[row.failure_stage] ?? row.failure_stage) : '未归类';
  return `${row.error_code} / ${stage}`;
}

function findingsText(findings: Record<string, number> | undefined) {
  const entries = Object.entries(findings ?? {});
  if (!entries.length) return '无';
  return entries.map(([key, count]) => `${redactionLabels[key] ?? key}×${count}`).join('、');
}

function onCandidateSelect(keys: (number | string)[]) {
  selectedKeys.value = keys.map(String);
  batchConfirmed.value = false;
}

function candidateCheckboxProps(row: AgentApi.RegressionCaseCandidate) {
  return { disabled: Boolean(row.existing_case_id) };
}

function openBatch() {
  if (!selectedCandidates.value.length) return;
  batchConfirmed.value = false;
  batchOpen.value = true;
}

function batchNote(row: AgentApi.RegressionCaseCandidate) {
  if (row.source === 'feedback') {
    return row.feedback_reason_code ? `差评：${row.feedback_reason_code}` : '差评任务转用例';
  }
  return row.error_code ? `失败任务：${row.error_code}` : null;
}

async function submitBatch() {
  if (!batchConfirmed.value || !selectedCandidates.value.length) return;
  batchSaving.value = true;
  try {
    const result = await createRegressionCasesBatchApi({
      items: selectedCandidates.value.map((item) => ({
        expected_execution_mode: item.expected_execution_mode,
        expected_tasks: item.expected_tasks,
        forbidden_tasks: item.forbidden_tasks,
        note: batchNote(item),
        question: item.redacted_question,
        source_task_id: item.source_task_id,
      })),
      redacted_confirmed: true,
    });
    const summary = `新增 ${result.created}、复用 ${result.reused}、跳过 ${result.skipped}、失败 ${result.failed}`;
    if (result.failed) {
      const reasons = result.items
        .filter((item) => item.status === 'FAILED')
        .slice(0, 2)
        .map((item) => item.reason)
        .filter(Boolean)
        .join('；');
      message.warning(`批量生成完成：${summary}${reasons ? `；${reasons}` : ''}`);
    } else {
      message.success(`批量生成完成：${summary}`);
    }
    batchOpen.value = false;
    selectedKeys.value = [];
    await loadCandidates();
    await load();
  } catch (error: any) {
    message.error(error?.message || '批量生成失败');
  } finally {
    batchSaving.value = false;
  }
}

function onCaseSelect(keys: (number | string)[]) {
  selectedCaseIds.value = keys.map(Number);
  approveConfirmed.value = false;
}

function caseCheckboxProps(row: AgentApi.RegressionCase) {
  return { disabled: row.status !== 'DRAFT' };
}

function openApprove() {
  if (!selectedCases.value.length) return;
  approveConfirmed.value = false;
  approveOpen.value = true;
}

async function submitApprove() {
  if (!approveConfirmed.value || !selectedCases.value.length) return;
  approveSaving.value = true;
  try {
    const result = await reviewRegressionCasesBatchApi({
      action: 'APPROVE',
      case_ids: selectedCases.value.map((item) => item.id),
    });
    const summary = `批准 ${result.updated}、跳过 ${result.skipped}、失败 ${result.failed}`;
    if (result.skipped || result.failed) {
      const reasons = result.items
        .filter((item) => item.result !== 'UPDATED')
        .slice(0, 2)
        .map((item) => item.reason)
        .filter(Boolean)
        .join('；');
      message.warning(`批量批准完成：${summary}${reasons ? `；${reasons}` : ''}`);
    } else {
      message.success(`批量批准完成：${summary}`);
    }
    approveOpen.value = false;
    selectedCaseIds.value = [];
    await load();
    await loadCandidates();
  } catch (error: any) {
    message.error(error?.message || '批量批准失败');
  } finally {
    approveSaving.value = false;
  }
}

async function loadCandidates() {
  candidatesLoading.value = true;
  try {
    const result = await getRegressionCaseCandidatesApi({
      days: candidateDays.value,
      include_infra: candidateIncludeInfra.value,
      limit: 20,
    });
    candidates.value = result.items;
    candidateTotal.value = result.total;
    selectedKeys.value = [];
    batchConfirmed.value = false;
  } catch {
    message.error('读取候选失败，请确认管理员权限');
  } finally {
    candidatesLoading.value = false;
  }
}

function openCandidates() {
  candidatesOpen.value = true;
  void loadCandidates();
}

function openCreate(row: AgentApi.RegressionCaseCandidate) {
  if (row.existing_case_id) {
    message.info('该任务已有回归用例，请在上方列表核对');
    return;
  }
  activeCandidate.value = row;
  createOpen.value = true;
}

async function afterCreated() {
  await loadCandidates();
  await load();
}

function confirmReview(row: AgentApi.RegressionCase, action: 'APPROVE' | 'ARCHIVE') {
  if (reviewingId.value) return;
  const label = action === 'APPROVE' ? '批准' : '归档';
  Modal.confirm({
    title: `${label}回归用例`,
    content: `确认${label} ${row.case_key}？${action === 'APPROVE' ? '批准后会被导出脚本纳入评测集。' : '归档后不会进入评测集，且不可恢复。'}`,
    okText: `确认${label}`,
    cancelText: '取消',
    onOk: async () => {
      reviewingId.value = row.id;
      try {
        await reviewRegressionCaseApi(row.id, action);
        message.success(`用例${label}成功`);
        void load();
      } catch (error: any) {
        message.error(error?.message || `${label}失败，请刷新后重试`);
      } finally {
        reviewingId.value = undefined;
      }
    },
  });
}

onMounted(async () => {
  try {
    options.value = await getRegressionCaseOptionsApi();
  } catch {
    message.error('读取回归用例选项失败');
  }
  await load();
});
</script>

<template>
  <section class="rounded bg-card p-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold">回归用例</h2>
        <p class="text-muted-foreground mt-1 text-xs">
          由任务详情或候选批量提交、人工确认后由服务端确定性脱敏的回归用例；管理员批准后由导出脚本纳入评测集。Agent 不自动修改用例或提示词。
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Select v-model:value="status" :options="statusOptions" allow-clear placeholder="全部状态" class="w-36" />
        <Button @click="openCandidates">生成候选</Button>
        <Button :disabled="!selectedCases.length" @click="openApprove">批量批准</Button>
        <Button @click="reset">重置</Button>
        <Button type="primary" :loading="loading" @click="search">查询</Button>
      </div>
    </div>

    <Table
      class="mt-4"
      :columns="columns"
      :data-source="rows"
      :loading="loading"
      :pagination="{
        current: page,
        pageSize,
        total,
        showSizeChanger: false,
      }"
      :row-selection="{
        selectedRowKeys: selectedCaseIds,
        onChange: onCaseSelect,
        getCheckboxProps: caseCheckboxProps,
      }"
      row-key="id"
      size="small"
      @change="onTableChange"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <Tag :color="statusColors[(record as AgentApi.RegressionCase).status]">
            {{ statusLabels[(record as AgentApi.RegressionCase).status] }}
          </Tag>
        </template>
        <template v-else-if="column.key === 'mode'">
          {{ modeLabels[(record as AgentApi.RegressionCase).expected_execution_mode] ?? (record as AgentApi.RegressionCase).expected_execution_mode }}
        </template>
        <template v-else-if="column.key === 'tasks'">
          {{ taskText(record as AgentApi.RegressionCase) }}
        </template>
        <template v-else-if="column.key === 'prompt'">
          {{ (record as AgentApi.RegressionCase).source_prompt_version || '—' }}
        </template>
        <template v-else-if="column.key === 'created_at'">
          {{ (record as AgentApi.RegressionCase).created_at?.replace('T', ' ').slice(0, 16) || '—' }}
        </template>
        <template v-else-if="column.key === 'operation'">
          <Button
            v-if="(record as AgentApi.RegressionCase).status === 'DRAFT'"
            type="link"
            size="small"
            :loading="reviewingId === (record as AgentApi.RegressionCase).id"
            @click="confirmReview(record as AgentApi.RegressionCase, 'APPROVE')"
          >
            批准
          </Button>
          <Button
            v-if="(record as AgentApi.RegressionCase).status !== 'ARCHIVED'"
            type="link"
            size="small"
            danger
            @click="confirmReview(record as AgentApi.RegressionCase, 'ARCHIVE')"
          >
            归档
          </Button>
        </template>
      </template>
    </Table>

    <Modal v-model:open="candidatesOpen" :footer="null" :width="1040" title="差评与失败任务候选">
      <div class="flex flex-wrap items-start justify-between gap-2">
        <p class="text-muted-foreground max-w-[640px] text-xs">
          来自近期差评或带错误码的失败任务，默认排除 WORKER_UNAVAILABLE 等基础设施失败；服务端按固定规则自动遮蔽手机号、邮箱、身份证、银行卡、IP 与联系人/单位名称；
          产品、供应商等业务实体不会自动改写，请核对后再提交。
        </p>
        <div class="flex items-center gap-2">
          <Select v-model:value="candidateDays" :options="candidateDayOptions" class="w-32" />
          <Checkbox v-model:checked="candidateIncludeInfra" @change="loadCandidates">
            含基础设施失败
          </Checkbox>
          <Button :loading="candidatesLoading" @click="loadCandidates">刷新</Button>
          <Button type="primary" :disabled="!selectedCandidates.length" @click="openBatch">
            批量生成草稿
          </Button>
        </div>
      </div>
      <Table
        class="mt-3"
        :columns="candidateColumns"
        :data-source="candidates"
        :loading="candidatesLoading"
        :pagination="{ pageSize: 10, showSizeChanger: false }"
        :row-selection="{
          selectedRowKeys: selectedKeys,
          onChange: onCandidateSelect,
          getCheckboxProps: candidateCheckboxProps,
        }"
        row-key="case_key"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'source'">
            <Tag :color="(record as AgentApi.RegressionCaseCandidate).source === 'feedback' ? 'warning' : 'processing'">
              {{ sourceLabels[(record as AgentApi.RegressionCaseCandidate).source] }}
            </Tag>
          </template>
          <template v-else-if="column.key === 'question'">
            <span :title="(record as AgentApi.RegressionCaseCandidate).redacted_question">
              {{ (record as AgentApi.RegressionCaseCandidate).redacted_question }}
            </span>
            <div class="text-muted-foreground mt-0.5 text-xs">
              {{ candidateTaskText(record as AgentApi.RegressionCaseCandidate) }}
              · 脱敏命中：{{ findingsText((record as AgentApi.RegressionCaseCandidate).redaction_findings) }}
            </div>
          </template>
          <template v-else-if="column.key === 'error'">
            {{ candidateStageText(record as AgentApi.RegressionCaseCandidate) }}
          </template>
          <template v-else-if="column.key === 'reason'">
            {{ (record as AgentApi.RegressionCaseCandidate).feedback_reason_code || '—' }}
          </template>
          <template v-else-if="column.key === 'existing'">
            {{ (record as AgentApi.RegressionCaseCandidate).existing_case_id ? `#${(record as AgentApi.RegressionCaseCandidate).existing_case_id}` : '—' }}
          </template>
          <template v-else-if="column.key === 'operation'">
            <Button type="link" size="small" @click="openCreate(record as AgentApi.RegressionCaseCandidate)">
              生成草稿
            </Button>
          </template>
        </template>
      </Table>
    </Modal>

    <Modal
      v-model:open="batchOpen"
      :confirm-loading="batchSaving"
      :ok-button-props="{ disabled: !batchConfirmed || !selectedCandidates.length }"
      :width="880"
      cancel-text="取消"
      ok-text="确认批量生成"
      title="批量生成回归用例"
      @ok="submitBatch"
    >
      <div class="rounded border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        将提交 {{ selectedCandidates.length }} 条候选。服务端保存前会再次执行确定性脱敏；
        已有本人草稿会复用，已审阅或同来源任务已有用例会跳过。产品、供应商等业务实体不会被自动改写。
      </div>
      <Table
        class="mt-3"
        :columns="batchColumns"
        :data-source="batchPreview"
        :pagination="false"
        :scroll="{ y: 300 }"
        row-key="case_key"
        size="small"
      />
      <Checkbox v-model:checked="batchConfirmed" class="mt-3">
        我已核对以上脱敏预览，确认不含客户、联系人、联系方式、真实单号等敏感信息
      </Checkbox>
    </Modal>

    <Modal
      v-model:open="approveOpen"
      :confirm-loading="approveSaving"
      :ok-button-props="{ disabled: !approveConfirmed || !selectedCases.length }"
      :width="880"
      cancel-text="取消"
      ok-text="确认批准"
      title="批量批准回归用例"
      @ok="submitApprove"
    >
      <div class="rounded border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        将批准 {{ selectedCases.length }} 条草稿，批准后由导出脚本纳入评测集。已在审阅状态或已被他人处理的用例会跳过并给出原因。
      </div>
      <Table
        class="mt-3"
        :columns="approveColumns"
        :data-source="approvePreview"
        :pagination="false"
        :scroll="{ y: 300 }"
        row-key="case_key"
        size="small"
      />
      <Checkbox v-model:checked="approveConfirmed" class="mt-3">
        我已核对以上用例的问题文本与期望任务
      </Checkbox>
    </Modal>

    <RegressionCaseModal
      v-model:open="createOpen"
      :draft="activeCandidate"
      @created="afterCreated"
    />
  </section>
</template>
