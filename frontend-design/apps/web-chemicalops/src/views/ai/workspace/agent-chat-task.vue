<script setup lang="ts">
import type { AgentApi, AiApi } from '#/api';
import { AI_TASK_STATUS_LABELS } from '#/api';
import { computed, ref, watch } from 'vue';
import { useAccess } from '@vben/access';
import { Button } from 'antdv-next';
import { formatDate, formatDateTime } from '#/utils/format';
import { agentDisplayNumber, inventoryProductLabel, inventorySummary, primaryTaskResults } from './task-view';
import AgentSourcePopover from './agent-source-popover.vue';
import { inventorySource, TASK_ERROR_HELP, TASK_LABELS, TOOL_LABELS, waitingCandidates } from './task-view';
const props = withDefaults(defineProps<{ task: AgentApi.Task; busy: boolean; showActions?: boolean; progress?: AiApi.BatchProgress; compactDetails?: boolean }>(), { showActions: true, compactDetails: false });
const emit = defineEmits<{ continue: [data: AgentApi.Continue] }>();
const { hasAccessByCodes } = useAccess();
const selection = ref<number | 'all'>();
const candidates = computed(() => waitingCandidates(props.task));
const results = computed(() => primaryTaskResults(props.task));
const showInventorySummary = computed(() => !props.compactDetails && props.task.status === 'SUCCEEDED' && results.value.length > 1 && results.value.every((entry) => entry.result?.tool === 'inventory.query_available'));
const hasDedicatedResult = computed(() => results.value.some((entry) => entry.result?.tool === 'inventory.query_available' || entry.result?.tool === 'supplier_quotes.compare'));
const inventoryContext = computed(() => {
  const inventory = results.value.flatMap((entry) => entry.result?.tool === 'inventory.query_available' ? [entry.result] : []);
  return {
    scopes: [...new Set(inventory.map((result) => result.scope))],
    warnings: [...new Set(inventory.flatMap(visibleWarnings))],
    times: [...new Set(inventory.map((result) => formatDateTime(result.observed_at)))],
  };
});
watch(() => props.task.revision, () => { selection.value = undefined; });
function choose() {
  const data: AgentApi.Continue = { question: '使用本次选中的候选继续原查询目标', revision: props.task.revision };
  if (candidates.value?.tool === 'catalog.search_products') {
    if (selection.value === 'all') {
      emit('continue', { ...data, all_products: true, question: '全选本次产品候选，汇总查询全部规格的库存' });
      return;
    }
    const row = candidates.value.rows.find((item) => item.product_id === selection.value);
    if (!row) return;
    data.product_id = row.product_id;
    data.question = `选择 ${row.product_name} · ${row.product_code}（${row.model || '未登记型号'} / ${row.packaging_spec || '未登记包装'}）继续查询`;
  }
  if (candidates.value?.tool === 'supplier_quotes.find_rfq_items') {
    const row = candidates.value.rows.find((item) => item.rfq_item_id === selection.value);
    if (!row) return;
    data.rfq_item_id = row.rfq_item_id;
    data.question = `选择询价 ${row.rfq_no}（${row.specification || '未登记规格'}）继续查询`;
  }
  emit('continue', data);
}
function visibleWarnings(result: AgentApi.Result) {
  return 'warnings' in result ? [...new Set(result.warnings)].filter((text) => !text.includes('截断')) : [];
}
function quoteRecommendationLines(result?: AgentApi.Result) {
  if (!result || result.tool !== 'supplier_quotes.compare' || !result.recommendation) return [];
  const recommendation = result.recommendation;
  const lines = recommendation.status === 'RECOMMENDED'
    ? [`成本候选：${result.rows.find((row) => row.quote_id === recommendation.candidate_quote_id)?.supplier_name ?? `报价 #${recommendation.candidate_quote_id}`} · ${recommendation.currency_code} ${agentDisplayNumber(recommendation.total_cost ?? '-')}`]
    : ['未生成唯一成本候选。'];
  lines.push(...recommendation.reasons, ...recommendation.risks.map((risk) => `待核实：${risk}`));
  return lines;
}
</script>
<template>
  <article class="agent-chat">
    <header v-if="!compactDetails" class="agent-header">
      <div class="agent-state" :class="`is-${task.status.toLowerCase()}`" aria-live="polite">
        <span class="agent-state-icon" aria-hidden="true">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path v-if="task.status === 'SUCCEEDED'" d="m5 10 3 3 7-7"/><template v-else><circle cx="10" cy="10" r="6.5"/><path d="M10 6v4l2.5 1.5"/></template></svg>
        </span>
        <span>{{ TASK_LABELS[task.status] }}</span>
        <span class="agent-readonly">只读查询</span>
      </div>
    </header>

    <template v-if="showInventorySummary">
      <p class="agent-reply"><strong>{{ inventorySummary(task) }}</strong><AgentSourcePopover v-for="entry in results" :key="entry.step" :result="entry.result!" /></p>
      <p class="agent-muted">各规格的库存和来源已整理在下方，展开即可查看。</p>
      <details class="mt-3 border-t border-border/50 pt-2">
        <summary class="text-muted-foreground cursor-pointer select-none text-xs font-medium">规格明细与数据来源（{{ results.length }} 个规格）</summary>
        <AgentChatTask :task="task" :busy="false" :show-actions="false" compact-details />
      </details>
    </template>
    <template v-else>
    <template v-if="progress">
      <p class="agent-reply" aria-live="polite">已完成 {{ progress.completed }}/{{ progress.total }} 项查询</p>
      <ol class="agent-prose"><li v-for="entry in progress.tasks" :key="entry.id">{{ entry.question }} · {{ AI_TASK_STATUS_LABELS[entry.status] }}</li></ol>
      <p class="agent-muted">查询进度会自动更新，已完成结果会保留。</p>
    </template>
    <template v-else>
      <p v-if="task.status !== 'SUCCEEDED' || !results.length" class="agent-reply">{{ task.status === 'RUNNING' ? '正在核对产品和业务数据…' : task.reply }}</p>
      <p v-else-if="!hasDedicatedResult && task.reply" class="agent-reply">{{ task.reply }}</p>
      <p v-if="task.status === 'RUNNING'" class="agent-muted">查询结果会自动更新。</p>
    </template>
    <p v-if="task.error_code" class="agent-error">{{ TASK_ERROR_HELP[task.error_code] || '请核对条件、权限及模型服务后重新查询。' }}（{{ task.error_code }}）</p>

    <form v-if="candidates && showActions !== false" class="agent-selection" @submit.prevent="choose">
      <fieldset :disabled="busy">
        <legend>{{ candidates.tool === 'catalog.search_products' ? '选择需要查询的规格' : '选择需要比较的询价' }}</legend>
        <div class="agent-choices">
          <template v-if="candidates.tool === 'catalog.search_products'">
            <label v-if="!candidates.truncated && task.can_select_all_products" class="agent-choice">
              <input v-model="selection" type="radio" :name="task.id" value="all" />
              <span class="agent-choice-copy"><strong>全选 · 查询全部规格</strong><span>汇总本次 {{ candidates.rows.length }} 个规格，按库存计量单位分别合计</span></span>
            </label>
            <label v-for="row in candidates.rows" :key="row.product_id" class="agent-choice">
              <input v-model="selection" type="radio" :name="task.id" :value="row.product_id" />
              <span class="agent-choice-copy"><strong>{{ row.product_name }}</strong><span>{{ row.model || '未登记型号' }} · 包装：{{ row.packaging_spec || '未登记' }} · 计量单位：{{ row.unit_name }}</span><small>{{ row.product_code }}</small></span>
            </label>
          </template>
          <template v-else-if="candidates.tool === 'supplier_quotes.find_rfq_items'">
            <label v-for="row in candidates.rows" :key="row.rfq_item_id" class="agent-choice">
              <input v-model="selection" type="radio" :name="task.id" :value="row.rfq_item_id" />
              <span class="agent-choice-copy"><strong>{{ row.rfq_no }}</strong><span>{{ row.specification || '未登记规格' }}</span><small>{{ row.technical_requirements || '无技术要求' }} · 明细 {{ row.rfq_item_id }}</small></span>
            </label>
          </template>
        </div>
      </fieldset>
      <div class="agent-selection-footer"><p>也可以在输入框补充更精确的条件{{ candidates.truncated ? '；当前候选未完整返回' : '' }}。</p><Button html-type="submit" type="primary" :disabled="busy || selection === undefined">继续查询</Button></div>
    </form>
    <p v-else-if="task.status === 'WAITING_INPUT'" class="agent-muted">在下方输入框补充信息，即可继续。</p>
    <p v-if="!compactDetails && task.status === 'SUCCEEDED' && results.length > 1" class="agent-intro">查到以下结果：</p>
    <template v-if="compactDetails && inventoryContext.scopes.length">
      <p class="agent-muted">查询范围：{{ inventoryContext.scopes.join('；') }}。</p>
      <p v-if="inventoryContext.warnings.length" class="agent-muted">{{ inventoryContext.warnings.join(' ') }}</p>
      <p class="agent-snapshot">{{ inventoryContext.times.join('；') }}（本地时间）查询快照</p>
    </template>

    <section v-for="entry in results" :key="entry.step" class="agent-result">
      <template v-if="entry.result?.tool === 'inventory.query_available'">
        <ol class="agent-prose">
          <li><strong>{{ inventoryProductLabel(task, entry.result.product_id, entry.result.product_name) }}<span v-if="entry.result.totals.length">，可用库存为 <template v-for="(total, i) in entry.result.totals" :key="i">{{ i ? '、' : '' }}{{ agentDisplayNumber(total.available_quantity) }} {{ total.unit_name }}</template>。</span><span v-else>：暂时没有找到库存记录。</span></strong><AgentSourcePopover :result="entry.result" /></li>
          <li v-if="!compactDetails && entry.result.total_rows > 0">下方可查看仓库、批次及对应库存。<span v-if="entry.result.truncated">合计包含全部匹配记录，明细展示其中 <strong>{{ entry.result.rows.length }} / {{ entry.result.total_rows }} 条</strong>。</span></li>
        </ol>
        <details v-if="entry.result.total_rows > 0" class="agent-disclosure">
          <summary><span>库存明细</span><span class="agent-count">{{ entry.result.rows.length }}{{ entry.result.truncated ? ` / ${entry.result.total_rows}` : '' }} 条</span></summary>
          <template v-if="!compactDetails">
            <p class="agent-muted">查询范围：{{ entry.result.scope }}。</p>
            <p v-for="warning in visibleWarnings(entry.result)" :key="warning" class="agent-muted">{{ warning }}</p>
          </template>
          <div class="agent-table"><table><caption class="sr-only">库存明细与来源</caption><thead><tr><th>仓库 / 批次</th><th class="agent-numeric">可用量</th><th>状态 / 有效期</th><th>来源</th></tr></thead><tbody>
            <tr v-for="row in entry.result.rows" :key="row.balance_id"><td><span>{{ row.warehouse_name }}</span><small>{{ row.batch_no }}</small></td><td class="agent-numeric">{{ agentDisplayNumber(row.available_quantity) }} {{ row.unit_name }}</td><td><span>{{ row.status === 'AVAILABLE' ? '可用' : row.status === 'FROZEN' ? '冻结' : row.status }}</span><small>{{ row.expiry_date ? formatDate(row.expiry_date) : '未登记有效期' }}</small></td><td><RouterLink v-if="hasAccessByCodes(['warehouse.inventory.read'])" :to="inventorySource(entry.result.product_id, row.warehouse_id)">查看库存 ↗</RouterLink><small>余额 #{{ row.balance_id }}</small></td></tr>
          </tbody></table></div>
        </details>
      </template>
      <template v-else-if="entry.result?.tool === 'supplier_quotes.compare'">
        <ol class="agent-prose">
          <li><strong>询价 {{ entry.result.rfq_no }} 的供应商报价。</strong>查到 <strong>{{ entry.result.rows.length }} 条</strong>报价明细；规格为 {{ entry.result.specification || '未登记规格' }}，技术要求为 {{ entry.result.technical_requirements || '无技术要求' }}。<span v-if="entry.result.total_rows === 0">暂时没有找到符合条件的最新报价。</span><AgentSourcePopover :result="entry.result" /></li>
          <li><strong>比较口径。</strong>{{ entry.result.comparison_basis }}。<strong>不同可比组的排名不能相互比较。</strong></li>
        </ol>
        <div v-if="quoteRecommendationLines(entry.result).length" class="agent-notice">
          <span aria-hidden="true">ⓘ</span>
          <div>
            <p v-for="line in quoteRecommendationLines(entry.result)" :key="line">{{ line }}</p>
          </div>
        </div>
        <details v-if="entry.result.total_rows > 0" class="agent-disclosure">
          <summary><span>查看报价与可比组排名</span><span class="agent-count">{{ entry.result.rows.length }}{{ entry.result.truncated ? ` / ${entry.result.total_rows}` : '' }} 条</span></summary>
          <div class="agent-table"><table><caption class="sr-only">报价明细；不同可比组不能相互比较</caption><thead><tr><th>供应商 / 报价</th><th class="agent-numeric">报价单价</th><th>型号 / 税务口径</th><th>组内排名</th><th>报价量 / MOQ / 交期 / 账期</th><th>总成本</th><th>日期 / 有效期</th></tr></thead><tbody>
            <tr v-for="row in entry.result.rows" :key="row.quote_item_id"><td>{{ row.supplier_name }}<small>{{ row.quote_no }} · v{{ row.quote_version }}</small></td><td class="agent-numeric">{{ agentDisplayNumber(row.unit_price) }}<small>{{ row.currency_code }}/{{ row.unit_name }}</small></td><td>{{ row.supplier_model ?? '未登记' }}<small>{{ row.tax_rate === null ? '税率未知' : `${agentDisplayNumber(row.tax_rate)}%` }} · {{ row.tax_included === null ? '含税口径未知' : row.tax_included ? '含税价' : '未税价' }}</small></td><td>{{ row.rank ?? '不排序' }}<small v-if="row.comparison_reasons.length">{{ row.comparison_reasons.join('；') }}</small></td><td>{{ agentDisplayNumber(row.quoted_quantity) }} {{ row.unit_name }}<small>MOQ {{ row.moq_quantity === null ? '未知' : agentDisplayNumber(row.moq_quantity) }} · {{ row.lead_days === null ? '交期未知' : `${row.lead_days} 天` }}</small><small>账期 {{ row.payment_terms ?? '未知' }}</small></td><td><template v-if="row.cost_analysis?.complete">货款 {{ agentDisplayNumber(row.cost_analysis.goods_amount ?? '-') }} + 税 {{ agentDisplayNumber(row.cost_analysis.goods_tax ?? '-') }}<small>运费 {{ agentDisplayNumber(row.cost_analysis.freight_amount ?? '-') }} + 税 {{ agentDisplayNumber(row.cost_analysis.freight_tax ?? '-') }}</small><small>MOQ补量 {{ agentDisplayNumber(row.cost_analysis.moq_extra_quantity ?? '0') }} {{ row.unit_name }} · 合计 {{ row.currency_code }} {{ agentDisplayNumber(row.cost_analysis.total_cost ?? '-') }}</small></template><small v-else>{{ row.cost_analysis?.reasons.join('；') || '总成本信息不完整' }}</small></td><td>{{ formatDate(row.quote_date) }}<small>{{ row.valid_until ? formatDate(row.valid_until) : '未登记有效期' }}</small></td></tr>
          </tbody></table></div>
        </details>
        <p v-if="entry.result.truncated" class="agent-muted">报价已截断，当前结果不代表完整比较。</p>
        <RouterLink v-if="hasAccessByCodes(['procurement.rfqs.read'])" class="agent-source-link" :to="{ path: '/procurement/rfqs', query: { ai_record_id: entry.result.rfq_id } }">查看询价原记录 ↗</RouterLink>
      </template>
      <p v-else-if="entry.result?.total_rows === 0" class="agent-empty">{{ entry.result.tool === 'catalog.search_products' ? '当前授权范围未找到匹配产品。' : '当前授权范围未找到可用询价明细。' }}</p>
      <template v-if="entry.result">
        <div v-if="entry.result.tool !== 'inventory.query_available' && visibleWarnings(entry.result).length" class="agent-notice"><span aria-hidden="true">ⓘ</span><div><p v-for="warning in visibleWarnings(entry.result)" :key="warning">{{ warning }}</p></div></div>
        <p v-if="'observed_at' in entry.result && !(compactDetails && entry.result.tool === 'inventory.query_available')" class="agent-snapshot">{{ formatDateTime(entry.result.observed_at) }}（本地时间）查询快照</p>
      </template>
      <AgentSourcePopover v-if="entry.result && !['inventory.query_available', 'supplier_quotes.compare'].includes(entry.result.tool)" :result="entry.result" />
    </section>

    <details v-if="task.trace.length" class="agent-audit">
      <summary>查询过程与来源 <span>{{ task.trace.length }} 步</span></summary>
      <ol>
        <li v-for="entry in task.trace" :key="entry.step">
          <div class="agent-step-heading"><span class="agent-step-number">{{ entry.step }}</span><strong>{{ TOOL_LABELS[entry.tool || ''] || (entry.action === 'ask_user' ? '补充条件' : entry.action === 'finish' ? '汇总结果' : '停止查询') }}</strong><span>{{ entry.status === 'SUCCEEDED' ? '已完成' : entry.status === 'WAITING_INPUT' ? '曾等待补充' : '已停止' }}</span></div>
          <p v-if="entry.question" class="agent-muted">{{ entry.question }}</p>
          <template v-if="entry.result">
            <p class="agent-muted">匹配 {{ entry.result.total_rows }} 条记录{{ entry.result.truncated ? '，返回明细已截断' : '' }}。</p>
            <ul v-if="entry.result.tool === 'catalog.search_products'" class="agent-audit-records"><li v-for="row in entry.result.rows" :key="row.product_id">{{ row.product_name }} · {{ row.product_code }} · {{ row.model || '未登记型号' }} / {{ row.packaging_spec || '未登记包装' }} / {{ row.unit_name }}</li></ul>
            <ul v-if="entry.result.tool === 'supplier_quotes.find_rfq_items'" class="agent-audit-records"><li v-for="row in entry.result.rows" :key="row.rfq_item_id">{{ row.rfq_no }} · 明细 {{ row.rfq_item_id }} · {{ row.specification || '未登记规格' }} / {{ row.technical_requirements || '无技术要求' }}</li></ul>
            <AgentSourcePopover :result="entry.result" />
          </template>
        </li>
      </ol>
    </details>
    </template>
  </article>
</template>
<style scoped>
.agent-chat { color: inherit; font-size: 14px; line-height: 1.85; }
.agent-intro { margin: 12px 0; }
.agent-prose { list-style: decimal; margin: 0 0 12px; padding-left: 24px; }
.agent-prose li { padding-left: 3px; margin: 8px 0; }
.agent-prose li::marker, .agent-prose strong { font-weight: 600; }
.agent-prose :deep(.source-pill) { margin-left: 6px; vertical-align: middle; }
.agent-header, .agent-state, .agent-result-heading { display: flex; align-items: center; }
.agent-header { justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.agent-state { gap: 8px; font-size: 13px; font-weight: 600; }
.agent-state-icon { display: grid; place-items: center; width: 24px; height: 24px; color: hsl(var(--primary)); background: hsl(var(--primary) / .08); border-radius: 50%; }
.agent-state-icon svg { width: 18px; height: 18px; }
.is-succeeded .agent-state-icon { color: #27845f; background: #edf8f1; }
.is-failed .agent-state-icon { color: hsl(var(--destructive)); background: hsl(var(--destructive) / .08); }
.agent-readonly { margin-left: 4px; padding-left: 12px; border-left: 1px solid hsl(var(--border)); color: hsl(var(--muted-foreground)); font-size: 12px; font-weight: 400; }
.agent-reply { margin: 12px 0; white-space: pre-wrap; }
.agent-muted, .agent-comparison { color: hsl(var(--muted-foreground)); font-size: 12px; margin: 8px 0; }
.agent-result { margin-top: 16px; }
.agent-result + .agent-result { padding-top: 20px; border-top: 1px solid hsl(var(--border)); }
.agent-result-heading { gap: 12px; flex-wrap: wrap; }
.agent-result-heading > span { font-size: 12px; color: hsl(var(--muted-foreground)); }
.agent-disclosure { border-top: 1px solid hsl(var(--border)); border-bottom: 1px solid hsl(var(--border)); }
summary { cursor: pointer; font-size: 12px; color: hsl(var(--muted-foreground)); padding: 12px 0; }
summary:hover { color: hsl(var(--primary)); }
.agent-disclosure summary > span:first-child { margin-left: 4px; color: hsl(var(--foreground)); font-weight: 500; }
.agent-count { margin-left: 12px; font-variant-numeric: tabular-nums; }
.agent-table { overflow: auto; max-height: 320px; margin-bottom: 12px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { padding: 10px 12px; text-align: left; white-space: nowrap; border-bottom: 1px solid hsl(var(--border)); }
th { position: sticky; top: 0; z-index: 1; background: hsl(var(--muted)); color: hsl(var(--muted-foreground)); font-weight: 500; }
td { background: hsl(var(--background)); }
td small { display: block; font-size: 11px; color: hsl(var(--muted-foreground)); margin-top: 3px; }
.agent-numeric { text-align: right; font-variant-numeric: tabular-nums; }
a { color: hsl(var(--primary)); text-decoration: none; }
a:hover { text-decoration: underline; }
.agent-source-link { display: inline-block; font-size: 12px; margin-top: 4px; }
.agent-notice { display: flex; align-items: flex-start; gap: 8px; margin-top: 14px; color: hsl(var(--muted-foreground)); font-size: 12px; }
.agent-notice p { margin: 0; }
.agent-snapshot { color: hsl(var(--muted-foreground)); font-size: 11px; margin: 12px 0; }
.agent-empty { padding: 16px 0; color: hsl(var(--muted-foreground)); }
.agent-audit { border-top: 1px solid hsl(var(--border)); margin-top: 16px; }
.agent-audit > summary > span { margin-left: 8px; }
.agent-audit ol { list-style: none; margin: 0; padding: 0 0 12px; }
.agent-audit li { padding: 10px 0; }
.agent-step-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 12px; }
.agent-step-heading > span:last-child { color: hsl(var(--muted-foreground)); font-size: 11px; }
.agent-step-number { color: hsl(var(--muted-foreground)); width: 20px; }
.agent-audit-records, .agent-sources ul { font-size: 12px; color: hsl(var(--muted-foreground)); overflow-wrap: anywhere; }
.agent-audit-records li, .agent-sources li { padding: 2px 0; }
.agent-error { color: hsl(var(--destructive)); }
fieldset { border: 0; padding: 0; margin: 20px 0 16px; min-width: 0; }
legend { font-weight: 600; margin-bottom: 12px; font-size: 13px; }
.agent-choices { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.agent-choice { display: flex; gap: 10px; align-items: flex-start; padding: 12px; border: 1px solid hsl(var(--border)); border-radius: 10px; cursor: pointer; background: hsl(var(--background)); transition: border-color .15s; }
.agent-choice:hover { border-color: hsl(var(--primary) / .45); }
.agent-choice:has(input:checked) { border-color: hsl(var(--primary)); background: hsl(var(--primary) / .035); }
.agent-choice input { margin-top: 5px; accent-color: hsl(var(--primary)); }
.agent-choice-copy { display: grid; gap: 3px; min-width: 0; overflow-wrap: anywhere; }
.agent-choice-copy strong { font-size: 13px; font-weight: 600; }
.agent-choice-copy > span { font-size: 12px; }
.agent-choice-copy small { color: hsl(var(--muted-foreground)); font-size: 11px; }
.agent-selection-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.agent-selection-footer p { font-size: 12px; color: hsl(var(--muted-foreground)); margin: 0; }
input:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid hsl(var(--primary)); outline-offset: 3px; }
@media (max-width: 640px) { .agent-header { gap: 8px; flex-wrap: wrap; } .agent-readonly { display: none; } .agent-choices { grid-template-columns: 1fr; } .agent-selection-footer { align-items: flex-start; flex-direction: column; } }
</style>
