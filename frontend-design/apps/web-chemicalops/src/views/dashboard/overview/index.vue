<script lang="ts" setup>
import type { DashboardApi } from '#/api';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Button, Card, DatePicker, Empty, Spin, Table, Tag } from 'antdv-next';

import {
  getDashboardOverviewApi,
  getDashboardReportApi,
  getHealthApi,
} from '#/api';
import { EXPIRY_ALERT_LEVEL_DICT } from '#/constants/dictionary';
import { formatAmount, formatDate, formatQuantity } from '#/utils/format';

import StatCard from './components/stat-card.vue';
import StatusChart from './components/status-chart.vue';
import SupplierChart from './components/supplier-chart.vue';
import TrendChart from './components/trend-chart.vue';

defineOptions({ name: 'DashboardOverview' });

const overview = ref<DashboardApi.Overview>();
const report = ref<DashboardApi.Report>();
const health = ref<{ data_mode: string; environment: string }>();
const loading = ref(false);
const range = ref<[string, string]>();

/** 默认展示最近 6 个月 */
function defaultRange(): [string, string] {
  const end = new Date();
  const start = new Date();
  start.setMonth(start.getMonth() - 5);
  start.setDate(1);
  const pad = (n: number) => String(n).padStart(2, '0');
  const fmt = (d: Date) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return [fmt(start), fmt(end)];
}

/** 库存按计量单位汇总展示，避免把不同单位直接相加 */
const inventoryText = computed(() => {
  const units = overview.value?.inventory_units ?? [];
  if (units.length === 0) {
    return formatQuantity(overview.value?.inventory_quantity);
  }
  return units
    .map((unit) => `${formatQuantity(unit.quantity)} ${unit.unit_name}`)
    .join(' / ');
});

const expiryAlertTone = computed<'success' | 'warning'>(() =>
  Number(overview.value?.expiry_alerts ?? 0) > 0 ? 'warning' : 'success',
);

const paidAmountText = computed(() => {
  const amount = overview.value?.paid_amount;
  return amount === null || amount === undefined
    ? '-'
    : `¥${formatAmount(amount)}`;
});

const isDemo = computed(() => health.value?.data_mode === 'demo');

const pendingTaskLabels: Record<string, string> = {
  PURCHASE_ORDER_APPROVAL: '采购订单待审批',
  QUALITY_ACCEPTANCE: '到货质量待验收',
  DELIVERY_CONFIRMATION: '到货待确认',
  OPEN_EXCEPTION: '待处理异常',
  INVENTORY_EXPIRY: '库存临期预警',
};

function pendingTaskLabel(taskType: string) {
  return pendingTaskLabels[taskType] ?? '其他待办';
}

async function load() {
  loading.value = true;
  try {
    const [overviewData, reportData] = await Promise.all([
      getDashboardOverviewApi(),
      getDashboardReportApi(
        range.value
          ? { date_from: range.value[0], date_to: range.value[1] }
          : undefined,
      ),
    ]);
    overview.value = overviewData;
    report.value = reportData;
  } finally {
    loading.value = false;
  }
}

function onRangeChange() {
  load();
}

const alertColumns = [
  { key: 'product_name', title: '产品', minWidth: 160 },
  { key: 'quantity', title: '数量', width: 120, align: 'right' as const },
  { key: 'unit_name', title: '单位', width: 90 },
  { key: 'expiry_date', title: '有效期至', width: 120 },
  { key: 'days_remaining', title: '剩余天数', width: 110 },
  { key: 'level', title: '预警级别', width: 130 },
];

onMounted(async () => {
  range.value = defaultRange();
  // 健康检查失败不应阻塞看板，因此单独请求
  getHealthApi()
    .then((res) => {
      health.value = res;
    })
    .catch(() => {
      health.value = undefined;
    });
  await load();
});
</script>

<template>
  <Page auto-content-height>
    <Spin :spinning="loading">
      <div class="space-y-4">
        <!-- 页面标题与筛选 -->
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <h1 class="m-0 text-xl font-semibold tracking-normal">运营总览</h1>
            <Tag v-if="health" class="m-0 border-0 bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
              <span
                class="mr-1 inline-block size-1.5 rounded-full align-middle"
                :class="isDemo ? 'bg-amber-500' : 'bg-emerald-500'"
              />
              {{ isDemo ? '演示数据' : '生产数据' }} · {{ health.environment }}
            </Tag>
          </div>
          <div class="flex items-center gap-2">
            <DatePicker.RangePicker
              v-model:value="range"
              value-format="YYYY-MM-DD"
              @change="onRangeChange"
            />
            <Button :loading="loading" @click="load">刷新</Button>
          </div>
        </div>

        <!-- KPI 行 -->
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            icon="lucide:clipboard-list"
            title="采购订单总数"
            :value="overview?.purchase_orders_total ?? '-'"
          />
          <StatCard
            icon="lucide:truck"
            title="进行中订单"
            tone="primary"
            :value="overview?.purchase_orders_in_progress ?? '-'"
          />
          <StatCard
            icon="lucide:triangle-alert"
            title="逾期到货"
            tone="danger"
            :value="overview?.deliveries_overdue ?? '-'"
          />
          <StatCard
            icon="lucide:bell-ring"
            title="开放异常"
            to="/operations/exceptions"
            tone="danger"
            :value="overview?.open_exceptions ?? '-'"
          />
          <StatCard
            icon="lucide:boxes"
            title="库存概况"
            :value="inventoryText"
          >
            <template #value>
              <span class="flex flex-wrap items-baseline gap-x-2 gap-y-0" :title="inventoryText">
                <template
                  v-for="unit in overview?.inventory_units ?? []"
                  :key="unit.unit_id"
                >
                  <span class="whitespace-nowrap text-[18px] font-semibold leading-6">
                    {{ formatQuantity(unit.quantity) }}
                    <span class="ml-1 text-xs font-normal text-muted-foreground">
                      {{ unit.unit_name }}
                    </span>
                  </span>
                </template>
                <template v-if="(overview?.inventory_units ?? []).length === 0">
                  {{ inventoryText }}
                </template>
              </span>
            </template>
          </StatCard>
          <StatCard
            icon="lucide:calendar-clock"
            title="有效期预警"
            :tone="expiryAlertTone"
            :value="overview?.expiry_alerts ?? '-'"
          />
          <StatCard
            icon="lucide:file-check-2"
            title="已确认对账"
            to="/finance/reconciliations"
            :value="overview?.confirmed_reconciliations ?? '-'"
          />
          <StatCard
            icon="lucide:wallet"
            title="已付款金额"
            tone="success"
            to="/finance/payments"
            :value="paidAmountText"
          />
        </div>

        <!-- 趋势与状态 -->
        <div class="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Card class="dashboard-panel xl:col-span-2" title="采购金额趋势">
            <TrendChart :data="report?.order_trend ?? []" />
          </Card>
          <Card class="dashboard-panel" title="订单状态分布">
            <StatusChart :data="report?.order_statuses ?? []" />
          </Card>
        </div>

        <!-- 供应商与待办 -->
        <div class="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Card class="dashboard-panel xl:col-span-2" title="供应商采购金额（前 8 名）">
            <SupplierChart :data="report?.supplier_performance ?? []" />
          </Card>
          <Card class="dashboard-panel" title="待办事项">
            <Empty
              v-if="(report?.pending_tasks ?? []).length === 0"
              description="暂无待办"
            />
            <ul v-else class="space-y-3">
              <li
                v-for="task in report?.pending_tasks ?? []"
                :key="task.task_type"
                class="flex items-center justify-between border-b border-dashed pb-2 last:border-0"
              >
                <span class="text-sm">{{ pendingTaskLabel(task.task_type) }}</span>
                <span class="text-lg font-semibold">{{ task.task_count }}</span>
              </li>
            </ul>
          </Card>
        </div>

        <!-- 有效期预警 -->
        <Card class="dashboard-panel" title="库存有效期预警">
          <Empty
            v-if="(report?.inventory_alerts ?? []).length === 0"
            description="所选区间没有临期批次"
          />
          <Table
            v-else
            :columns="alertColumns"
            :data-source="report?.inventory_alerts ?? []"
            :pagination="false"
            :scroll="{ x: 820 }"
            row-key="expiry_date"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'quantity'">
                {{ formatQuantity(record.quantity) }}
              </template>
              <template v-else-if="column.key === 'expiry_date'">
                {{ formatDate(record.expiry_date) }}
              </template>
              <template v-else-if="column.key === 'days_remaining'">
                {{ record.days_remaining }} 天
              </template>
              <template v-else-if="column.key === 'level'">
                <Tag :color="EXPIRY_ALERT_LEVEL_DICT.color(record.level)">
                  {{ EXPIRY_ALERT_LEVEL_DICT.label(record.level) }}
                </Tag>
              </template>
            </template>
          </Table>
        </Card>
      </div>
    </Spin>
  </Page>
</template>

<style scoped>
.dashboard-panel {
  border: 1px solid #e8ecf2;
  border-radius: 8px;
  box-shadow: none;
}

.dashboard-panel :deep(.ant-card-head) {
  min-height: 52px;
  padding-inline: 20px;
}

.dashboard-panel :deep(.ant-card-head-title) {
  color: #172033;
  font-size: 16px;
  font-weight: 600;
}
</style>
