<script lang="ts" setup>
import type { QueryTrace } from './query-chart-plans';

import { computed } from 'vue';

import QueryChartCard from './query-chart-card.vue';
import { buildQueryCharts } from './query-chart-plans';

const props = defineProps<{ trace: QueryTrace }>();
const charts = computed(() => buildQueryCharts(props.trace));
const rows = computed(() => Array.isArray(props.trace.rows) ? props.trace.rows : []);
const columns = computed(() => props.trace.columns?.length
  ? props.trace.columns.filter((column) => column.key !== 'records')
  : Object.keys(rows.value[0] ?? {}).filter((key) => key !== 'records').map((key) => ({ key, label: key })));

function cell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}
</script>

<template>
  <div v-if="rows.length" class="mt-3 space-y-2">
    <div v-if="charts.length" class="grid gap-3" style="grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr))">
      <QueryChartCard v-for="(chart, index) in charts" :key="`${chart.title}-${index}`" :plan="chart" />
    </div>
    <p v-else-if="trace.dataset === 'inventory'" class="text-muted-foreground m-0 text-xs">
      这组库存汇总缺少逐行计量单位，无法安全比较数量；原始结果仍可查看。
    </p>
    <p v-if="charts.length && trace.truncated && trace.dataset !== 'overdue_unfulfilled_orders'" class="text-muted-foreground m-0 text-xs">
      图表仅根据本次返回的 {{ rows.length }} 行绘制，更多记录未计入。
    </p>
    <details
      v-if="columns.length"
      :open="trace.dataset === 'overdue_unfulfilled_orders'"
      class="rounded-md border border-border/70 bg-background/80 text-xs"
    >
      <summary class="text-muted-foreground cursor-pointer px-3 py-2 font-medium select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
        查看结构化数据（{{ rows.length }} 行）
      </summary>
      <div class="max-h-64 overflow-auto border-t border-border/70">
        <table class="w-full border-collapse text-left">
          <thead class="sticky top-0 bg-background">
            <tr>
              <th v-for="column in columns" :key="column.key" scope="col" class="whitespace-nowrap border-b border-border/70 px-3 py-2 font-medium">
                {{ column.label }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in rows" :key="rowIndex" class="border-b border-border/50 last:border-0">
              <td v-for="column in columns" :key="column.key" class="max-w-64 whitespace-nowrap px-3 py-2">
                {{ cell(row[column.key]) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  </div>
</template>
