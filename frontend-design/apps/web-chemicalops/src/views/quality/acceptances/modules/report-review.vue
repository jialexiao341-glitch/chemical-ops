<script lang="ts" setup>
import type { QualityAcceptanceApi } from '#/api';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { Alert, Button, Select, Spin, Tag, message } from 'antdv-next';

import {
  downloadAcceptanceReportApi,
  getAcceptanceReportFilesApi,
  reviewAcceptanceReportApi,
  uploadAcceptanceReportApi,
} from '#/api';

const emit = defineEmits(['continue']);
const acceptance = ref<null | QualityAcceptanceApi.Acceptance>(null);
const files = ref<QualityAcceptanceApi.ReportFile[]>([]);
const selectedFileId = ref<number>();
const review = ref<null | QualityAcceptanceApi.ReportReview>(null);
const loadingFiles = ref(false);
const uploading = ref(false);
const reviewing = ref(false);
const fileInput = ref<HTMLInputElement>();

const title = computed(() => `核对报告 · ${acceptance.value?.acceptance_no ?? ''}`);
const selectedFile = computed(() => files.value.find((item) => item.id === selectedFileId.value));
const mismatchCount = computed(() => review.value?.checks.filter((item) => item.status !== 'MATCH').length ?? 0);
const canRecordResult = computed(() => !acceptance.value?.result || ['PENDING', 'REINSPECTION'].includes(acceptance.value.result));

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

const [Drawer, drawerApi] = useVbenDrawer<null | QualityAcceptanceApi.Acceptance>({
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    acceptance.value = drawerApi.getData() ?? null;
    review.value = null;
    files.value = [];
    selectedFileId.value = undefined;
    if (acceptance.value) await loadFiles(acceptance.value.id);
  },
});

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

async function runReview() {
  if (!acceptance.value || !selectedFileId.value) return;
  reviewing.value = true;
  review.value = null;
  try {
    review.value = await reviewAcceptanceReportApi(acceptance.value.id, selectedFileId.value);
  } catch {
    // 请求层已显示解析或 AI 服务错误。
  } finally {
    reviewing.value = false;
  }
}

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

function checkLabel(status: QualityAcceptanceApi.ReportCheck['status']) {
  return {
    MATCH: '一致',
    MISMATCH: '值不一致',
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
        description="提取报告原文，与当前验收单已录入的数据比较。请依据原始报告复核；此处不会提交验收结论。"
      />

      <section class="rounded-lg border border-border p-4">
        <h3 class="mb-3 text-sm font-semibold">选择当前验收单的报告</h3>
        <Spin :spinning="loadingFiles">
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
            <Button type="primary" :disabled="!selectedFileId" :loading="reviewing" @click="runReview">开始核对</Button>
          </div>
        </Spin>
        <p class="mt-2 text-xs text-muted-foreground">支持可提取文字的 PDF、DOCX、XLSX 和文本报告；扫描件需启用文档识别服务。</p>
      </section>

      <section v-if="review" class="space-y-4" aria-live="polite">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 class="text-base font-semibold">核对结果</h3>
            <p class="text-xs text-muted-foreground">{{ review.file_name }} · {{ review.checks.length }} 项检测值 · {{ mismatchCount }} 项待复核</p>
          </div>
          <Tag :color="mismatchCount || review.batch_status === 'MISMATCH' ? 'orange' : 'blue'" class="!mr-0">
            {{ mismatchCount || review.batch_status === 'MISMATCH' ? '需要人工复核' : '已完成只读核对' }}
          </Tag>
        </div>

        <Alert v-for="warning in review.warnings" :key="warning" type="warning" show-icon :message="warning" />

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
          <table class="w-full min-w-[650px] border-collapse text-left text-sm">
            <thead class="bg-muted/40 text-xs text-muted-foreground">
              <tr><th class="px-3 py-2 font-medium">检测项目</th><th class="px-3 py-2 font-medium">报告值</th><th class="px-3 py-2 font-medium">系统值</th><th class="px-3 py-2 font-medium">核对</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in review.checks" :key="item.item_name" class="border-t border-border align-top">
                <td class="px-3 py-3 font-medium">{{ item.item_name }}</td>
                <td class="px-3 py-3">{{ item.report_value || '—' }}</td>
                <td class="px-3 py-3">{{ item.recorded_value || '—' }}</td>
                <td class="px-3 py-3"><Tag :color="item.status === 'MATCH' ? 'green' : 'orange'">{{ checkLabel(item.status) }}</Tag></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="review.checks.some((item) => item.source_quote)" class="rounded-lg border border-border p-4">
          <h4 class="mb-3 text-sm font-semibold">原文依据</h4>
          <div v-for="item in review.checks.filter((entry) => entry.source_quote)" :key="item.item_name" class="border-t border-border py-3 first:border-0 first:pt-0 last:pb-0">
            <div class="mb-1 text-xs font-medium text-muted-foreground">{{ item.item_name }} · {{ item.source_location || '正文' }}</div>
            <p class="whitespace-pre-wrap text-sm leading-6">{{ item.source_quote }}</p>
          </div>
        </div>
        <div v-if="canRecordResult" class="flex justify-end border-t border-border pt-4">
          <Button type="primary" @click="continueToResult">带入候选值，继续录入</Button>
        </div>
      </section>
    </div>
  </Drawer>
</template>
