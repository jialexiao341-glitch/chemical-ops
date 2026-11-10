<script lang="ts" setup>
import type { AgentApi } from '#/api';
import { computed, onMounted, ref, watch } from 'vue';
import { Select, Spin, message } from 'antdv-next';
import { getAgentFeedbackAdminSummaryApi } from '#/api/ai/agent';

const days = ref(7);
const loading = ref(false);
const summary = ref<AgentApi.FeedbackAdminSummary>();
const dayOptions = [
  { label: '最近 7 天', value: 7 },
  { label: '最近 30 天', value: 30 },
  { label: '最近 90 天', value: 90 },
];

async function load() {
  loading.value = true;
  try {
    summary.value = await getAgentFeedbackAdminSummaryApi(days.value);
  } catch {
    message.error('读取反馈聚合失败，请确认账号权限');
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(days, load);

function rows(record?: Record<string, number>) {
  return Object.entries(record ?? {})
    .sort((a, b) => b[1] - a[1])
    .map(([key, count]) => ({ key, count }));
}

const upRate = computed(() => {
  const total = summary.value?.total ?? 0;
  return total ? `${Math.round(((summary.value?.up ?? 0) / total) * 100)}%` : '—';
});
</script>

<template>
  <section class="rounded bg-card p-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold">反馈看板</h2>
        <p class="text-muted-foreground mt-1 text-xs">
          跨用户聚合，只统计评分、原因、prompt 版本和模型，不展示用户身份与反馈原文。
        </p>
      </div>
      <Select v-model:value="days" :options="dayOptions" class="w-36" />
    </div>

    <Spin :spinning="loading">
      <div v-if="summary" class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="rounded border border-border p-3">
          <p class="text-muted-foreground text-xs">反馈总数</p>
          <p class="mt-1 text-2xl font-semibold">{{ summary.total }}</p>
        </div>
        <div class="rounded border border-border p-3">
          <p class="text-muted-foreground text-xs">参与用户</p>
          <p class="mt-1 text-2xl font-semibold">{{ summary.users }}</p>
        </div>
        <div class="rounded border border-border p-3">
          <p class="text-muted-foreground text-xs">没帮助</p>
          <p class="mt-1 text-2xl font-semibold">{{ summary.down }}</p>
        </div>
        <div class="rounded border border-border p-3">
          <p class="text-muted-foreground text-xs">有帮助占比</p>
          <p class="mt-1 text-2xl font-semibold">{{ upRate }}</p>
        </div>
      </div>

      <div v-if="summary" class="mt-4 grid gap-4 lg:grid-cols-2">
        <div class="rounded border border-border p-3">
          <h3 class="mb-2 text-sm font-medium">没帮助原因</h3>
          <table class="w-full text-sm">
            <tbody>
              <tr v-for="item in rows(summary.by_reason)" :key="item.key" class="border-t border-border/60">
                <td class="py-1.5">{{ item.key }}</td>
                <td class="py-1.5 text-right">{{ item.count }}</td>
              </tr>
              <tr v-if="!rows(summary.by_reason).length">
                <td class="text-muted-foreground py-2">暂无数据</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="rounded border border-border p-3">
          <h3 class="mb-2 text-sm font-medium">按 prompt 版本</h3>
          <table class="w-full text-sm">
            <tbody>
              <tr v-for="item in rows(summary.by_prompt_version)" :key="item.key" class="border-t border-border/60">
                <td class="py-1.5 break-all">{{ item.key }}</td>
                <td class="py-1.5 text-right">{{ item.count }}</td>
              </tr>
              <tr v-if="!rows(summary.by_prompt_version).length">
                <td class="text-muted-foreground py-2">暂无数据</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="rounded border border-border p-3">
          <h3 class="mb-2 text-sm font-medium">按模型</h3>
          <table class="w-full text-sm">
            <tbody>
              <tr v-for="item in rows(summary.by_model)" :key="item.key" class="border-t border-border/60">
                <td class="py-1.5">{{ item.key }}</td>
                <td class="py-1.5 text-right">{{ item.count }}</td>
              </tr>
              <tr v-if="!rows(summary.by_model).length">
                <td class="text-muted-foreground py-2">暂无数据</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </Spin>
  </section>
</template>
