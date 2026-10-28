<script lang="ts" setup>
import type { DashboardApi } from '#/api';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Button, Card, DatePicker, Empty, Spin, Tag } from 'antdv-next';

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
  if (overview.value?.inventory_available === false) return '不适用';
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

const expiryAlerts = computed(() => report.value?.inventory_alerts ?? []);
const expiryBands = computed(() => {
  const rows = expiryAlerts.value;
  return [
    { label: '已过期', count: rows.filter((row) => row.days_remaining < 0).length, tone: 'expired' },
    { label: '7 天内', count: rows.filter((row) => row.days_remaining >= 0 && row.days_remaining <= 7).length, tone: 'urgent' },
    { label: '8–30 天', count: rows.filter((row) => row.days_remaining > 7).length, tone: 'warning' },
  ];
});
const expiryChartStep = computed(() =>
  Math.max(1, Math.ceil(Math.max(...expiryBands.value.map((band) => band.count)) / 5)),
);
const expiryChartMax = computed(() => expiryChartStep.value * 5);
const expiryChartTicks = computed(() =>
  Array.from({ length: 6 }, (_, index) => (5 - index) * expiryChartStep.value),
);

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
            <Tag v-if="overview?.inventory_available === false">库存指标未按部门归属，暂不可用</Tag>
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
        <Card v-if="report?.inventory_available !== false" class="dashboard-panel expiry-panel" title="库存有效期预警">
          <template #extra>
            <span class="expiry-panel-count">
              {{ report?.inventory_alerts?.length ?? 0 }} 条预警
            </span>
          </template>
          <Empty
            v-if="expiryAlerts.length === 0"
            description="当前没有需要关注的临期批次"
          />
          <div v-else class="expiry-layout">
            <section class="expiry-summary" aria-label="到期时间分布">
              <div class="expiry-section-label">到期分布</div>
              <p class="expiry-summary-intro">按当前库存记录统计，预警窗口为未来 30 天。</p>
              <div class="expiry-chart" role="img" :aria-label="`已过期 ${expiryBands[0]?.count ?? 0} 条，7 天内 ${expiryBands[1]?.count ?? 0} 条，8 到 30 天 ${expiryBands[2]?.count ?? 0} 条`">
                <div class="expiry-y-title">预警记录数（条）</div>
                <div class="expiry-chart-body">
                  <div class="expiry-y-ticks" aria-hidden="true">
                    <span v-for="tick in expiryChartTicks" :key="tick">{{ tick }}</span>
                  </div>
                  <div class="expiry-plot">
                    <div class="expiry-gridlines" aria-hidden="true">
                      <span v-for="tick in expiryChartTicks" :key="tick" />
                    </div>
                    <div class="expiry-columns">
                      <div v-for="band in expiryBands" :key="band.label" class="expiry-column-group">
                        <strong class="expiry-column-value">{{ band.count }}</strong>
                        <div
                          class="expiry-column"
                          :class="`expiry-column--${band.tone}`"
                          :style="{ height: `${(band.count / expiryChartMax) * 150}px` }"
                        />
                      </div>
                    </div>
                  </div>
                </div>
                <div class="expiry-x-labels" aria-hidden="true">
                  <span v-for="band in expiryBands" :key="band.label">{{ band.label }}</span>
                </div>
                <div class="expiry-x-title">到期区间</div>
              </div>
            </section>

            <section class="expiry-details" aria-label="临期批次明细">
              <div class="expiry-section-label">临期批次</div>
              <div class="expiry-list">
                <div v-for="alert in expiryAlerts" :key="alert.balance_id" class="expiry-list-row">
                  <div class="expiry-list-main">
                    <div class="expiry-product-name">{{ alert.product_name }}</div>
                    <div class="expiry-product-meta">
                      {{ alert.batch_no }} · {{ alert.warehouse_name }} / {{ alert.location_name }}
                    </div>
                  </div>
                  <div class="expiry-list-amount">
                    <strong>{{ formatQuantity(alert.quantity) }} {{ alert.unit_name }}</strong>
                    <span>在库数量</span>
                  </div>
                  <div class="expiry-list-date">
                    <strong>{{ formatDate(alert.expiry_date) }}</strong>
                    <span>{{ alert.days_remaining < 0 ? `已过期 ${-alert.days_remaining} 天` : `剩余 ${alert.days_remaining} 天` }}</span>
                  </div>
                  <Tag class="expiry-status" :color="EXPIRY_ALERT_LEVEL_DICT.color(alert.level)">
                    {{ EXPIRY_ALERT_LEVEL_DICT.label(alert.level) }}
                  </Tag>
                </div>
              </div>
            </section>
          </div>
        </Card>
      </div>
    </Spin>
  </Page>
</template>

<style scoped>
.dashboard-panel {
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
  box-shadow: none;
}

.dashboard-panel :deep(.ant-card-head) {
  min-height: 52px;
  padding-inline: 20px;
}

.dashboard-panel :deep(.ant-card-head-title) {
  color: hsl(var(--foreground));
  font-size: 16px;
  font-weight: 600;
}

.expiry-panel-count {
  color: hsl(var(--foreground));
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.expiry-layout {
  display: grid;
  gap: 28px;
  grid-template-columns: minmax(240px, 1fr) minmax(0, 2fr);
}

.expiry-summary {
  padding: 8px 24px 8px 4px;
  border-right: 1px solid hsl(var(--border));
}

.expiry-section-label {
  color: hsl(var(--foreground));
  font-size: 14px;
  font-weight: 600;
}

.expiry-summary-intro {
  margin: 6px 0 24px;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
  line-height: 1.6;
}

.expiry-chart {
  margin-top: 38px;
  padding-right: 6px;
}

.expiry-y-title,
.expiry-x-title {
  color: hsl(var(--muted-foreground));
  font-size: 12px;
}

.expiry-y-title {
  margin: 0 0 14px 36px;
}

.expiry-chart-body {
  display: flex;
  height: 180px;
}

.expiry-y-ticks {
  display: flex;
  flex: 0 0 36px;
  flex-direction: column;
  justify-content: space-between;
  padding-right: 8px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  text-align: right;
}

.expiry-y-ticks span {
  transform: translateY(50%);
}

.expiry-plot {
  position: relative;
  flex: 1;
  min-width: 0;
  border-bottom: 1px solid hsl(var(--border));
  border-left: 1px solid hsl(var(--border));
}

.expiry-gridlines {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  pointer-events: none;
}

.expiry-gridlines span {
  border-top: 1px dashed hsl(var(--border) / 70%);
}

.expiry-columns {
  position: absolute;
  inset: 0 0 1px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.expiry-column-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  min-width: 0;
  padding-inline: 6px;
}

.expiry-column-value {
  margin-bottom: 6px;
  color: hsl(var(--foreground));
  font-size: 20px;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.expiry-column {
  width: min(72px, 72%);
  flex: none;
  border-radius: 6px 6px 0 0;
}

.expiry-column--expired { background: #dc2626; }
.expiry-column--urgent { background: #f97316; }
.expiry-column--warning { background: #eab308; }

.expiry-x-labels {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 10px 0 0 36px;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
  text-align: center;
}

.expiry-x-title {
  margin: 12px 0 0 36px;
  text-align: center;
}

.expiry-details {
  min-width: 0;
}

.expiry-list {
  max-height: 460px;
  margin-top: 8px;
  overflow-y: auto;
}

.expiry-list-row {
  display: grid;
  align-items: center;
  gap: 16px;
  grid-template-columns: minmax(180px, 1fr) 100px 104px 88px;
  min-height: 66px;
  padding: 10px 4px;
  border-bottom: 1px solid hsl(var(--border));
}

.expiry-list-row:last-child {
  border-bottom: 0;
}

.expiry-list-main {
  min-width: 0;
}

.expiry-product-name,
.expiry-list-amount strong,
.expiry-list-date strong {
  color: hsl(var(--foreground));
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
}

.expiry-product-meta,
.expiry-list-amount span,
.expiry-list-date span {
  display: block;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
  line-height: 1.5;
}

.expiry-product-meta {
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.expiry-list-amount,
.expiry-list-date {
  font-variant-numeric: tabular-nums;
}

.expiry-status {
  margin-inline-end: 0;
}

@media (max-width: 1100px) {
  .expiry-layout {
    grid-template-columns: 1fr;
  }

  .expiry-summary {
    padding: 0 0 24px;
    border-right: 0;
    border-bottom: 1px solid hsl(var(--border));
  }
}

@media (max-width: 640px) {
  .expiry-list-row {
    gap: 4px 12px;
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .expiry-list-main { grid-column: 1 / -1; }
  .expiry-list-date { grid-column: 1; }
  .expiry-list-amount { grid-column: 2; grid-row: 2; text-align: right; }
  .expiry-status { grid-column: 2; grid-row: 3; justify-self: end; }
}
</style>
