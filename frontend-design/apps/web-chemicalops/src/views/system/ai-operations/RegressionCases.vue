<script lang="ts" setup>
import type { AgentApi } from '#/api';

import { computed, onMounted, ref } from 'vue';
import { Button, Modal, Select, Table, Tag, message } from 'antdv-next';

import {
  getRegressionCaseOptionsApi,
  getRegressionCasePageApi,
  reviewRegressionCaseApi,
} from '#/api';

defineOptions({ name: 'RegressionCases' });

const rows = ref<AgentApi.RegressionCase[]>([]);
const options = ref<AgentApi.RegressionCaseOptions>();
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const status = ref<string>();
const loading = ref(false);
const reviewingId = ref<number>();
const statusOptions = [
  { label: '草稿', value: 'DRAFT' },
  { label: '已批准', value: 'APPROVED' },
  { label: '已归档', value: 'ARCHIVED' },
];
const statusLabels: Record<AgentApi.RegressionCase['status'], string> = {
  APPROVED: '已批准',
  ARCHIVED: '已归档',
  DRAFT: '草稿',
};
const statusColors: Record<AgentApi.RegressionCase['status'], string> = {
  APPROVED: 'success',
  ARCHIVED: 'default',
  DRAFT: 'warning',
};
const modeLabels: Record<string, string> = {
  agent: 'Agent 只读任务',
  batch: '多意图批次',
  document: '文档问答',
  none: '不执行',
  query: '统计查询',
};
const taskLabels = computed(() => Object.fromEntries(
  (options.value?.tasks ?? []).map((item) => [item.key, item.label])));

const columns = [
  { dataIndex: 'case_key', key: 'case_key', title: '用例编号', width: 140 },
  { dataIndex: 'status', key: 'status', title: '状态', width: 90 },
  { dataIndex: 'expected_execution_mode', key: 'mode', title: '执行模式', width: 130 },
  { dataIndex: 'expected_tasks', key: 'tasks', title: '任务', width: 180 },
  { dataIndex: 'question', key: 'question', title: '脱敏后的问题', ellipsis: true },
  { dataIndex: 'source_prompt_version', key: 'prompt', title: '来源 prompt', width: 190, ellipsis: true },
  { dataIndex: 'created_at', key: 'created_at', title: '提交时间', width: 170 },
  { key: 'operation', title: '操作', width: 130, fixed: 'right' as const },
];

async function load() {
  loading.value = true;
  try {
    const result = await getRegressionCasePageApi({
      page: page.value,
      page_size: pageSize.value,
      status: status.value,
    });
    rows.value = result.items;
    total.value = result.total;
  } catch {
    message.error('读取回归用例失败，请确认管理员权限');
  } finally {
    loading.value = false;
  }
}

function search() {
  page.value = 1;
  void load();
}

function reset() {
  status.value = undefined;
  search();
}

function onTableChange(pagination: { current?: number; pageSize?: number }) {
  page.value = pagination.current ?? 1;
  pageSize.value = pagination.pageSize ?? pageSize.value;
  void load();
}

function taskText(row: AgentApi.RegressionCase) {
  if (!row.expected_tasks.length) return '—';
  return row.expected_tasks.map((key) => taskLabels.value[key] ?? key).join('、');
}

function confirmReview(row: AgentApi.RegressionCase, action: 'APPROVE' | 'ARCHIVE') {
  if (reviewingId.value) return;
  const label = action === 'APPROVE' ? '批准' : '归档';
  Modal.confirm({
    title: `${label}回归用例`,
    content: `确认${label} ${row.case_key}？${action === 'APPROVE' ? '批准后会被导出脚本纳入评测集。' : '归档后不会进入评测集，且不可恢复。'}`,
    okText: `确认${label}`,
    cancelText: '取消',
    onOk: async () => {
      reviewingId.value = row.id;
      try {
        await reviewRegressionCaseApi(row.id, action);
        message.success(`用例${label}成功`);
        void load();
      } catch (error: any) {
        message.error(error?.message || `${label}失败，请刷新后重试`);
      } finally {
        reviewingId.value = undefined;
      }
    },
  });
}

onMounted(async () => {
  try {
    options.value = await getRegressionCaseOptionsApi();
  } catch {
    message.error('读取回归用例选项失败');
  }
  await load();
});
</script>

<template>
  <section class="rounded bg-card p-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold">回归用例</h2>
        <p class="text-muted-foreground mt-1 text-xs">
          由任务详情提交、人工脱敏的回归用例；管理员批准后由导出脚本纳入评测集。Agent 不自动修改用例或提示词。
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Select v-model:value="status" :options="statusOptions" allow-clear placeholder="全部状态" class="w-36" />
        <Button @click="reset">重置</Button>
        <Button type="primary" :loading="loading" @click="search">查询</Button>
      </div>
    </div>

    <Table
      class="mt-4"
      :columns="columns"
      :data-source="rows"
      :loading="loading"
      :pagination="{
        current: page,
        pageSize,
        total,
        showSizeChanger: false,
      }"
      row-key="id"
      size="small"
      @change="onTableChange"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <Tag :color="statusColors[(record as AgentApi.RegressionCase).status]">
            {{ statusLabels[(record as AgentApi.RegressionCase).status] }}
          </Tag>
        </template>
        <template v-else-if="column.key === 'mode'">
          {{ modeLabels[(record as AgentApi.RegressionCase).expected_execution_mode] ?? (record as AgentApi.RegressionCase).expected_execution_mode }}
        </template>
        <template v-else-if="column.key === 'tasks'">
          {{ taskText(record as AgentApi.RegressionCase) }}
        </template>
        <template v-else-if="column.key === 'prompt'">
          {{ (record as AgentApi.RegressionCase).source_prompt_version || '—' }}
        </template>
        <template v-else-if="column.key === 'created_at'">
          {{ (record as AgentApi.RegressionCase).created_at?.replace('T', ' ').slice(0, 16) || '—' }}
        </template>
        <template v-else-if="column.key === 'operation'">
          <Button
            v-if="(record as AgentApi.RegressionCase).status === 'DRAFT'"
            type="link"
            size="small"
            :loading="reviewingId === (record as AgentApi.RegressionCase).id"
            @click="confirmReview(record as AgentApi.RegressionCase, 'APPROVE')"
          >
            批准
          </Button>
          <Button
            v-if="(record as AgentApi.RegressionCase).status !== 'ARCHIVED'"
            type="link"
            size="small"
            danger
            @click="confirmReview(record as AgentApi.RegressionCase, 'ARCHIVE')"
          >
            归档
          </Button>
        </template>
      </template>
    </Table>
  </section>
</template>
