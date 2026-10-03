<script setup lang="ts">
import type { AgentApi } from '#/api';

import { computed, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Page } from '@vben/common-ui';
import { Button, Input, Tag } from 'antdv-next';
import { cancelAgentTaskApi, continueAgentTaskApi, createAgentTaskApi, getAgentTaskApi } from '#/api';
import { acceptTask, inventorySource, SOURCE_LABELS, TASK_ERROR_HELP, TASK_LABELS, TOOL_LABELS, waitingCandidates } from './task-view';

defineOptions({ name: 'AiAgentTask' });
const route = useRoute();
const router = useRouter();
const task = ref<AgentApi.Task>();
const question = ref('');
const supplement = ref('');
const selection = ref<number>();
const busy = ref(false);
const refreshing = ref(false);
const cancelling = ref(false);
const error = ref('');
let epoch = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
const candidates = computed(() => waitingCandidates(task.value));
const results = computed(() => task.value?.trace.filter((entry) => entry.status === 'SUCCEEDED' && entry.result) ?? []);
const canContinue = computed(() => task.value?.status === 'WAITING_INPUT' && !busy.value && (selection.value !== undefined || supplement.value.trim()));

function apply(incoming: AgentApi.Task, requestEpoch: number) {
  if (requestEpoch === epoch && acceptTask(task.value, incoming)) task.value = incoming;
}
function clearPoll() {
  if (timer) clearTimeout(timer);
}
function schedulePoll() {
  clearPoll();
  if (task.value?.status === 'RUNNING') timer = setTimeout(() => void refresh(), 2000);
}
async function refresh() {
  const id = route.query.task;
  if (typeof id !== 'string' || refreshing.value) return;
  const requestEpoch = epoch;
  refreshing.value = true;
  try {
    apply(await getAgentTaskApi(id), requestEpoch);
    if (requestEpoch === epoch) error.value = '';
  } catch {
    if (requestEpoch === epoch) {
      task.value = undefined; // 权限撤销/不可访问时不再显示旧证据。
      epoch += 1; // 拒绝后使已在途响应失效，不能重新显示旧证据。
      clearPoll();
      busy.value = false;
      refreshing.value = false;
      cancelling.value = false;
      error.value = '任务无法读取，请核对登录、权限或服务状态后刷新。';
    }
  } finally {
    if (requestEpoch === epoch) {
      refreshing.value = false;
      schedulePoll();
    }
  }
}
async function start() {
  if (busy.value || !question.value.trim()) return;
  const requestEpoch = ++epoch;
  clearPoll();
  task.value = undefined;
  error.value = '';
  busy.value = true;
  try {
    const result = await createAgentTaskApi(question.value.trim());
    if (requestEpoch !== epoch) return;
    task.value = result;
    await router.replace({ query: { task: result.id } });
    schedulePoll();
  } catch {
    if (requestEpoch === epoch) error.value = '未取得任务编号，请核对权限或服务状态。启动请求可能已保存，请勿连续重复提交。';
  } finally {
    if (requestEpoch === epoch) busy.value = false;
  }
}
async function continueTask() {
  if (!task.value || !canContinue.value) return;
  const requestEpoch = epoch;
  const selected = candidates.value;
  const data: AgentApi.Continue = { question: supplement.value.trim() || '使用本次选中的候选继续原查询目标', revision: task.value.revision };
  if (selected?.tool === 'catalog.search_products') data.product_id = selection.value;
  if (selected?.tool === 'supplier_quotes.find_rfq_items') data.rfq_item_id = selection.value;
  busy.value = true;
  error.value = '';
  try {
    apply(await continueAgentTaskApi(task.value.id, data), requestEpoch);
    supplement.value = '';
  } catch {
    if (requestEpoch === epoch) {
      error.value = '未取得续跑结果，正在刷新任务。请核对最新状态后操作。';
      await refresh();
    }
  } finally {
    if (requestEpoch === epoch) { busy.value = false; schedulePoll(); }
  }
}
async function cancel() {
  if (!task.value || cancelling.value) return;
  const requestEpoch = epoch;
  cancelling.value = true;
  try { apply(await cancelAgentTaskApi(task.value.id), requestEpoch); }
  catch { if (requestEpoch === epoch) error.value = '未确认取消结果，请刷新任务后核对。'; }
  finally { if (requestEpoch === epoch) { cancelling.value = false; schedulePoll(); } }
}
watch(() => task.value?.revision, () => { selection.value = undefined; });
watch(() => route.query.task, (id) => {
  // 创建响应设置 URL 后已有结果，不重复读取；URL 变化立即清掉前一个任务。
  if (id === task.value?.id) return;
  epoch += 1;
  clearPoll();
  busy.value = false;
  refreshing.value = false;
  cancelling.value = false;
  task.value = undefined;
  error.value = '';
  if (typeof id === 'string' && /^[a-f\d]{32}$/.test(id)) void refresh();
  else if (id) error.value = '任务编号无效，请从工作台重新发起查询。';
}, { immediate: true });
onUnmounted(() => { epoch += 1; clearPoll(); });
</script>

<template>
  <Page auto-content-height>
    <main class="agent-page">
      <header class="agent-header">
        <div><p class="agent-eyebrow">化运 AI · 采购辅助</p><h1>采购只读任务</h1><p class="text-muted-foreground">定位产品，核对账面库存，比较同一询价内的报价。结果限定在当前授权范围。</p></div>
        <Button @click="router.push('/ai/workspace')">返回对话工作台</Button>
      </header>
      <form v-if="!route.query.task" class="agent-input" @submit.prevent="start">
        <label for="agent-goal">描述查询目标</label>
        <Input.TextArea id="agent-goal" v-model:value="question" :maxlength="2000" :rows="3" :disabled="busy" placeholder="例如：查乙醇的库存，并比较可用询价中的供应商报价" />
        <div class="agent-actions"><span class="text-muted-foreground">本任务不创建采购申请、不定标、不下单。</span><Button type="primary" html-type="submit" :loading="busy" :disabled="!question.trim()">开始查询</Button></div>
        <p v-if="busy" role="status">正在启动任务…</p>
      </form>
      <p v-if="error" class="agent-error" role="alert">{{ error }}</p>
      <p v-if="refreshing && !task" role="status">正在读取任务…</p>
      <div v-if="route.query.task" class="agent-actions">
        <Button :loading="refreshing" @click="refresh">刷新任务</Button>
        <Button :disabled="busy || task?.status === 'RUNNING'" @click="router.push({ path: '/ai/agent' })">发起新任务</Button>
        <Button v-if="task && ['RUNNING', 'WAITING_INPUT'].includes(task.status)" :loading="cancelling" @click="cancel">取消任务</Button>
      </div>
      <template v-if="task">
        <section class="agent-status" aria-live="polite">
          <div class="agent-actions"><h2>{{ TASK_LABELS[task.status] }}</h2><Tag :color="task.status === 'FAILED' ? 'red' : task.status === 'SUCCEEDED' ? 'green' : 'blue'">{{ TASK_LABELS[task.status] }}</Tag></div>
          <p class="agent-id">任务编号 {{ task.id }}</p>
          <p class="agent-reply">{{ task.status === 'RUNNING' ? '正在读取业务数据，请稍候。' : task.reply }}</p>
          <p v-if="busy" role="status">补充信息已发送，正在查询；可刷新查看步骤或取消本任务。</p>
          <p v-if="task.error_code" class="agent-error">{{ TASK_ERROR_HELP[task.error_code] || '请核对输入、权限及模型服务后重新发起查询。' }}（{{ task.error_code }}）</p>
          <p v-if="task.status === 'RUNNING'" class="text-muted-foreground">页面会更新状态。若服务中断后长期停留在查询中，可取消后重新发起。</p>
        </section>
        <details class="agent-history"><summary>查询目标与补充记录（{{ task.messages.length }}）</summary><ol><li v-for="(text, index) in task.messages" :key="index">{{ text }}</li></ol></details>
        <form v-if="task.status === 'WAITING_INPUT'" class="agent-input" @submit.prevent="continueTask">
          <fieldset v-if="candidates?.tool === 'catalog.search_products'" :disabled="busy"><legend>选择产品规格</legend>
            <label v-for="row in candidates.rows" :key="row.product_id" class="agent-choice"><input v-model="selection" type="radio" name="candidate" :value="row.product_id" /><span><strong>{{ row.product_name }}</strong> · {{ row.product_code }}<br />{{ row.model || '未登记型号' }} / {{ row.packaging_spec || '未登记包装' }} / {{ row.unit_name }}</span></label>
          </fieldset>
          <fieldset v-if="candidates?.tool === 'supplier_quotes.find_rfq_items'" :disabled="busy"><legend>选择询价明细</legend>
            <label v-for="row in candidates.rows" :key="row.rfq_item_id" class="agent-choice"><input v-model="selection" type="radio" name="candidate" :value="row.rfq_item_id" /><span><strong>{{ row.rfq_no }}</strong> · 明细 {{ row.rfq_item_id }}<br />{{ row.specification || '未登记规格' }} / {{ row.technical_requirements || '无技术要求' }}</span></label>
          </fieldset>
          <p v-if="candidates?.truncated" class="text-muted-foreground">候选未完整返回，请补充精确产品编码或询价编号后缩小范围。</p>
          <label for="agent-supplement">{{ candidates ? '补充查询条件（可选）' : '补充查询条件' }}</label>
          <Input.TextArea id="agent-supplement" v-model:value="supplement" :rows="2" :maxlength="2000" :disabled="busy" placeholder="补充产品名称、规格或询价编号" />
          <Button html-type="submit" type="primary" :loading="busy" :disabled="!canContinue">继续查询</Button>
        </form>
        <section v-if="task.trace.length" class="agent-progress" aria-label="任务步骤"><h2>任务步骤</h2><ol><li v-for="step in task.trace" :key="step.step"><span>{{ step.step }}</span><strong>{{ TOOL_LABELS[step.tool || ''] || (step.action === 'ask_user' ? '等待补充' : step.action === 'finish' ? '汇总证据' : '停止查询') }}</strong><small>{{ step.status === 'SUCCEEDED' ? '已完成' : step.status === 'WAITING_INPUT' ? '等待补充' : '已停止' }}</small></li></ol></section>
        <section v-for="entry in results" :key="entry.step" class="agent-result">
          <p class="agent-observed">步骤 {{ entry.step }} · 已保存的查询结果</p>
          <template v-if="entry.result?.tool === 'inventory.query_available'">
            <h2>{{ entry.result.product_name }} · 账面库存</h2><p class="text-muted-foreground">{{ entry.result.scope }}</p>
            <div class="agent-totals"><p v-for="(total, i) in entry.result.totals" :key="i"><strong>{{ total.available_quantity }}</strong> {{ total.unit_name }}<span>账面可用量</span></p></div>
            <p v-if="entry.result.total_rows === 0">当前授权范围无库存记录。</p>
            <div v-else class="agent-table"><table><caption>库存明细与来源</caption><thead><tr><th>仓库 / 批次</th><th>可用量</th><th>状态 / 有效期</th><th>来源</th></tr></thead><tbody><tr v-for="row in entry.result.rows" :key="row.balance_id"><td>{{ row.warehouse_name }}<br />{{ row.batch_no }}</td><td>{{ row.available_quantity }} {{ row.unit_name }}</td><td>{{ row.status === 'AVAILABLE' ? '可用' : row.status === 'FROZEN' ? '冻结' : row.status }}<br />{{ row.expiry_date || '未登记' }}</td><td><RouterLink :to="inventorySource(entry.result.product_id, row.warehouse_id)">余额 #{{ row.balance_id }} · 查看所在库存列表</RouterLink></td></tr></tbody></table></div>
          </template>
          <template v-else-if="entry.result?.tool === 'supplier_quotes.compare'">
            <h2>{{ entry.result.rfq_no }} · 供应商报价</h2><p>{{ entry.result.specification || '未登记规格' }} · {{ entry.result.technical_requirements || '无技术要求' }}</p><p class="text-muted-foreground">{{ entry.result.comparison_basis }}。{{ entry.result.scope }}</p>
            <p v-if="entry.result.total_rows === 0">当前授权范围无符合条件的最新报价。</p>
            <div v-else class="agent-table"><table><caption>报价明细；不同可比组的排名不能相互比较</caption><thead><tr><th>供应商 / 报价</th><th>未税单价</th><th>型号 / 税率</th><th>组内排名</th><th>报价量 / 起订量 / 交期</th><th>日期 / 有效期</th></tr></thead><tbody><tr v-for="row in entry.result.rows" :key="row.quote_item_id"><td>{{ row.supplier_name }}<br />{{ row.quote_no }} · v{{ row.quote_version }}</td><td>{{ row.unit_price }} {{ row.currency_code }}/{{ row.unit_name }}</td><td>{{ row.supplier_model ?? '未登记' }}<br />{{ row.tax_rate ?? '未知' }}{{ row.tax_rate === null ? '' : '%' }}</td><td>{{ row.rank ?? '不排序' }}</td><td>{{ row.quoted_quantity }} {{ row.unit_name }}<br />起订量 {{ row.moq_quantity ?? '未登记' }}（单位见询价原记录）<br />{{ row.lead_days === null ? '未登记交期' : `${row.lead_days} 天` }}</td><td>{{ row.quote_date }}<br />{{ row.valid_until || '未登记' }}</td></tr></tbody></table></div>
            <RouterLink :to="{ path: '/procurement/rfqs', query: { ai_record_id: entry.result.rfq_id } }">查看询价原记录与报价来源</RouterLink>
          </template>
          <template v-else-if="entry.result"><h2>{{ TOOL_LABELS[entry.result.tool] }}</h2><p>当前授权范围匹配 {{ entry.result.total_rows }} 条记录。</p><details><summary>查看候选与来源</summary>
            <ul v-if="entry.result.tool === 'catalog.search_products'"><li v-for="row in entry.result.rows" :key="row.product_id">{{ row.product_name }} · {{ row.product_code }} · {{ row.model || '未登记型号' }} / {{ row.packaging_spec || '未登记包装' }} / {{ row.unit_name }}</li></ul>
            <ul v-else-if="entry.result.tool === 'supplier_quotes.find_rfq_items'"><li v-for="row in entry.result.rows" :key="row.rfq_item_id">{{ row.rfq_no }} · 明细 {{ row.rfq_item_id }} · {{ row.specification || '未登记规格' }} / {{ row.technical_requirements || '无技术要求' }}</li></ul>
          </details></template>
          <template v-if="entry.result">
            <p v-if="'observed_at' in entry.result" class="agent-observed">查询时点 {{ entry.result.observed_at }}（UTC） · 历史快照，刷新任务不重新计算业务数据</p>
            <p v-if="entry.result.truncated" class="agent-error">明细已截断，共 {{ entry.result.total_rows }} 条；{{ entry.result.tool === 'inventory.query_available' ? '合计仍覆盖全部授权范围。' : '当前结果不代表完整比较。' }}</p>
            <ul v-if="'warnings' in entry.result" class="agent-warnings"><li v-for="warning in entry.result.warnings" :key="warning">{{ warning }}</li></ul>
            <details class="agent-sources"><summary>来源记录（{{ entry.result.sources.length }}）</summary><ul><li v-for="source in entry.result.sources" :key="`${source.resource}-${source.record_id}`">{{ SOURCE_LABELS[source.resource] || '业务记录' }} #{{ source.record_id }}<span v-if="source.parent_id"> · 所属单据 #{{ source.parent_id }}</span></li></ul></details>
          </template>
        </section>
      </template>
    </main>
  </Page>
</template>

<style scoped>
.agent-page { max-width: 1120px; margin: 0 auto; padding: 24px; color: hsl(var(--foreground)); }
.agent-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 28px; }
.agent-eyebrow { color: hsl(var(--primary)); font-size: 12px; margin-bottom: 8px; }
h1 { font-size: 26px; font-weight: 600; margin-bottom: 8px; }
h2 { font-size: 17px; font-weight: 600; margin-bottom: 12px; }
p { line-height: 1.65; }
.agent-input, .agent-status, .agent-result { padding: 20px; margin: 16px 0; border: 1px solid hsl(var(--border)); border-radius: 12px; background: hsl(var(--card)); }
.agent-input { display: grid; gap: 12px; }
.agent-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.agent-input .agent-actions { justify-content: space-between; }
.agent-actions h2 { margin: 0; }
.agent-id, .agent-observed { color: hsl(var(--muted-foreground)); font-size: 12px; overflow-wrap: anywhere; margin: 10px 0; }
.agent-reply { white-space: pre-wrap; margin-top: 16px; }
.agent-error { color: hsl(var(--destructive)); margin: 12px 0; }
.agent-choice { display: flex; align-items: center; gap: 12px; border-bottom: 1px solid hsl(var(--border)); padding: 14px 4px; cursor: pointer; }
.agent-choice:has(input:checked) { background: hsl(var(--muted)); }
fieldset { min-width: 0; }
legend { font-weight: 600; }
.agent-progress { margin: 24px 0; }
.agent-progress ol { display: flex; flex-wrap: wrap; gap: 12px; }
.agent-progress li { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.agent-progress li > span { border: 1px solid hsl(var(--border)); border-radius: 50%; min-width: 24px; text-align: center; }
.agent-progress small { color: hsl(var(--muted-foreground)); }
.agent-totals { display: flex; flex-wrap: wrap; gap: 32px; padding: 20px 0; }
.agent-totals strong { font-size: 28px; font-variant-numeric: tabular-nums; }
.agent-totals span { display: block; color: hsl(var(--muted-foreground)); font-size: 12px; }
.agent-table { overflow-x: auto; margin: 12px 0; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
caption { text-align: left; color: hsl(var(--muted-foreground)); padding: 8px 0; }
th, td { text-align: left; padding: 12px; border-bottom: 1px solid hsl(var(--border)); white-space: nowrap; font-variant-numeric: tabular-nums; }
th { background: hsl(var(--muted)); font-weight: 500; }
a { color: hsl(var(--primary)); text-decoration: underline; text-underline-offset: 3px; }
summary { cursor: pointer; padding: 8px 0; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
.agent-history li, .agent-warnings li, .agent-sources li { margin: 6px 0; overflow-wrap: anywhere; }
.agent-warnings { margin: 12px 0; }
input:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid hsl(var(--primary)); outline-offset: 3px; }
@media (max-width: 640px) { .agent-page { padding: 12px; } .agent-header { flex-direction: column; gap: 12px; } .agent-input, .agent-status, .agent-result { padding: 16px; } }
</style>
