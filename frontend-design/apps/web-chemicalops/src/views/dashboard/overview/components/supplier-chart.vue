<script lang="ts" setup>
import type { DashboardApi } from '#/api';
import type { EchartsUIType } from '@vben/plugins/echarts';

import { computed, nextTick, onMounted, ref, watch } from 'vue';

import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import { Empty } from 'antdv-next';

import { CHART_BASE, CHART_COLORS } from '#/constants/chart';
import { formatAmount } from '#/utils/format';

const props = defineProps<{ data: DashboardApi.SupplierRow[] }>();

const chartRef = ref<EchartsUIType>();
const { renderEcharts } = useEcharts(chartRef);

/** 取采购额前 8 名，横向条形图更适合展示供应商名称 */
const rows = computed(() =>
  [...(props.data ?? [])]
    .sort((a, b) => Number(b.order_amount) - Number(a.order_amount))
    .slice(0, 8)
    .reverse(),
);

function render() {
  if (rows.value.length === 0) {
    return;
  }
  renderEcharts({
    grid: { bottom: 10, containLabel: true, left: 10, right: 40, top: 20 },
    series: [
      {
        barMaxWidth: 18,
        data: rows.value.map((row) => Number(row.order_amount)),
        itemStyle: { borderRadius: [0, 4, 4, 0], color: CHART_COLORS.primary },
        label: {
          formatter: (params: any) => formatAmount(params.value),
          position: 'right',
          show: true,
          color: CHART_COLORS.neutral,
          fontSize: 11,
        },
        name: '采购金额',
        type: 'bar',
      },
    ],
    tooltip: {
      formatter: (params: any) => {
        const row = rows.value[params.dataIndex];
        if (!row) {
          return '';
        }
        return `${row.supplier_name}<br/>采购额：${formatAmount(row.order_amount)}<br/>订单数：${row.order_count}<br/>逾期到货：${row.overdue_deliveries}`;
      },
      trigger: 'axis',
    },
    xAxis: {
      ...CHART_BASE,
      axisLabel: { show: false },
      splitLine: { show: true },
      type: 'value',
    },
    yAxis: {
      ...CHART_BASE,
      axisLabel: { ...CHART_BASE.axisLabel, width: 110, overflow: 'truncate' },
      axisLine: { show: false },
      axisTick: { show: false },
      data: rows.value.map((row) => row.supplier_name),
      splitLine: { show: false },
      type: 'category',
    },
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
  <Empty v-if="!data || data.length === 0" description="暂无供应商采购数据" />
  <EchartsUI v-else ref="chartRef" height="320px" />
</template>
