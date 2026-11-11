<script lang="ts" setup>
import type { AgentApi } from '#/api';
import { computed, onMounted, ref } from 'vue';
import { Button, Select, Spin, message } from 'antdv-next';
import { getAgentQualitySummaryApi } from '#/api/ai/agent';

const days = ref(7);
const promptVersion = ref<string>();
const errorClass = ref<string>();
const tool = ref<string>();
const rating = ref<string>();
const loading = ref(false);
const summary = ref<AgentApi.QualitySummary>();
const dayOptions = [
  { label: '最近 7 天', value: 7 },
  { label: '最近 30 天', value: 30 },
  { label: '最近 90 天', value: 90 },
];
const errorClassLabels: Record<string, string> = {
  AMBIGUOUS_TIMEOUT: '响应超时待核对',
  AUTHORIZATION: '权限',
  BUDGET: '预算或范围',
  BUSINESS_INVALID: '业务输入或状态',
  FORMAT: '模型格式',
  TOOL_TIMEOUT: '工具超时',
  TRANSIENT_INFRA: '临时基础设施',
  UNKNOWN: '未知',
};
const recoveryLabels: Record<string, string> = {
  CONTACT_SUPPORT: '联系管理员',
  FIX_INPUT: '修正输入',
  NARROW_SCOPE: '缩小范围',
  REAUTH: '重新登录或授权',
  RETRY: '可重试',
  WAIT: '稍后核对',
};
const stageLabels: Record<string, string> = {
  budget: '预算',
  confirm: '证据与确认',
  context: '上下文',
  infra: '基础设施',
  planner: '规划生成',
  routing: '路由识别',
  tool: '工具调用',
  unknown: '未归类',
};
const reasonLabels: Record<string, string> = {
  FACT_ERROR: '事实错误',
  FORMAT: '格式问题',
  OTHER: '其他',
  SCOPE_ERROR: '范围错误',
  SLOW: '响应慢',
  TOOL_ERROR: '工具错误',
  UNSPECIFIED: '未填写原因',
};
const promptOptions = computed(() => (summary.value?.available_prompt_versions ?? [])
  .map((value) => ({ label: value, value })));
const errorClassOptions = computed(() => (summary.value?.available_error_classes ?? [])
  .map((value) => ({ label: errorClassLabels[value] ?? value, value })));
const toolOptions = computed(() => (summary.value?.available_tools ?? [])
  .map((value) => ({ label: value, value })));
const ratingOptions = [
  { label: '有帮助', value: 'UP' },
  { label: '没帮助', value: 'DOWN' },
];
const downRate = computed(() => summary.value?.down_rate == null
  ? '—'
  : `${Math.round(summary.value.down_rate * 1000) / 10}%`);
const conflict = computed(() => summary.value?.case_conflict ?? {
  ambiguous_rating: 0, down_on_success: 0, task_ids: [], total: 0,
});

async function load() {
  loading.value = true;
  try {
    summary.value = await getAgentQualitySummaryApi({
      days: days.value,
      error_class: errorClass.value,
      prompt_version: promptVersion.value,
      rating: rating.value as 'DOWN' | 'UP' | undefined,
      tool: tool.value,
    });
  } catch {
    message.error('读取质量聚合失败，请确认账号权限');
  } finally {
    loading.value = false;
  }
}

function reset() {
  days.value = 7;
  promptVersion.value = undefined;
  errorClass.value = undefined;
  tool.value = undefined;
  rating.value = undefined;
  void load();
}

onMounted(load);

function errorClassLabel(value: string) {
  return errorClassLabels[value] ?? value;
}

function recoveryLabel(value: string) {
  return recoveryLabels[value] ?? value;
}

function reasonLabel(value: string) {
  return reasonLabels[value] ?? value;
}

function stageLabel(value: string) {
  return stageLabels[value] ?? value;
}
</script>

<template>
  <section class="rounded bg-card p-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold">质量与失败</h2>
        <p class="text-muted-foreground mt-1 text-xs">
          聚合失败任务、错误分类、工具调用和用户反馈；只展示计数与任务编号，不含问题原文和用户身份。
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <Select v-model:value="days" :options="dayOptions" class="w-32" />
        <Select v-model:value="promptVersion" :options="promptOptions" allow-clear placeholder="全部 prompt 版本" class="w-52" />
        <Select v-model:value="errorClass" :options="errorClassOptions" allow-clear placeholder="全部错误类别" class="w-44" />
        <Select v-model:value="tool" :options="toolOptions" allow-clear placeholder="全部工具" class="w-52" />
        <Select v-model:value="rating" :options="ratingOptions" allow-clear placeholder="全部反馈" class="w-36" />
        <Button @click="reset">重置</Button>
        <Button type="primary" :loading="loading" @click="load">查询</Button>
      </div>
    </div>

    <Spin :spinning="loading">
      <template v-if="summary">
        <p v-if="summary.truncated" class="text-amber-700 mt-3 text-xs" role="status">
          统计窗口内任务超过 5000 条，仅统计最近 5000 条；请缩短时间范围后复核。
        </p>
        <div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div class="rounded border border-border p-3">
            <p class="text-muted-foreground text-xs">任务数</p>
            <p class="mt-1 text-2xl font-semibold">{{ summary.tasks }}</p>
          </div>
          <div class="rounded border border-border p-3">
            <p class="text-muted-foreground text-xs">失败任务</p>
            <p class="mt-1 text-2xl font-semibold">{{ summary.failed_tasks }}</p>
          </div>
          <div class="rounded border border-border p-3">
            <p class="text-muted-foreground text-xs">反馈数</p>
            <p class="mt-1 text-2xl font-semibold">{{ summary.feedback }}</p>
          </div>
          <div class="rounded border border-border p-3">
            <p class="text-muted-foreground text-xs">没帮助占比</p>
            <p class="mt-1 text-2xl font-semibold">{{ downRate }}</p>
          </div>
        </div>

        <div class="mt-4 grid gap-4 lg:grid-cols-2">
          <div class="rounded border border-border p-3">
            <h3 class="mb-2 text-sm font-medium">错误类别</h3>
            <table class="w-full text-sm">
              <tbody>
                <tr v-for="row in summary.by_error_class" :key="`class-${row.key}`" class="border-t border-border/60">
                  <td class="py-1.5">{{ errorClassLabel(row.key) }}</td>
                  <td class="py-1.5 text-right">{{ row.count }}</td>
                </tr>
                <tr v-if="!summary.by_error_class.length">
                  <td class="text-muted-foreground py-2">暂无数据</td>
                </tr>
              </tbody>
            </table>
            <h3 class="mb-2 mt-4 text-sm font-medium">恢复建议</h3>
            <table class="w-full text-sm">
              <tbody>
                <tr v-for="row in summary.by_recovery" :key="`recovery-${row.key}`" class="border-t border-border/60">
                  <td class="py-1.5">{{ recoveryLabel(row.key) }}</td>
                  <td class="py-1.5 text-right">{{ row.count }}</td>
                </tr>
                <tr v-if="!summary.by_recovery.length">
                  <td class="text-muted-foreground py-2">暂无数据</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="rounded border border-border p-3">
            <h3 class="mb-2 text-sm font-medium">错误码与失败样本</h3>
            <table class="w-full text-sm">
              <thead>
                <tr class="text-muted-foreground text-xs">
                  <th class="py-1 text-left font-normal">错误码</th>
                  <th class="py-1 text-right font-normal">次数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in summary.by_error_code" :key="`code-${row.key}`" class="border-t border-border/60">
                  <td class="py-1.5 break-all">{{ row.key }}</td>
                  <td class="py-1.5 text-right">{{ row.count }}</td>
                </tr>
                <tr v-if="!summary.by_error_code.length">
                  <td class="text-muted-foreground py-2" colspan="2">暂无数据</td>
                </tr>
              </tbody>
            </table>
            <details v-if="Object.keys(summary.samples).length" class="mt-2 text-xs">
              <summary class="text-muted-foreground cursor-pointer">失败样本任务编号（每类最多 5 条）</summary>
              <p v-for="(ids, code) in summary.samples" :key="code" class="mt-1 break-all">
                <span class="font-medium">{{ code }}</span>：{{ ids.join('、') }}
              </p>
            </details>
          </div>

          <div class="rounded border border-border p-3">
            <h3 class="mb-2 text-sm font-medium">反馈原因</h3>
            <table class="w-full text-sm">
              <tbody>
                <tr v-for="row in summary.by_feedback_reason" :key="`reason-${row.key}`" class="border-t border-border/60">
                  <td class="py-1.5">{{ reasonLabel(row.key) }}</td>
                  <td class="py-1.5 text-right">{{ row.count }}</td>
                </tr>
                <tr v-if="!summary.by_feedback_reason.length">
                  <td class="text-muted-foreground py-2">暂无数据</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="rounded border border-border p-3">
            <h3 class="mb-2 text-sm font-medium">按 prompt 版本</h3>
            <table class="w-full text-sm">
              <tbody>
                <tr v-for="row in summary.by_prompt_version" :key="`prompt-${row.key}`" class="border-t border-border/60">
                  <td class="py-1.5 break-all">{{ row.key }}</td>
                  <td class="py-1.5 text-right">{{ row.count }}</td>
                </tr>
                <tr v-if="!summary.by_prompt_version.length">
                  <td class="text-muted-foreground py-2">暂无数据</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="rounded border border-border p-3">
            <h3 class="mb-2 text-sm font-medium">按失败阶段</h3>
            <table class="w-full text-sm">
              <tbody>
                <tr v-for="row in summary.by_failure_stage" :key="`stage-${row.key}`" class="border-t border-border/60">
                  <td class="py-1.5">{{ stageLabel(row.key) }}</td>
                  <td class="py-1.5 text-right">{{ row.count }}</td>
                </tr>
                <tr v-if="!summary.by_failure_stage?.length">
                  <td class="text-muted-foreground py-2">暂无数据</td>
                </tr>
              </tbody>
            </table>
            <p class="text-muted-foreground mt-2 text-xs">
              只按错误码确定性归因，表示问题先坏在哪一段；不判定业务责任。
            </p>
          </div>

          <div class="rounded border border-border p-3">
            <h3 class="mb-2 text-sm font-medium">评价冲突</h3>
            <table class="w-full text-sm">
              <tbody>
                <tr class="border-t border-border/60">
                  <td class="py-1.5">同一任务同时有帮助/没帮助</td>
                  <td class="py-1.5 text-right">{{ conflict.ambiguous_rating }}</td>
                </tr>
                <tr class="border-t border-border/60">
                  <td class="py-1.5">标记没帮助但任务成功</td>
                  <td class="py-1.5 text-right">{{ conflict.down_on_success }}</td>
                </tr>
                <tr class="border-t border-border/60">
                  <td class="py-1.5">去重合计</td>
                  <td class="py-1.5 text-right">{{ conflict.total }}</td>
                </tr>
              </tbody>
            </table>
            <details v-if="conflict.task_ids?.length" class="mt-2 text-xs">
              <summary class="text-muted-foreground cursor-pointer">冲突任务编号（最多 50 条）</summary>
              <p class="mt-1 break-all">{{ conflict.task_ids.join('、') }}</p>
            </details>
            <p class="text-muted-foreground mt-2 text-xs">
              只标记评价与状态不一致，供人工复核；不作为自动判定。
            </p>
          </div>

          <div class="rounded border border-border p-3 lg:col-span-2">
            <h3 class="mb-2 text-sm font-medium">按工具调用</h3>
            <div class="flex flex-wrap gap-2">
              <span v-for="row in summary.by_tool" :key="`tool-${row.key}`" class="rounded border border-border/70 px-2 py-1 text-xs">
                {{ row.key }} · {{ row.count }}
              </span>
              <span v-if="!summary.by_tool.length" class="text-muted-foreground text-sm">暂无数据</span>
            </div>
          </div>
        </div>

        <p class="text-muted-foreground mt-4 text-xs">
          筛选条件：{{ summary.filters.prompt_version || '全部版本' }} · {{ summary.filters.error_class || '全部错误类别' }} ·
          {{ summary.filters.tool || '全部工具' }} · {{ summary.filters.rating ? (summary.filters.rating === 'DOWN' ? '没帮助' : '有帮助') : '全部反馈' }}
        </p>
      </template>
    </Spin>
  </section>
</template>
