<script lang="ts" setup>
import type { DashboardApi } from '#/api';
import type { EchartsUIType } from '@vben/plugins/echarts';

import { nextTick, onMounted, ref, watch } from 'vue';

import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import { Empty } from 'antdv-next';

import { CHART_BASE, CHART_COLORS } from '#/constants/chart';
import { formatAmount } from '#/utils/format';

const props = defineProps<{ data: DashboardApi.TrendRow[] }>();

const chartRef = ref<EchartsUIType>();
const { renderEcharts } = useEcharts(chartRef);

function render() {
  const rows = props.data ?? [];
  if (rows.length === 0) {
    return;
  }
  renderEcharts({
    grid: { bottom: 30, containLabel: true, left: 10, right: 20, top: 40 },
    legend: { data: ['采购金额', '订单数'], right: 10, top: 4 },
    series: [
      {
        barMaxWidth: 26,
        data: rows.map((row) => Number(row.order_amount)),
        itemStyle: { borderRadius: [4, 4, 0, 0], color: CHART_COLORS.primarySoft },
        name: '采购金额',
        type: 'bar',
      },
      {
        data: rows.map((row) => row.order_count),
        itemStyle: { color: CHART_COLORS.primary },
        name: '订单数',
        smooth: true,
        symbolSize: 6,
        type: 'line',
        yAxisIndex: 1,
      },
    ],
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: any) => formatAmount(value),
    },
    xAxis: {
      ...CHART_BASE,
      axisLabel: {
        ...CHART_BASE.axisLabel,
        // 半年区间按天出数据：首标保留年份，其余只显示月-日，并自动隐藏重叠标签
        formatter: (value: string, index: number) =>
          index === 0 ? value : String(value).slice(5),
        hideOverlap: true,
      },
      axisTick: { show: false },
      data: rows.map((row) => row.date),
      type: 'category' as const,
    },
    yAxis: [
      // 不再渲染轴名称：默认 nameLocation 会把它画在轴顶端，
      // 与顶部刻度数值、右上角图例文字直接重叠；序列含义由图例与 tooltip 承担
      {
        ...CHART_BASE,
        axisLine: { show: false },
        type: 'value' as const,
      },
      {
        ...CHART_BASE,
        axisLine: { show: false },
        splitLine: { show: false },
        type: 'value' as const,
      },
    ],
  });
}

onMounted(() => nextTick(render));
watch(
  () => props.data,
  () => nextTick(render),
  { deep: true },
);
</script>

<template>
  <Empty v-if="!data || data.length === 0" description="所选区间没有采购数据" />
  <figure v-else>
    <figcaption class="sr-only">采购趋势：<span v-for="row in data" :key="row.date">{{ row.date }}，采购金额 {{ formatAmount(row.order_amount) }}，订单数 {{ row.order_count }}；</span></figcaption>
    <EchartsUI ref="chartRef" height="300px" />
  </figure>
</template>
