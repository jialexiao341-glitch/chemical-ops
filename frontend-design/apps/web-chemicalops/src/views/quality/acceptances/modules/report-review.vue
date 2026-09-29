<script lang="ts" setup>
import type { QualityAcceptanceApi } from '#/api';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { Alert, Button, Input, Select, Spin, Tag, message } from 'antdv-next';

import {
  downloadAcceptanceReportApi,
  decideAcceptanceReviewApi,
  getAcceptanceReportFilesApi,
  getAcceptanceReviewHistoryApi,
  getAcceptanceReviewRecordApi,
  getAcceptanceReviewTargetsApi,
  reviewAcceptanceReportApi,
  uploadAcceptanceReportApi,
} from '#/api';

const emit = defineEmits(['continue']);
const acceptance = ref<null | QualityAcceptanceApi.Acceptance>(null);
const files = ref<QualityAcceptanceApi.ReportFile[]>([]);
const targets = ref<QualityAcceptanceApi.ReviewTarget[]>([]);
const history = ref<QualityAcceptanceApi.ReviewHistory[]>([]);
const selectedFileId = ref<number>();
const selectedTargetId = ref<number>();
const reviewerNote = ref('');
const deciding = ref(false);
const review = ref<null | QualityAcceptanceApi.ReportReview>(null);
const loadingFiles = ref(false);
const uploading = ref(false);
const reviewing = ref(false);
const fileInput = ref<HTMLInputElement>();

const title = computed(() => `核对报告 · ${acceptance.value?.acceptance_no ?? ''}`);
const selectedFile = computed(() => files.value.find((item) => item.id === selectedFileId.value));
const mismatchCount = computed(() => review.value?.checks.filter((item) => item.status !== 'MATCH').length ?? 0);
const standardIssueCount = computed(() => review.value?.checks.filter((item) => ['MISSING', 'OUTSIDE_STANDARD', 'UNVERIFIED'].includes(item.standard_status)).length ?? 0);
const currentHistory = computed(() => history.value.find((item) => item.id === review.value?.review_id));
const canRecordResult = computed(() => !acceptance.value?.result || ['PENDING', 'REINSPECTION'].includes(acceptance.value.result));
const canPrefill = computed(() => canRecordResult.value && targets.value.length === 1 && review.value?.review_id === history.value[0]?.id && review.value?.batch_status === 'MATCH' && review.value?.product_status === 'MATCH');

/** 将有报告原文依据的结果带入验收表单，由用户继续填写。 */
function continueToResult() {
  if (!acceptance.value) return;
  const suggestedTestResult = Object.fromEntries(
    (review.value?.checks ?? [])
      .filter((item) => item.report_value && item.source_quote)
      .map((item) => [item.item_name, item.report_value as string]),
  );
  drawerApi.close();
  emit('continue', {
    ...acceptance.value,
    suggested_report_file_id: review.value?.file_id,
    suggested_test_result: suggestedTestResult,
  });
}

/** 加载验收单报告，并优先选中此前关联的文件。 */
async function loadFiles(id: number) {
  loadingFiles.value = true;
  try {
    files.value = await getAcceptanceReportFilesApi(id);
    const preferred = acceptance.value?.report_file_id;
    selectedFileId.value = files.value.find((item) => item.id === preferred)?.id ?? files.value[0]?.id;
  } finally {
    loadingFiles.value = false;
  }
}

/** 并行加载核对目标与历史；只有单条明细时自动选中。 */
async function loadContext(id: number) {
  const [targetRows, reviewRows] = await Promise.all([
    getAcceptanceReviewTargetsApi(id),
    getAcceptanceReviewHistoryApi(id),
  ]);
  targets.value = targetRows;
  history.value = reviewRows;
  selectedTargetId.value = targetRows.length === 1 ? targetRows[0]?.delivery_item_id : undefined;
}

const [Drawer, drawerApi] = useVbenDrawer<null | QualityAcceptanceApi.Acceptance>({
  /** 打开抽屉时清除上次状态并加载当前验收单上下文。 */
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    acceptance.value = drawerApi.getData() ?? null;
    review.value = null;
    targets.value = [];
    history.value = [];
    reviewerNote.value = '';
    files.value = [];
    selectedFileId.value = undefined;
    if (acceptance.value) await Promise.all([loadFiles(acceptance.value.id), loadContext(acceptance.value.id)]);
  },
});

/** 上传用户选择的报告，关联当前验收单并选中该文件。 */
async function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  const record = acceptance.value;
  input.value = '';
  if (!file || !record) return;
  uploading.value = true;
  try {
    const uploaded = await uploadAcceptanceReportApi(record.id, file);
    files.value = [uploaded, ...files.value];
    selectedFileId.value = uploaded.id;
    review.value = null;
    message.success('报告已关联到当前验收单');
  } catch {
    // 请求层已显示权限或上传错误。
  } finally {
    uploading.value = false;
  }
}

/** 对选定报告和到货明细发起核对，并刷新历史记录。 */
async function runReview() {
  if (!acceptance.value || !selectedFileId.value) return;
  reviewing.value = true;
  review.value = null;
  try {
    review.value = await reviewAcceptanceReportApi(acceptance.value.id, selectedFileId.value, selectedTargetId.value);
    reviewerNote.value = '';
    history.value = await getAcceptanceReviewHistoryApi(acceptance.value.id);
  } catch {
    // 请求层已显示解析或 AI 服务错误。
  } finally {
    reviewing.value = false;
  }
}

/** 展示指定历史核对快照及其已有复核意见。 */
async function openHistory(reviewId: number) {
  if (!acceptance.value) return;
  review.value = await getAcceptanceReviewRecordApi(acceptance.value.id, reviewId);
  selectedFileId.value = review.value.file_id;
  selectedTargetId.value = review.value.delivery_item_id ?? undefined;
  reviewerNote.value = currentHistory.value?.reviewer_note ?? '';
}

/** 保存人工确认或退回修正结论，要求填写复核意见。 */
async function decide(status: 'CONFIRMED' | 'NEEDS_CORRECTION') {
  if (!acceptance.value || !review.value?.review_id) return;
  if (!reviewerNote.value.trim()) {
    message.warning('请填写人工复核意见');
    return;
  }
  deciding.value = true;
  try {
    await decideAcceptanceReviewApi(acceptance.value.id, review.value.review_id, status, reviewerNote.value.trim());
    history.value = await getAcceptanceReviewHistoryApi(acceptance.value.id);
    message.success('复核意见已保存');
  } catch {
    // 请求层已显示错误。
  } finally {
    deciding.value = false;
  }
}

/** 将标准比对状态转换为页面展示文字。 */
function standardLabel(status: QualityAcceptanceApi.ReportCheck['standard_status']) {
  return {
    WITHIN_STANDARD: '符合配置范围',
    OUTSIDE_STANDARD: '超出配置范围',
    UNVERIFIED: '待人工核对',
    MISSING: '报告缺项',
    NOT_CONFIGURED: '未配置标准',
  }[status];
}

/** 下载当前选中报告，并在浏览器中释放临时下载地址。 */
async function downloadReport() {
  if (!acceptance.value || !selectedFileId.value || !selectedFile.value) return;
  try {
    const blob = await downloadAcceptanceReportApi(acceptance.value.id, selectedFileId.value);
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = selectedFile.value.file_name;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch {
    // 请求层已显示下载错误。
  }
}

/** 将报告与系统录入值的核对状态转换为页面文字。 */
function checkLabel(status: QualityAcceptanceApi.ReportCheck['status']) {
  return {
    MATCH: '一致',
    MISMATCH: '值不一致',
    NOT_COMPARABLE: '旧记录未关联明细',
    NOT_RECORDED: '系统未录入',
    REPORT_MISSING: '报告未找到',
  }[status];
}

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[860px] max-w-[100vw]">
    <div class="space-y-5 pb-6">
      <Alert
        type="info"
        show-icon
        message="只读核对"
        description="按选定的产品和批次核对报告、系统值与人工维护的检测标准。结果会留存供复核，不会提交验收结论。"
      />

      <section class="rounded-lg border border-border p-4">
        <h3 class="mb-3 text-sm font-semibold">选择报告与到货明细</h3>
        <Spin :spinning="loadingFiles">
          <Select
            v-model:value="selectedTargetId"
            class="mb-3 w-full"
            :options="targets.map((item) => ({ label: `${item.line_no}. ${item.product_name}${item.product_model ? `（${item.product_model}）` : ''} · ${item.batch_no || '批次未录入'}`, value: item.delivery_item_id }))"
            placeholder="请选择要核对的产品和批次"
            @change="review = null"
          />
          <div class="flex flex-wrap items-center gap-2">
            <Select
              v-model:value="selectedFileId"
              class="min-w-0 flex-1 sm:min-w-[300px]"
              :options="files.map((item) => ({ label: item.file_name, value: item.id }))"
              placeholder="先上传一份检测报告"
              :disabled="files.length === 0"
              @change="review = null"
            />
            <input ref="fileInput" class="hidden" type="file" accept=".pdf,.docx,.xlsx,.txt,.csv" aria-label="上传检测报告" @change="onFileChange" />
            <Button :loading="uploading" @click="fileInput?.click()">上传报告</Button>
            <Button :disabled="!selectedFileId" @click="downloadReport">查看原件</Button>
            <Button type="primary" :disabled="!selectedFileId || !selectedTargetId" :loading="reviewing" @click="runReview">开始核对</Button>
          </div>
        </Spin>
        <p class="mt-2 text-xs text-muted-foreground">支持可提取文字的 PDF、DOCX、XLSX 和文本报告；扫描件需启用文档识别服务。</p>
      </section>

      <section v-if="history.length" class="rounded-lg border border-border p-4">
        <h3 class="mb-2 text-sm font-semibold">历史核对记录</h3>
        <div class="max-h-36 space-y-2 overflow-y-auto">
          <button v-for="item in history" :key="item.id" type="button" class="flex w-full items-center justify-between gap-3 rounded border border-border px-3 py-2 text-left text-xs hover:bg-muted/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary" @click="openHistory(item.id)">
            <span class="truncate">{{ item.product_name }} · {{ item.batch_no || '无批次' }} · {{ item.file_name }} · 标准{{ item.standard_version ? `第 ${item.standard_version} 版` : '未配置' }}</span>
            <Tag :color="item.status === 'CONFIRMED' ? 'green' : item.status === 'NEEDS_CORRECTION' ? 'orange' : 'blue'" class="!mr-0 shrink-0">{{ item.status === 'CONFIRMED' ? '已确认' : item.status === 'NEEDS_CORRECTION' ? '需修正' : '待复核' }}</Tag>
          </button>
        </div>
      </section>

      <section v-if="review" class="space-y-4" aria-live="polite">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 class="text-base font-semibold">核对结果</h3>
            <p class="text-xs text-muted-foreground">{{ review.product_name }} · {{ review.file_name }} · {{ review.checks.length }} 项 · {{ mismatchCount }} 项录入待核对 · {{ standardIssueCount }} 项标准待核查</p>
          </div>
          <Tag :color="mismatchCount || standardIssueCount || !review.standard_id || review.batch_status !== 'MATCH' || review.product_status !== 'MATCH' ? 'orange' : 'blue'" class="!mr-0">
            {{ mismatchCount || standardIssueCount || !review.standard_id || review.batch_status !== 'MATCH' || review.product_status !== 'MATCH' ? '需要人工复核' : '已完成只读核对' }}
          </Tag>
        </div>

        <Alert v-for="warning in review.warnings" :key="warning" type="warning" show-icon :message="warning" />

        <div v-if="review.standard_version" class="rounded-lg border border-border px-4 py-3 text-sm">
          <span class="font-medium">适用检测标准：第 {{ review.standard_version }} 版</span>
          <span class="ml-2 text-muted-foreground">{{ review.standard_source }}</span>
        </div>

        <div class="rounded-lg border border-border p-4">
          <div class="mb-1 flex items-center gap-2 text-sm font-medium">
            检品名称
            <Tag :color="review.product_status === 'MATCH' ? 'green' : 'orange'" class="!mr-0">{{ review.product_status === 'MATCH' ? '名称一致' : review.product_status === 'MISMATCH' ? '名称不一致' : '无法核对' }}</Tag>
          </div>
          <p class="text-sm">报告：{{ review.report_product_name || '未提取到' }}{{ review.report_product_model ? `（${review.report_product_model}）` : '' }} · 所选产品：{{ review.product_name }}{{ review.product_model ? `（${review.product_model}）` : '' }}</p>
        </div>

        <div class="rounded-lg border border-border p-4">
          <div class="mb-1 flex items-center gap-2 text-sm font-medium">
            批次号
            <Tag :color="review.batch_status === 'MATCH' ? 'green' : 'orange'" class="!mr-0">
              {{ review.batch_status === 'MATCH' ? '一致' : review.batch_status === 'MISMATCH' ? '不一致' : '无法核对' }}
            </Tag>
          </div>
          <p class="text-sm">报告：{{ review.report_batch_no || '未提取到' }} · 到货记录：{{ review.expected_batch_nos.join('、') || '未录入' }}</p>
        </div>

        <div v-if="review.checks.length" class="overflow-x-auto rounded-lg border border-border">
          <table class="w-full min-w-[850px] border-collapse text-left text-sm">
            <thead class="bg-muted/40 text-xs text-muted-foreground">
              <tr><th class="px-3 py-2 font-medium">检测项目</th><th class="px-3 py-2 font-medium">报告值</th><th class="px-3 py-2 font-medium">系统值</th><th class="px-3 py-2 font-medium">录入差异</th><th class="px-3 py-2 font-medium">标准要求</th><th class="px-3 py-2 font-medium">标准对照</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in review.checks" :key="item.item_name" class="border-t border-border align-top">
                <td class="px-3 py-3 font-medium">{{ item.item_name }}</td>
                <td class="px-3 py-3">{{ item.report_value || '—' }}</td>
                <td class="px-3 py-3">{{ item.recorded_value || '—' }}</td>
                <td class="px-3 py-3"><Tag :color="item.status === 'MATCH' ? 'green' : 'orange'">{{ checkLabel(item.status) }}</Tag></td>
                <td class="px-3 py-3">{{ item.standard_requirement || '—' }}</td>
                <td class="px-3 py-3"><Tag :color="item.standard_status === 'WITHIN_STANDARD' ? 'green' : item.standard_status === 'NOT_CONFIGURED' ? 'default' : 'orange'">{{ standardLabel(item.standard_status) }}</Tag></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="review.review_id" class="space-y-3 rounded-lg border border-border p-4">
          <h4 class="text-sm font-semibold">人工复核</h4>
          <p class="text-xs text-muted-foreground">确认表示已核查这份分析记录，不代表验收合格或库存放行。</p>
          <Input.TextArea v-model:value="reviewerNote" :rows="2" :maxlength="2000" :disabled="currentHistory?.status !== 'PENDING'" placeholder="填写核查依据、待补材料或修正意见" />
          <div v-if="currentHistory?.status === 'PENDING'" class="flex justify-end gap-2">
            <Button :loading="deciding" @click="decide('NEEDS_CORRECTION')">标记需修正</Button>
            <Button type="primary" :loading="deciding" @click="decide('CONFIRMED')">确认已复核</Button>
          </div>
          <Tag v-else :color="currentHistory?.status === 'CONFIRMED' ? 'green' : 'orange'">{{ currentHistory?.status === 'CONFIRMED' ? '已确认' : '需修正' }}</Tag>
        </div>

        <div v-if="review.checks.some((item) => item.source_quote)" class="rounded-lg border border-border p-4">
          <h4 class="mb-3 text-sm font-semibold">原文依据</h4>
          <div v-for="item in review.checks.filter((entry) => entry.source_quote)" :key="item.item_name" class="border-t border-border py-3 first:border-0 first:pt-0 last:pb-0">
            <div class="mb-1 text-xs font-medium text-muted-foreground">{{ item.item_name }} · {{ item.source_location || '正文' }}</div>
            <p class="whitespace-pre-wrap text-sm leading-6">{{ item.source_quote }}</p>
          </div>
        </div>
        <div v-if="canRecordResult" class="flex justify-end border-t border-border pt-4">
          <p v-if="!canPrefill" class="mr-auto text-xs text-muted-foreground">产品、批次未核实或包含多条明细时，请在验收表单手动录入检测值。</p>
          <Button type="primary" :disabled="!canPrefill" @click="continueToResult">带入候选值，继续录入</Button>
        </div>
      </section>
    </div>
  </Drawer>
</template>
