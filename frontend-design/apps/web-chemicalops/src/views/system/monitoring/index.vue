<script lang="ts" setup>
import type { SystemMonitoringApi } from '#/api';

import { onMounted, onUnmounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Button, Card, Empty, Spin, Table, Tag } from 'antdv-next';

import { getSystemMonitoringOverviewApi } from '#/api';
import { formatDateTime } from '#/utils/format';

defineOptions({ name: 'SystemMonitoring' });

const overview = ref<SystemMonitoringApi.Overview>();
const loading = ref(false);
const unavailable = ref(false);
let refreshTimer: ReturnType<typeof setInterval> | undefined;

const alertColumns = [
  { key: 'name', title: '告警', width: 210 },
  { key: 'severity', title: '级别', width: 110 },
  { key: 'state', title: '状态', width: 110 },
  { key: 'summary', title: '摘要', minWidth: 260 },
  { key: 'active_at', title: '开始时间', width: 190 },
];

const targetColumns = [
  { key: 'job', title: '采集任务', width: 190 },
  { key: 'instance', title: '目标实例', minWidth: 220 },
  { key: 'health', title: '状态', width: 100 },
  { key: 'last_scrape', title: '最近采集', width: 190 },
  { key: 'last_error', title: '错误', minWidth: 220 },
];

const ruleColumns = [
  { key: 'name', title: '规则', minWidth: 240 },
  { key: 'state', title: '触发状态', width: 120 },
  { key: 'health', title: '规则健康度', width: 140 },
  { key: 'last_evaluation', title: '最近评估', width: 190 },
];

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
  if (state === 'critical' || state === 'error' || state === 'high') return 'error';
  if (state === 'warning' || state === 'medium') return 'warning';
  if (state === 'firing' || state === 'down' || state === 'bad') return 'error';
  if (state === 'pending') return 'warning';
  if (state === 'up' || state === 'ok' || state === 'inactive') return 'success';
  return 'default';
}

onMounted(() => {
  load();
  refreshTimer = setInterval(load, 30_000);
});

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer);
});
</script>

<template>
  <Page auto-content-height>
    <Spin :spinning="loading && !overview">
      <div class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 class="m-0 text-xl font-semibold tracking-normal">运行监控</h1>
            <p class="mb-0 mt-1 text-sm text-muted-foreground">
              管理员可查看 Prometheus 告警、规则评估与采集目标状态
              <span v-if="overview">· 更新于 {{ formatDateTime(overview.checked_at) }}</span>
            </p>
          </div>
          <Button :loading="loading" @click="load">刷新</Button>
        </div>

        <Card v-if="unavailable" class="border-amber-200 bg-amber-50">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div class="font-medium text-amber-900">暂时无法读取监控数据</div>
              <div class="mt-1 text-sm text-amber-800">
                请检查 Prometheus 服务和后端 PROMETHEUS_URL 配置，然后重试。
              </div>
            </div>
            <Button @click="load">重新连接</Button>
          </div>
        </Card>

        <template v-if="overview">
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Card>
              <div class="text-sm text-muted-foreground">触发中告警</div>
              <div class="mt-2 text-2xl font-semibold" :class="overview.firing_alerts ? 'text-red-600' : 'text-emerald-600'">
                {{ overview.firing_alerts }}
              </div>
            </Card>
            <Card>
              <div class="text-sm text-muted-foreground">等待确认</div>
              <div class="mt-2 text-2xl font-semibold" :class="overview.pending_alerts ? 'text-amber-600' : ''">
                {{ overview.pending_alerts }}
              </div>
            </Card>
            <Card>
              <div class="text-sm text-muted-foreground">正常采集目标</div>
              <div class="mt-2 text-2xl font-semibold">
                {{ overview.healthy_targets }} <span class="text-base font-normal text-muted-foreground">/ {{ overview.target_count }}</span>
              </div>
            </Card>
            <Card>
              <div class="text-sm text-muted-foreground">告警规则</div>
              <div class="mt-2 text-2xl font-semibold">{{ overview.rule_count }}</div>
            </Card>
          </div>

          <Card>
            <div class="mb-4 flex items-center gap-3">
              <h2 class="m-0 text-base font-semibold">当前告警</h2>
              <Tag :color="overview.firing_alerts ? 'error' : overview.pending_alerts ? 'warning' : 'success'">
                {{ overview.firing_alerts ? `${overview.firing_alerts} 条触发中` : overview.pending_alerts ? `${overview.pending_alerts} 条待确认` : '当前正常' }}
              </Tag>
            </div>
            <Empty v-if="overview.alerts.length === 0" description="当前没有待处理告警" />
            <Table
              v-else
              :columns="alertColumns"
              :data-source="overview.alerts"
              :pagination="false"
              :scroll="{ x: 900 }"
              row-key="id"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'severity'">
                  <Tag :color="stateColor(record.severity)">{{ record.severity }}</Tag>
                </template>
                <template v-else-if="column.key === 'state'">
                  <Tag :color="stateColor(record.state)">{{ record.state === 'firing' ? '触发中' : '待触发' }}</Tag>
                </template>
                <template v-else-if="column.key === 'summary'">
                  <span :title="record.description">{{ record.summary }}</span>
                </template>
                <template v-else-if="column.key === 'active_at'">
                  {{ record.active_at ? formatDateTime(record.active_at) : '-' }}
                </template>
              </template>
            </Table>
          </Card>

          <Card>
            <h2 class="mb-4 mt-0 text-base font-semibold">监控采集目标</h2>
            <Empty v-if="overview.targets.length === 0" description="Prometheus 当前没有采集目标" />
            <Table
              v-else
              :columns="targetColumns"
              :data-source="overview.targets"
              :pagination="false"
              :scroll="{ x: 900 }"
              row-key="instance"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'health'">
                  <Tag :color="stateColor(record.health)">{{ record.health === 'up' ? '正常' : record.health }}</Tag>
                </template>
                <template v-else-if="column.key === 'last_scrape'">
                  {{ record.last_scrape ? formatDateTime(record.last_scrape) : '-' }}
                </template>
                <template v-else-if="column.key === 'last_error'">
                  <span :class="record.last_error ? 'text-red-600' : 'text-muted-foreground'">
                    {{ record.last_error || '-' }}
                  </span>
                </template>
              </template>
            </Table>
          </Card>

          <Card>
            <h2 class="mb-4 mt-0 text-base font-semibold">告警规则状态</h2>
            <Empty v-if="overview.rules.length === 0" description="没有已加载的告警规则" />
            <Table
              v-else
              :columns="ruleColumns"
              :data-source="overview.rules"
              :pagination="false"
              :scroll="{ x: 760 }"
              row-key="id"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'state' || column.key === 'health'">
                  <Tag :color="stateColor(record[column.key])">
                    {{ record[column.key] === 'inactive' ? '正常' : record[column.key] }}
                  </Tag>
                </template>
                <template v-else-if="column.key === 'last_evaluation'">
                  {{ record.last_evaluation ? formatDateTime(record.last_evaluation) : '-' }}
                </template>
              </template>
            </Table>
          </Card>
        </template>
      </div>
    </Spin>
  </Page>
</template>
