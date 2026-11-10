<script lang="ts" setup>
import type { AgentApi } from '#/api';
import { computed, onMounted, ref, watch } from 'vue';
import { Select, Spin, message } from 'antdv-next';
import { getAgentCostSummaryApi } from '#/api/ai/agent';

const days = ref(30);
const loading = ref(false);
const summary = ref<AgentApi.CostSummary>();
const dayOptions = [
  { label: '最近 7 天', value: 7 },
  { label: '最近 30 天', value: 30 },
  { label: '最近 90 天', value: 90 },
];

async function load() {
  loading.value = true;
  try {
    summary.value = await getAgentCostSummaryApi(days.value);
  } catch {
    message.error('读取成本聚合失败，请确认账号权限');
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(days, load);

function formatNumber(value?: null | number) {
  return value == null ? '—' : value.toLocaleString('zh-CN');
}

function formatRate(value?: null | number) {
  return value == null ? '—' : `${Math.round(value * 1000) / 10}%`;
}

function formatCost(value?: null | number) {
  return value == null ? '—' : value.toFixed(4);
}

function formatSeconds(value?: null | number) {
  return value == null ? '—' : value.toFixed(2);
}

function groupName(row: AgentApi.CostGroup) {
  return row.scene ?? row.model ?? row.prompt_version ?? 'unknown';
}

const successRate = computed(() => {
  const item = summary.value?.summary;
  return item ? formatRate(item.success_rate) : '—';
});
</script>

<template>
  <section class="rounded bg-card p-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold">成本看板</h2>
        <p class="text-muted-foreground mt-1 text-xs">
          只读任务运行信息，按场景、模型和 prompt 版本聚合；不展示任务原文和用户身份。
        </p>
      </div>
      <Select v-model:value="days" :options="dayOptions" class="w-36" />
    </div>

    <Spin :spinning="loading">
      <template v-if="summary">
        <div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div class="rounded border border-border p-3">
            <p class="text-muted-foreground text-xs">任务数</p>
            <p class="mt-1 text-2xl font-semibold">{{ summary.summary.tasks }}</p>
          </div>
          <div class="rounded border border-border p-3">
            <p class="text-muted-foreground text-xs">成功率</p>
            <p class="mt-1 text-2xl font-semibold">{{ successRate }}</p>
          </div>
          <div class="rounded border border-border p-3">
            <p class="text-muted-foreground text-xs">总 token</p>
            <p class="mt-1 text-2xl font-semibold">{{ formatNumber(summary.summary.total_tokens) }}</p>
          </div>
          <div class="rounded border border-border p-3">
            <p class="text-muted-foreground text-xs">估算费用</p>
            <p class="mt-1 text-2xl font-semibold">{{ formatCost(summary.summary.estimated_cost) }}</p>
            <p v-if="!summary.pricing.configured" class="text-muted-foreground mt-1 text-xs">未配置单价</p>
          </div>
        </div>

        <p class="text-muted-foreground mt-3 text-xs">
          输入 {{ formatNumber(summary.summary.input_tokens) }} · 输出
          {{ formatNumber(summary.summary.output_tokens) }} · P50 / P95 墙钟
          {{ formatSeconds(summary.summary.p50_seconds) }} / {{ formatSeconds(summary.summary.p95_seconds) }} 秒
        </p>

        <div class="mt-4 grid gap-4 lg:grid-cols-3">
          <div v-for="group in [
            { title: '按场景', key: 'scene', rows: summary.by_scene },
            { title: '按模型', key: 'model', rows: summary.by_model },
            { title: '按 prompt 版本', key: 'prompt_version', rows: summary.by_prompt_version },
          ]" :key="group.key" class="rounded border border-border p-3">
            <h3 class="mb-2 text-sm font-medium">{{ group.title }}</h3>
            <table class="w-full text-sm">
              <thead>
                <tr class="text-muted-foreground text-xs">
                  <th class="py-1 text-left font-normal">分组</th>
                  <th class="py-1 text-right font-normal">任务</th>
                  <th class="py-1 text-right font-normal">总 token</th>
                  <th class="py-1 text-right font-normal">费用</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in group.rows" :key="groupName(row)" class="border-t border-border/60">
                  <td class="max-w-40 truncate py-1.5" :title="groupName(row)">{{ groupName(row) }}</td>
                  <td class="py-1.5 text-right">{{ row.tasks }}</td>
                  <td class="py-1.5 text-right">{{ formatNumber(row.total_tokens) }}</td>
                  <td class="py-1.5 text-right">{{ formatCost(row.estimated_cost) }}</td>
                </tr>
                <tr v-if="!group.rows.length">
                  <td class="text-muted-foreground py-2" colspan="4">暂无数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <p class="text-muted-foreground mt-4 text-xs">
          用量覆盖：有 run_meta 用量 {{ summary.coverage.run_meta_usage }} / {{ summary.coverage.tasks }}；
          仅 token_budget 总量 {{ summary.coverage.token_budget_only }}；无用量 {{ summary.coverage.unmetered }}；
          无任务记录 {{ summary.coverage.missing }}。缺输入/输出拆分或旧任务不估算费用。
        </p>
      </template>
    </Spin>
  </section>
</template>