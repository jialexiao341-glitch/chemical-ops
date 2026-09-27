<script lang="ts" setup>
import type { EchartsUIType } from '@vben/plugins/echarts';
import type { QueryChartPlan } from './query-chart-plans';

import { nextTick, onMounted, ref, watch } from 'vue';

import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import { CATEGORICAL_COLORS, CHART_COLORS } from '#/constants/chart';

const props = defineProps<{ plan: QueryChartPlan }>();
const chartRef = ref<EchartsUIType>();
const { renderEcharts } = useEcharts(chartRef);
const format = (value: unknown) => {
  const amount = Number(value);
  return Number.isFinite(amount)
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(amount)
    : String(value ?? '-');
};

function render() {
  const plan = props.plan;
  const textColor = getComputedStyle(document.body).color || CHART_COLORS.ink;
  const axisBase = {
    axisLabel: { color: textColor, fontSize: 11 },
    axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.35)' } },
    splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.25)', type: 'dashed' as const } },
  };
  if (plan.type === 'donut') {
    const values = plan.series[0]?.values ?? [];
    renderEcharts({
      aria: { enabled: true },
      color: CATEGORICAL_COLORS,
      legend: { bottom: 0, icon: 'circle', left: 'center', textStyle: { color: textColor }, type: 'scroll' },
      series: [{
        data: plan.labels.map((name, index) => ({ name, value: values[index] ?? 0 })),
        itemStyle: { borderColor: '#fff', borderRadius: 5, borderWidth: 2 },
        label: { show: false },
        radius: ['48%', '70%'],
        type: 'pie',
      }],
      tooltip: {
        trigger: 'item',
        valueFormatter: (value: unknown) => `${format(value)}${plan.unit ? ` ${plan.unit}` : ''}`,
      },
    });
    return;
  }

  const horizontal = plan.type === 'bar' && plan.horizontal;
  const categoryAxis = {
    ...axisBase,
    axisLabel: { ...axisBase.axisLabel, hideOverlap: true, overflow: 'truncate' as const, width: horizontal ? 140 : 75 },
    axisTick: { show: false },
    data: horizontal ? [...plan.labels].reverse() : plan.labels,
    type: 'category' as const,
  };
  const valueAxis = {
    ...axisBase,
    axisLine: { show: false },
    type: 'value' as const,
  };
  renderEcharts({
    aria: { enabled: true },
    color: CATEGORICAL_COLORS,
    grid: { bottom: plan.series.length > 1 ? 34 : 14, containLabel: true, left: 8, right: 18, top: 16 },
    legend: plan.series.length > 1 ? { bottom: 0, icon: 'roundRect', left: 'center', textStyle: { color: textColor } } : { show: false },
    series: plan.series.map((series, index) => ({
      barMaxWidth: 18,
      data: horizontal ? [...series.values].reverse() : series.values,
      itemStyle: { color: CATEGORICAL_COLORS[index % CATEGORICAL_COLORS.length] || CHART_COLORS.primary },
      name: series.name,
      showSymbol: true,
      smooth: plan.type === 'line',
      symbolSize: 7,
      type: plan.type === 'line' ? 'line' as const : 'bar' as const,
    })),
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: unknown) => `${format(value)}${plan.unit ? ` ${plan.unit}` : ''}`,
    },
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? categoryAxis : valueAxis,
  });
}

onMounted(() => nextTick(render));
watch(() => props.plan, () => nextTick(render), { deep: true });
</script>

<template>
  <section class="min-w-0 rounded-lg border border-border/70 bg-background p-3" :aria-label="plan.title">
    <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <h4 class="m-0 text-sm font-semibold text-foreground">{{ plan.title }}</h4>
      <span v-if="plan.unit" class="text-muted-foreground text-xs">单位：{{ plan.unit }}</span>
    </div>
    <p v-if="plan.note" class="text-muted-foreground m-0 mt-1 text-xs leading-5">{{ plan.note }}</p>
    <EchartsUI ref="chartRef" height="260px" />
  </section>
</template>
