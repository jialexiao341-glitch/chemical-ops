<script lang="ts" setup>
import type { DashboardApi } from '#/api';
import type { EchartsUIType } from '@vben/plugins/echarts';

import { nextTick, onMounted, ref, watch } from 'vue';

import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import { Empty } from 'antdv-next';

import { CATEGORICAL_COLORS, CHART_COLORS } from '#/constants/chart';
import { PURCHASE_ORDER_STATUS_DICT } from '#/constants/dictionary';
import { formatAmount } from '#/utils/format';

const props = defineProps<{ data: DashboardApi.StatusRow[] }>();

const chartRef = ref<EchartsUIType>();
const { renderEcharts } = useEcharts(chartRef);

/** 环形图中心展示订单总数 */
const total = () => (props.data ?? []).reduce((sum, row) => sum + row.order_count, 0);

function render() {
  const rows = props.data ?? [];
  if (rows.length === 0) {
    return;
  }
  renderEcharts({
    color: CATEGORICAL_COLORS,
    legend: { bottom: 0, icon: 'circle', left: 'center' },
    series: [
      {
        avoidLabelOverlap: true,
        data: rows.map((row) => ({
          name: PURCHASE_ORDER_STATUS_DICT.label(row.status),
          value: row.order_count,
        })),
        emphasis: {
          label: { fontSize: 14, fontWeight: 'bold', show: true },
        },
        itemStyle: { borderColor: '#fff', borderRadius: 6, borderWidth: 2 },
        label: { show: false, position: 'center' },
        radius: ['52%', '74%'],
        type: 'pie',
      },
    ],
    tooltip: {
      formatter: (params: any) => {
        const row = rows[params.dataIndex];
        if (!row) {
          return params.name;
        }
        return `${params.name}<br/>订单数：${row.order_count}<br/>金额：${formatAmount(row.order_amount)}`;
      },
      trigger: 'item',
    },
    // 用 title 在环形中心展示订单总数，比 graphic 更贴合 ECharts 的类型约定
    title: {
      left: 'center',
      subtext: '订单总数',
      subtextStyle: { color: CHART_COLORS.neutral, fontSize: 12 },
      text: String(total()),
      textStyle: {
        color: CHART_COLORS.ink,
        fontSize: 22,
        fontWeight: 600,
      },
      top: '40%',
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
  <Empty v-if="!data || data.length === 0" description="暂无订单状态数据" />
  <EchartsUI v-else ref="chartRef" height="300px" />
</template>
