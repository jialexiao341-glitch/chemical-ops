<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { SystemMonitoringApi } from '#/api';

import { computed, onUnmounted, ref } from 'vue';
import { Page } from '@vben/common-ui';
import { IconifyIcon } from '@vben/icons';
import { Alert, Button, Card, Empty, Spin, Tag } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getSystemMonitoringOverviewApi } from '#/api';
import { formatDateTime } from '#/utils/format';
import StatCard from '#/views/dashboard/overview/components/stat-card.vue';

defineOptions({ name: 'SystemMonitoring' });

const overview = ref<SystemMonitoringApi.Overview>();
const loading = ref(false);
const unavailable = ref(false);

const ruleNames: Record<string, string> = {
  ChemicalOpsAPITargetDown: 'API 服务不可达',
  ChemicalOpsAPITargetMissing: 'API 采集目标缺失',
  ChemicalOpsDatabaseMetricsUnavailable: '数据库指标采集失败',
  ChemicalOpsQueueHasFailedTasks: '队列存在失败任务',
  ChemicalOpsQueueRecoveryIsolationRequired: '队列任务需要隔离',
  ChemicalOpsQueueOldestReadyTaskDelayed: '队列任务等待超时',
};
const statusLabels: Record<string, string> = {
  critical: '严重', warning: '警告', info: '提示',
  firing: '触发中', pending: '待确认', inactive: '未触发',
  up: '正常', down: '异常', ok: '正常', error: '异常',
  bad: '异常', unknown: '未知',
};
const abnormalTargets = computed(() => overview.value
  ? overview.value.target_count - overview.value.healthy_targets
  : undefined);
const unhealthyRules = computed(() => overview.value?.rules.filter((rule) => rule.health !== 'ok').length ?? 0);
const attentionRequired = computed(() => Boolean(
  overview.value?.firing_alerts || overview.value?.pending_alerts || abnormalTargets.value || unhealthyRules.value,
));

const [Grid, gridApi] = useVbenVxeGrid({
  gridOptions: {
    columns: [
      { field: 'name', title: '监控项', minWidth: 220, align: 'left', slots: { default: 'rule-name' } },
      { field: 'state', title: '告警状态', minWidth: 100, slots: { default: 'status' } },
      { field: 'health', title: '规则运行', minWidth: 100, slots: { default: 'status' } },
      { field: 'last_evaluation', title: '最近检查', minWidth: 170, formatter: ({ cellValue }) => cellValue ? formatDateTime(cellValue) : '-' },
    ],
    height: 292,
    fit: true,
    keepSource: true,
    pagerConfig: { enabled: false },
    rowConfig: { keyField: 'id' },
    toolbarConfig: { custom: false, export: false, refresh: false, zoom: true },
    proxyConfig: {
      ajax: {
        query: async () => {
          await load();
          const items = overview.value?.rules ?? [];
          return { items, total: items.length };
        },
      },
    },
  } as VxeTableGridOptions<SystemMonitoringApi.Rule>,
});

async function load() {
  if (loading.value) return;
  loading.value = true;
  try {
    overview.value = await getSystemMonitoringOverviewApi();
    unavailable.value = false;
  } catch {
    unavailable.value = true;
  } finally {
    loading.value = false;
  }
}

function stateColor(state: string) {
  if (['critical', 'error', 'firing', 'down', 'bad'].includes(state)) return 'error';
  if (['warning', 'pending'].includes(state)) return 'warning';
  if (['up', 'ok'].includes(state)) return 'success';
  return 'default';
}

const refreshTimer = setInterval(() => { void gridApi.query(); }, 30_000);
onUnmounted(() => clearInterval(refreshTimer));
</script>

<template>
  <Page auto-content-height>
    <div class="space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <h1 class="m-0 text-xl font-semibold tracking-normal">运行监控</h1>
          <Tag v-if="overview" class="m-0" :color="unavailable ? 'default' : attentionRequired ? 'warning' : 'success'">
            {{ unavailable ? '数据未更新' : attentionRequired ? '需要关注' : '运行正常' }}
          </Tag>
        </div>
        <Button :loading="loading" :title="overview ? `更新于 ${formatDateTime(overview.checked_at)} · 每 30 秒自动刷新` : '刷新监控数据'" @click="gridApi.query()">
          <IconifyIcon icon="lucide:refresh-cw" class="mr-1 size-4" />
          刷新
        </Button>
      </div>

      <Alert
        v-if="unavailable"
        type="warning"
        show-icon
        :message="overview ? '监控暂不可用，当前保留上次数据' : '监控暂不可用，请稍后重试'"
      />

      <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard title="触发告警" icon="lucide:bell-ring" :tone="!unavailable && overview?.firing_alerts ? 'danger' : 'default'" :value="overview?.firing_alerts ?? '-'" />
        <StatCard title="待确认" icon="lucide:clock-3" :tone="!unavailable && overview?.pending_alerts ? 'warning' : 'default'" :value="overview?.pending_alerts ?? '-'" />
        <StatCard title="正常目标" icon="lucide:server" :tone="unavailable || !overview?.target_count ? 'default' : abnormalTargets ? 'warning' : 'success'" :value="overview ? `${overview.healthy_targets} / ${overview.target_count}` : '-'" />
        <StatCard title="监控规则" icon="lucide:shield-check" :value="overview?.rule_count ?? '-'" />
      </div>

      <Spin :spinning="loading && !overview">
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Card class="dashboard-panel xl:col-span-2" title="当前告警">
            <Empty v-if="!overview?.alerts.length" :description="overview ? '当前没有告警' : '暂无监控数据'" />
            <ul v-else class="m-0 max-h-64 list-none space-y-3 overflow-auto p-0">
              <li v-for="alert in overview.alerts" :key="alert.id" class="border-b border-dashed pb-3 last:border-0 last:pb-0">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <span class="font-medium" :title="alert.name">{{ ruleNames[alert.name] || alert.name }}</span>
                  <div class="flex items-center gap-2">
                    <Tag class="m-0" :color="stateColor(alert.severity)">{{ statusLabels[alert.severity] || alert.severity }}</Tag>
                    <Tag class="m-0" :color="stateColor(alert.state)">{{ statusLabels[alert.state] || alert.state }}</Tag>
                  </div>
                </div>
                <p class="mb-3 mt-2" :title="alert.description">{{ alert.summary.replace(/^ChemicalOps\s+/, '') }}</p>
                <div class="flex items-center justify-between gap-3 text-sm text-muted-foreground">
                  <span>触发时间</span>
                  <span>{{ alert.active_at ? formatDateTime(alert.active_at) : '-' }}</span>
                </div>
              </li>
            </ul>
          </Card>

          <Card class="dashboard-panel" title="采集状态">
            <Empty v-if="!overview?.targets.length" :description="overview ? '暂无采集目标' : '暂无监控数据'" />
            <ul v-else class="m-0 max-h-64 list-none space-y-3 overflow-auto p-0">
              <li v-for="target in overview.targets" :key="`${target.job}:${target.instance}`" class="border-b border-dashed pb-3 last:border-0 last:pb-0">
                <div class="flex items-center justify-between gap-2">
                  <span class="font-medium">{{ target.job }}</span>
                  <Tag class="m-0" :color="stateColor(target.health)">{{ statusLabels[target.health] || target.health }}</Tag>
                </div>
                <p class="mb-3 mt-2 break-all">{{ target.instance }}</p>
                <div class="flex items-center justify-between gap-3 text-sm text-muted-foreground">
                  <span>最近采集</span>
                  <span>{{ target.last_scrape ? formatDateTime(target.last_scrape) : '-' }}</span>
                </div>
                <p v-if="target.last_error" class="mb-0 mt-2 break-words text-red-600">{{ target.last_error }}</p>
              </li>
            </ul>
          </Card>
        </div>
      </Spin>

      <Grid table-title="告警规则">
        <template #rule-name="{ row }">
          <span :title="row.name">{{ ruleNames[row.name] || row.name }}</span>
        </template>
        <template #status="{ column, row }">
          <Tag :color="stateColor(row[column.field])">
            {{ statusLabels[row[column.field]] || row[column.field] }}
          </Tag>
        </template>
      </Grid>
    </div>
  </Page>
</template>
