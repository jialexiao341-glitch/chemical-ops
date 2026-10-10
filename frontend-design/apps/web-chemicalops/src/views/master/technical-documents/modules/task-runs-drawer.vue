<script lang="ts" setup>
import type { TechnicalDocumentRun } from '#/api';

import { onBeforeUnmount, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenDrawer } from '@vben/common-ui';
import { Button, Empty, Spin, Tag, message } from 'antdv-next';

import {
  getTechnicalDocumentRunsApi,
  startTechnicalDocumentFetchApi,
  startTechnicalDocumentIngestApi,
} from '#/api';

const { hasAccessByCodes } = useAccess();

const runs = ref<TechnicalDocumentRun[]>([]);
const loading = ref(false);
const retryingRunId = ref('');
let refreshTimer: ReturnType<typeof setInterval> | undefined;

const [Drawer] = useVbenDrawer({
  footer: false,
  async onOpenChange(open) {
    if (open) await reloadRuns();
    else stopPolling();
  },
});

function stopPolling() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = undefined;
}

async function reloadRuns() {
  loading.value = true;
  try {
    runs.value = await getTechnicalDocumentRunsApi();
  } finally {
    loading.value = false;
  }
  if (runs.value.some((run) => ['QUEUED', 'RUNNING', 'RETRYING'].includes(run.status))) {
    if (!refreshTimer) refreshTimer = setInterval(() => { void reloadRuns(); }, 5000);
  } else {
    stopPolling();
  }
}

function runSummary(run: TechnicalDocumentRun) {
  if (run.status === 'QUEUED') return '已接收，等待后台执行';
  if (run.status === 'RETRYING') return '暂时未完成，等待自动重试';
  const data = run.result_json;
  if (run.error_type) {
    if (/StatementError|scheduler_job_runs|SQL:|not JSON serializable/i.test(run.error_type)) {
      return '任务结果保存失败，请展开阶段输出查看详情';
    }
    return run.error_type.length > 180 ? `${run.error_type.slice(0, 180)}…` : run.error_type;
  }
  const stages = data?.stages?.map((stage: any) => `${stage.stage}: ${stage.status === 'SUCCEEDED' ? '完成' : '失败'}`).join(' · ');
  const documents = data?.documents?.map((doc: any) => `${doc.doc_type.toUpperCase()} ${doc.parse_status}${doc.reject_reason ? `（${doc.reject_reason}）` : ''}`).join('；');
  return [stages, documents].filter(Boolean).join('；') || (data?.cas_no ? '等待后台启动' : '任务已创建，等待后台启动');
}

function runAction(run: TechnicalDocumentRun) {
  return run.result_json?.action === 'fetch' ? '拉取数据' : run.result_json?.action === 'ingest' ? '写入知识库' : '';
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date);
}

async function retryRun(run: TechnicalDocumentRun) {
  if (!hasAccessByCodes(['master.chemicals.write']) || run.status !== 'FAILED') return;
  const casNo = run.result_json?.cas_no;
  const docTypes = run.result_json?.doc_types;
  if (!casNo || !Array.isArray(docTypes) || retryingRunId.value) return;
  retryingRunId.value = run.run_id;
  try {
    const request = run.result_json?.action === 'fetch'
      ? startTechnicalDocumentFetchApi
      : startTechnicalDocumentIngestApi;
    await request({ cas_no: casNo, doc_types: docTypes });
    message.success(`CAS ${casNo} 的资料任务已重新启动`);
    await reloadRuns();
  } finally {
    retryingRunId.value = '';
  }
}

onBeforeUnmount(stopPolling);
</script>

<template>
  <Drawer title="处理任务" class="w-[720px] max-w-[100vw]">
    <div class="flex flex-col gap-4 pb-4">
      <div class="flex items-center justify-between gap-4 rounded-md bg-muted/40 px-4 py-3">
        <span class="text-sm text-muted-foreground">查看资料拉取和知识库写入进度，可重试失败任务</span>
        <Button :loading="loading" @click="reloadRuns">刷新</Button>
      </div>

      <Spin :spinning="loading">
        <Empty v-if="!runs.length" description="暂无处理任务" />
        <div v-else class="space-y-3">
          <article v-for="run in runs" :key="run.run_id" class="space-y-3 rounded-md border border-border bg-card p-4">
            <header class="flex flex-wrap items-center gap-2">
              <Tag class="m-0" :color="run.status === 'SUCCEEDED' ? 'success' : run.status === 'FAILED' ? 'error' : 'processing'">
                {{ run.status === 'SUCCEEDED' ? '完成' : run.status === 'FAILED' ? '失败' : run.status === 'QUEUED' ? '等待执行' : run.status === 'RETRYING' ? '等待重试' : '处理中' }}
              </Tag>
              <span class="text-base font-semibold">CAS {{ run.result_json?.cas_no || '任务启动中' }}</span>
              <Tag v-if="runAction(run)" class="m-0" color="blue">{{ runAction(run) }}</Tag>
              <time class="ml-auto text-sm text-muted-foreground">{{ formatDateTime(run.started_at) }}</time>
              <Button v-if="hasAccessByCodes(['master.chemicals.write'])" size="small" :loading="retryingRunId === run.run_id" :disabled="Boolean(retryingRunId) || run.status !== 'FAILED'" :title="run.status !== 'FAILED' ? '只有失败任务可以重试' : undefined" @click="retryRun(run)">重试</Button>
            </header>
            <p class="m-0 break-words text-sm leading-6 text-muted-foreground">{{ runSummary(run) }}</p>
            <details v-if="run.result_json?.stages?.length" class="rounded-md border border-border px-3 py-2">
              <summary class="cursor-pointer select-none py-1 text-sm font-medium">阶段输出 <span class="ml-1 font-normal text-muted-foreground">{{ run.result_json.stages.length }} 个阶段</span></summary>
              <section v-for="stage in run.result_json.stages" :key="stage.stage" class="mt-2 border-t border-border pt-3">
                <div class="text-sm font-medium">{{ stage.stage }} <span class="font-normal text-muted-foreground">· {{ stage.status === 'SUCCEEDED' ? '完成' : stage.status === 'FAILED' ? '失败' : '处理中' }}</span></div>
                <pre v-if="stage.output" class="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-muted/40 p-3 font-mono text-xs leading-5 text-muted-foreground">{{ stage.output }}</pre>
              </section>
            </details>
          </article>
        </div>
      </Spin>
    </div>
  </Drawer>
</template>
