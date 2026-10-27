<script lang="ts" setup>
/** 全局化工助手的业务上下文面板；复用 Vben 抽屉和工作台对话组件风格。 */
import type { AiApi } from '#/api';

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';
import { useAccessStore } from '@vben/stores';
import { IconifyIcon } from '@vben/icons';

import { Button, Dropdown, Input, Spin, Tag } from 'antdv-next';

import { askPageContextApi, askPurchaseOrderListContextApi, streamChatApi, streamPageContextApi } from '#/api';
import { answerSources } from '../answer-sources';
import ChemicalAssistantMark from './ChemicalAssistantMark.vue';
import { PanelAnswerCache, openingAction, sameAuthorizedEvidence, shouldDismissAssistant } from './floating-panel-state';
import { renderMarkdown } from '#/utils/markdown';
import { activeListCopilotContext, activePageCopilotContext } from '#/utils/page-copilot-context';

const emit = defineEmits<{ 'open-change': [isOpen: boolean] }>();

interface Turn {
  question: string;
  result: AiApi.ContextAskResult;
  trace?: AiApi.OrderTrace;
  incomplete?: boolean;
  sources?: ReturnType<typeof answerSources>;
}

const turns = ref<Turn[]>([]);
const question = ref('');
const loading = ref(false);
const canRestore = ref(false);
const openingQuestion = ref('');
const progressMessage = ref('');
const generalMode = ref(false);
const conversationId = ref<null | number>(null);
let streamAbort: AbortController | undefined;
let requestEpoch = 0;
const cache = new PanelAnswerCache<Turn>();
let currentCacheKey = '';
const panelVisible = ref(false);
const accessStore = useAccessStore();
watch(() => accessStore.accessToken, () => { cache.clear(); turns.value = []; conversationId.value = null; });
function cacheKey(target: { objectId: number; objectType: AiApi.ContextObjectType; general?: boolean; feature?: string; listFilters?: { keyword?: string; status?: string } }) {
  return target.general ? `general:${target.feature ?? 'orders'}` : target.listFilters ? `orders:${JSON.stringify(target.listFilters)}` : `${target.objectType}:${target.objectId}`;
}
function saveCompleted() {
  if (!currentCacheKey) return;
  const completed = turns.value.filter((item) => !item.incomplete);
  // 通用查询的历史来源可能因撤权而不可访问，不能仅凭会话归属恢复业务结果。
  if (currentCacheKey.startsWith('general:') && completed.some((item) => item.sources?.length || ['text2sql', 'multi-intent'].includes(item.result.model))) {
    cache.delete(currentCacheKey);
    return;
  }
  cache.save(currentCacheKey, completed, conversationId.value);
}
function onDocumentPointerDown(event: PointerEvent) {
  const target = event.target instanceof Element ? event.target : null;
  if (shouldDismissAssistant(panelVisible.value, target)) void drawerApi.close();
}
onMounted(() => document.addEventListener('pointerdown', onDocumentPointerDown, true));
const errorMessage = ref('');
const targetType = ref<AiApi.ContextObjectType>('purchase_order');
const targetId = ref(0);
const listFilters = ref<{ keyword?: string; status?: string } | null>(null);
const listRef = ref<HTMLElement>();
const panelWidth = ref(560);
const resizeHandle = ref<HTMLElement>();
let resizeStart: { x: number; width: number } | undefined;

const contextTypeLabel = computed(() => generalMode.value ? '通用对话' : listFilters.value ? '采购订单列表' : ({
  delivery: '到货单',
  finance_reconciliation: '财务对账单',
  inventory_balance: '库存余额',
  purchase_order: '采购订单',
  purchase_request: '采购申请',
  quality_acceptance: '质量验收单',
  rfq: '询价单',
  supplier: '供应商',
})[targetType.value]);
const pageScopeLabel = computed(() => {
  const page = activePageCopilotContext.value;
  if (page) return ({ delivery: '到货单', finance_reconciliation: '财务对账单', inventory_balance: '库存余额',
    purchase_order: '采购订单', purchase_request: '采购申请', quality_acceptance: '质量验收单',
    rfq: '询价单', supplier: '供应商' } as Record<AiApi.ContextObjectType, string>)[page.objectType];
  return activeListCopilotContext.value ? '采购订单列表' : undefined;
});
const generalFeature = ref<'orders' | 'knowledge' | 'guidance'>('orders');
const scopeOptions = computed(() => [
  ...(pageScopeLabel.value ? [{ label: `当前${pageScopeLabel.value}`, value: 'page' }] : []),
  { label: '订单与业务查询', value: 'orders' },
  { label: '化工资料查询', value: 'knowledge' },
  { label: '操作指引', value: 'guidance' },
]);
const selectedScope = computed(() => generalMode.value ? generalFeature.value : 'page');
const scopeTitle = computed(() => scopeOptions.value.find((option) => option.value === selectedScope.value)?.label ?? '选择功能');
const menuItems = computed(() => scopeOptions.value.map((option) => ({ key: option.value, label: option.label })));
const featureExamples = computed(() => ({
  orders: ['采购订单有哪些状态？', '如何查看订单到货进展？', '怎样查询采购申请？', '在哪里查看供应商信息？'],
  knowledge: ['如何查找化工品安全资料？', '怎样查询产品规格？', '如何查看质量验收信息？', '如何查找产品相关文档？'],
  guidance: ['如何创建采购申请？', '采购订单如何提交审批？', '怎样查看订单到货进度？', '如何查看任务处理进度？'],
})[generalFeature.value]);
const pageExamples: Record<AiApi.ContextObjectType, string[]> = {
  purchase_order: ['这单当前进展和卡点是什么？', '这单为什么还没结算？', '还差哪些单据或环节？', '相关到货和验收情况如何？'],
  purchase_request: ['这份申请当前是什么状态？', '关联询价与报价进展如何？', '关联订单的到货和验收情况如何？', '采购流程卡在哪个环节？'],
  delivery: ['这张到货单当前进展如何？', '关联订单是什么状态？', '到货数量情况如何？', '哪些信息还未登记？'],
  inventory_balance: ['这笔库存有多少可用量？', '库存当前是什么状态？', '这个批次何时到期？', '库存所在仓库和库位是什么？'],
  quality_acceptance: ['这张验收单的检测结果是什么？', '验收结论是什么？', '质量证明文件状态如何？', '关联到货单有哪些检测明细？'],
  finance_reconciliation: ['这张对账单目前是什么状态？', '发票和付款进展如何？', '对账金额是多少？', '付款前还需要核对什么？'],
  supplier: ['这家供应商的合作状态是什么？', '供应商的合作等级是什么？', '默认交货天数是多少？', '付款条件是什么？'],
  rfq: ['这份询价当前进展如何？'],
};
const initialQuestions = computed(() => {
  if (generalMode.value) return featureExamples.value;
  const items = listFilters.value
    ? ['当前筛选范围内的订单情况如何？', '这些订单有哪些状态？', '哪些订单的预计到货日期已过？', '哪些订单未填写预计到货日期？']
    : pageExamples[targetType.value];
  return [...new Set([openingQuestion.value, ...items].filter(Boolean))].slice(0, 4);
});
const visibleSuggestions = computed(() => turns.value.length ? (turns.value.at(-1)?.incomplete ? [] : turns.value.at(-1)?.result.context.suggested_questions ?? []) : initialQuestions.value);
const maxPanelWidth = computed(() => Math.min(920, window.innerWidth - 8));
const widthStyle = computed(() => ({
  width: window.innerWidth <= 640 ? '100vw' : `${Math.min(panelWidth.value, window.innerWidth - 8)}px`,
  maxWidth: window.innerWidth <= 640 ? '100vw' : 'calc(100vw - 8px)',
}));

function clampWidth(value: number) {
  panelWidth.value = Math.max(420, Math.min(value, Math.min(920, window.innerWidth - 8)));
}

function onResizeDown(event: PointerEvent) {
  if (window.innerWidth <= 640) return;
  event.preventDefault();
  resizeStart = { x: event.clientX, width: panelWidth.value };
  resizeHandle.value?.setPointerCapture(event.pointerId);
  window.addEventListener('pointermove', onResizeMove);
  window.addEventListener('pointerup', onResizeEnd, { once: true });
  window.addEventListener('pointercancel', onResizeEnd, { once: true });
}

function onResizeMove(event: PointerEvent) {
  if (resizeStart) clampWidth(resizeStart.width + resizeStart.x - event.clientX);
}

function onResizeEnd() {
  resizeStart = undefined;
  window.removeEventListener('pointermove', onResizeMove);
}

function onResizeKeydown(event: KeyboardEvent) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
  event.preventDefault();
  clampWidth(panelWidth.value + (event.key === 'ArrowLeft' ? 24 : -24));
}

const [Drawer, drawerApi] = useVbenDrawer<{
  objectId: number;
  objectType: AiApi.ContextObjectType;
  question?: string;
  listFilters?: { keyword?: string; status?: string };
  general?: boolean;
  feature?: 'orders' | 'knowledge' | 'guidance';
}>({
  footer: false,
  async onOpenChange(isOpen) {
    panelVisible.value = isOpen;
    emit('open-change', isOpen);
    if (!isOpen) { saveCompleted(); requestEpoch++; streamAbort?.abort(); streamAbort = undefined; loading.value = false; return; }
    const target = drawerApi.getData();
    turns.value = [];
    errorMessage.value = '';
    if (!target) return;
    currentCacheKey = cacheKey(target);
    generalMode.value = Boolean(target.general);
    if (target.feature) generalFeature.value = target.feature;
    conversationId.value = null;
    listFilters.value = target.listFilters ?? null;
    targetType.value = target.objectType;
    targetId.value = target.objectId;
    const defaultQuestions: Record<AiApi.ContextObjectType, string> = {
      delivery: '这张到货单当前的收货进展是什么？',
      finance_reconciliation: '这张对账单的状态、发票和付款进展如何？',
      inventory_balance: '这笔库存余额当前是什么状态？',
      purchase_order: '这单当前进展和卡点是什么？',
      purchase_request: '这份申请当前是什么状态？',
      quality_acceptance: '这张验收单的检测结果和结论是什么？',
      rfq: '这份询价当前进展如何？',
      supplier: '这家供应商的合作状态和基本资料是什么？',
    };
    openingQuestion.value = generalMode.value ? '' : target.question ?? (listFilters.value ? '当前筛选范围内的订单情况如何？' : defaultQuestions[target.objectType]);
    question.value = target.question ?? '';
    const saved = cache.get(currentCacheKey);
    const action = openingAction(generalMode.value, Boolean(saved));
    canRestore.value = action === 'confirm_restore';
    if (action === 'restore_local' && saved) {
      turns.value = JSON.parse(JSON.stringify(saved.turns));
      conversationId.value = saved.conversationId;
      await scrollToLatest();
    }

  },
});

/** 用户主动查看历史后，先重验全部业务来源，再恢复旧回答。 */
async function restorePrevious() {
  const saved = cache.get(currentCacheKey);
  if (!saved || loading.value || generalMode.value) return;
  const epoch = ++requestEpoch;
  loading.value = true;
  errorMessage.value = '';
  try {
    const latest = listFilters.value
      ? await askPurchaseOrderListContextApi('核验当前列表范围', listFilters.value)
      : await askPageContextApi('核验当前页面权限', targetType.value, targetId.value);
    if (!sameAuthorizedEvidence(saved.turns.map((turn) => turn.result), latest)) {
      throw new Error('页面数据或访问范围已变化，请重新提问。');
    }
    if (epoch !== requestEpoch) return;
    turns.value = JSON.parse(JSON.stringify(saved.turns));
    conversationId.value = saved.conversationId;
    canRestore.value = false;
    question.value = '';
    await scrollToLatest();
  } catch (error: any) {
    if (epoch === requestEpoch) { cache.delete(currentCacheKey); canRestore.value = false; errorMessage.value = error?.message || '当前内容已不可访问，请检查权限后重试。'; }
  } finally { if (epoch === requestEpoch) loading.value = false; }
}

/** 业务事实由服务端读取，正文使用真实 SSE 模型增量。 */
async function ask(next?: string) {
  const text = (next ?? question.value).trim();
  if (!text || loading.value) return;
  canRestore.value = false;
  if (listFilters.value && activeListCopilotContext.value) {
    const nextFilters = { ...activeListCopilotContext.value.filters };
    const nextKey = cacheKey({ objectId: 0, objectType: 'purchase_order', listFilters: nextFilters });
    if (nextKey !== currentCacheKey) { saveCompleted(); currentCacheKey = nextKey; turns.value = []; }
    listFilters.value = nextFilters;
  }
  const epoch = ++requestEpoch;
  const abort = new AbortController();
  streamAbort = abort;
  const history = turns.value.filter((item) => !item.incomplete).flatMap((item) => [
    { role: 'user' as const, content: item.question },
    { role: 'assistant' as const, content: item.result.answer },
  ]).filter((item) => item.content);
  const emptyContext: AiApi.ContextSnapshot = { object_type: targetType.value, object_id: null,
    title: generalMode.value ? '通用对话' : contextTypeLabel.value, summary: [], source_records: [], suggested_questions: [] };
  const turn: Turn = { question: text, result: { answer: '', citations: [], context: emptyContext, model: '', provider: 'chemicalops' }, incomplete: true };
  turns.value.push(turn);
  if (turns.value.length > 8) turns.value.shift();
  // 通过响应式数组引用更新，确保 Vue 能渲染流式增量。
  const current = turns.value.at(-1)!;
  loading.value = true; progressMessage.value = ''; errorMessage.value = ''; question.value = '';
  await scrollToLatest();
  try {
    if (generalMode.value) {
      let failed = '';
      await streamChatApi([...history, { role: 'user', content: text }], conversationId.value, {
        onDelta(part) { if (epoch === requestEpoch) { current.result.answer += part; void scrollToLatest(); } },
        onDone(done) {
          if (epoch !== requestEpoch) return;
          current.result.answer = done.answer ?? current.result.answer;
          current.result.model = done.model ?? 'chat';
          current.sources = answerSources(done.citations ?? []);
          current.incomplete = false;
          conversationId.value = done.conversation_id ?? conversationId.value;
        },
        onProgress(progress) { if (epoch === requestEpoch) progressMessage.value = `正在处理 ${progress.completed}/${progress.total} 项`; },
        onError(msg) { failed = msg; },
      }, undefined, { independent: true, signal: abort.signal });
      if (failed) throw new Error(failed);
      if (!current.incomplete && epoch === requestEpoch) await scrollToLatest();
    } else {
      if (listFilters.value && !activeListCopilotContext.value) throw new Error('当前订单列表已离开，请重新打开列表');
      if (listFilters.value && activeListCopilotContext.value) listFilters.value = { ...activeListCopilotContext.value.filters };
      const target = listFilters.value ? { filters: listFilters.value } : { objectType: targetType.value, objectId: targetId.value };
      await streamPageContextApi(text, target, {
        onDelta(part) { if (epoch === requestEpoch) { current.result.answer += part; void scrollToLatest(); } },
        onDone(result) {
          if (epoch !== requestEpoch) return;
          current.result = result;
          const citation = result.citations.find((item) => item.type === 'order_trace' || item.type === 'purchase-request-trace');
          current.trace = citation?.order_trace ?? citation;
          current.incomplete = false;
        },
      }, abort.signal, history.filter((item) => item.role === 'user').slice(-4).map((item) => item.content));
    }
  } catch (error: any) {
    if (epoch !== requestEpoch || abort.signal.aborted) return;
    errorMessage.value = error?.message || '回答生成失败，请稍后重试';
    question.value = text;
  } finally {
    if (epoch === requestEpoch) { loading.value = false; streamAbort = undefined; await scrollToLatest(); }
  }
}

async function scrollToLatest() {
  await nextTick();
  const element = listRef.value;
  if (element) element.scrollTop = element.scrollHeight;
}

function stageColor(status: string) {
  if (status === 'AVAILABLE') return 'green';
  if (status === 'NO_PERMISSION') return 'gold';
  return 'blue';
}

function stageLabel(status: string) {
  return ({ AVAILABLE: '可见', NO_PERMISSION: '无权限' } as Record<string, string>)[status] ?? status;
}

function recordTitle(record: Record<string, any>) {
  const title = record.number ?? record.batch_id ?? '关联记录';
  return record.status ? `${title}（${record.status}）` : String(title);
}

function open(objectType: AiApi.ContextObjectType, objectId: number, initialQuestion?: string) {
  drawerApi.setData({ objectId, objectType, question: initialQuestion }).open();
}

function openGeneral() {
  drawerApi.setData({ objectId: 0, objectType: 'purchase_order', general: true, feature: generalFeature.value }).open();
}
async function switchMode(value: string) {
  if (value !== 'page') {
    if (generalMode.value && generalFeature.value === value) return;
    generalFeature.value = value as typeof generalFeature.value;
  } else if (!generalMode.value) return;
  const page = activePageCopilotContext.value;
  const list = activeListCopilotContext.value;
  await drawerApi.close();
  await nextTick();
  if (value !== 'page') openGeneral();
  else if (page) open(page.objectType, page.objectId, page.question);
  else if (list) openList(list.filters);
}

function openList(filters: { keyword?: string; status?: string }) {
  drawerApi.setData({ objectId: 0, objectType: 'purchase_order', listFilters: { ...filters } }).open();
}

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown, true);
  requestEpoch++; streamAbort?.abort();
  window.removeEventListener('pointermove', onResizeMove);
  window.removeEventListener('pointerup', onResizeEnd);
  window.removeEventListener('pointercancel', onResizeEnd);
});

defineExpose({ open, openList, openGeneral, close: () => drawerApi.close() });
</script>

<template>
  <Drawer
    :sheet-style="widthStyle"
    :content-class="'!p-0 overflow-hidden'"
    :header-class="'!hidden'"
    :footer="false"
    :modal="false"
    :close-on-click-modal="false"
    :title="'化工助手'"
    class="page-copilot-panel"
  >
    <section class="assistant-shell" aria-label="化工助手对话">
      <div
        ref="resizeHandle"
        class="assistant-resize-handle"
        role="separator"
        aria-label="调整助手面板宽度"
        aria-orientation="vertical"
        :aria-valuenow="panelWidth"
        :aria-valuemin="420"
        :aria-valuemax="maxPanelWidth"
        tabindex="0"
        @pointerdown="onResizeDown"
        @keydown="onResizeKeydown"
      >
        <span />
      </div>

      <header class="assistant-header">
        <div class="assistant-brand-mark" aria-hidden="true"><ChemicalAssistantMark /></div>
        <div class="assistant-heading">
          <h2>化工助手</h2>
        </div>
        <Dropdown :menu="{ items: menuItems, selectedKeys: [selectedScope] }" :trigger="['click']" placement="bottomRight" :disabled="loading" @menu-click="({ key }) => switchMode(String(key))">
          <Button type="primary" size="small" class="assistant-function" :disabled="loading" aria-label="选择助手功能">
            <span>{{ scopeTitle }}</span><IconifyIcon icon="lucide:chevron-down" class="assistant-function-icon" aria-hidden="true" />
          </Button>
        </Dropdown>
        <Button class="assistant-close" size="small" aria-label="关闭化工助手" @click="drawerApi.close()">×</Button>
      </header>


      <main ref="listRef" class="assistant-thread" aria-live="polite">
        <div v-if="!turns.length && !loading" class="assistant-empty">
          <div class="assistant-empty-emblem" aria-hidden="true"><div class="assistant-empty-mark"><ChemicalAssistantMark /></div></div>
          <div class="assistant-empty-title">你好，我是化工助手</div>
          <p class="assistant-empty-caption">选择一个问题，或直接输入你想了解的内容</p>
          <Button v-if="canRestore" size="small" @click="restorePrevious">查看上次回答</Button>
        </div>
        <article v-for="(turn, index) in turns" :key="`${index}-${turn.question}`" class="assistant-turn">
          <div class="assistant-question-row">
            <div class="assistant-question">{{ turn.question }}</div>
          </div>
          <div class="assistant-answer-row">
            <div class="assistant-answer-mark" aria-hidden="true"><ChemicalAssistantMark /></div>
            <div class="assistant-answer-content">
              <div class="assistant-answer-text" v-html="renderMarkdown(turn.result.answer)" />
              <div v-if="turn.incomplete && !loading && turn.result.answer" class="assistant-answer-meta">回答未完成，请重试。</div>

              <details v-if="!turn.incomplete && turn.sources?.length" class="assistant-evidence">
                <summary>回答依据 · {{ turn.sources.length }} 条来源</summary>
                <ul class="assistant-source-list"><li v-for="source in turn.sources" :key="source.key">{{ source.label }}：{{ source.title }} {{ source.reference }}</li></ul>
              </details>
              <details v-if="!turn.incomplete && turn.trace?.stages?.length" class="assistant-evidence">
                <summary>流程追溯 · {{ turn.trace.stages.length }} 个环节</summary>
                <div class="assistant-stage-list">
                  <div v-for="stage in turn.trace.stages" :key="stage.stage" class="assistant-stage">
                    <div class="assistant-stage-heading">
                      <span>{{ stage.stage }}</span>
                      <Tag :color="stageColor(stage.status)">{{ stageLabel(stage.status) }}</Tag>
                    </div>
                    <div v-if="stage.records.length" class="assistant-stage-detail">
                      {{ stage.records.map(recordTitle).join('、') }}
                    </div>
                    <div v-else class="assistant-stage-detail">
                      {{ stage.summary || '未找到关联记录' }}
                    </div>
                  </div>
                </div>
              </details>

              <details v-if="!turn.incomplete && turn.result.context.source_records.length" class="assistant-evidence">
                <summary>回答依据 · {{ turn.result.context.source_records.length }} 条来源</summary>
                <ul class="assistant-source-list">
                  <li v-for="(record, recordIndex) in turn.result.context.source_records" :key="`${record.dataset}-${record.record_id}-${recordIndex}`">
                    {{ record.label ?? `${record.dataset} #${record.record_id ?? ''}` }}
                  </li>
                </ul>
              </details>
            </div>
          </div>
        </article>

        <div v-if="loading && !turns.at(-1)?.result.answer" class="assistant-loading"><Spin />{{ progressMessage || (generalMode ? '正在思考…' : `正在读取 ${contextTypeLabel} 并生成回答…`) }}</div>
        <div v-if="errorMessage" class="assistant-error" role="alert">{{ errorMessage }}</div>

      </main>

      <div v-if="!loading && visibleSuggestions.length" class="assistant-followups" aria-label="推荐问题">
        <span>{{ turns.length ? '继续了解' : '试着问我' }}</span>
        <div class="assistant-followup-list">
          <Button v-for="item in visibleSuggestions" :key="item" size="small" @click="ask(item)">{{ item }}</Button>
        </div>
      </div>
      <form class="assistant-composer" @submit.prevent="ask()">
        <Input.TextArea
          v-model:value="question"
          :disabled="loading"
          :maxlength="2000"
          :rows="2"
          :placeholder="generalMode ? (generalFeature === 'orders' ? '输入订单编号或业务问题…' : generalFeature === 'knowledge' ? '输入化工资料问题…' : '输入操作问题…') : listFilters ? '继续询问当前列表…' : '继续询问当前单据…'"
          aria-label="向化工助手提问"
          @keydown.enter.exact.prevent="ask()"
        />
        <div class="assistant-composer-footer">
          <span />
          <Button :loading="loading" :disabled="!question.trim()" type="primary" html-type="submit">发送</Button>
        </div>
      </form>
    </section>
  </Drawer>
</template>

<style scoped>
.assistant-empty { display: grid; justify-items: center; align-content: center; gap: 9px; margin: auto 0; padding: 28px 0; text-align: center; color: hsl(var(--muted-foreground)); line-height: 1.6; }
.assistant-empty-emblem { display: grid; width: 94px; height: 94px; place-items: center; margin-bottom: 5px; border: 1px solid hsl(var(--primary) / .11); border-radius: 50%; background: hsl(var(--primary) / .035); }
.assistant-empty-mark { display: grid; width: 58px; height: 58px; place-items: center; border-radius: 18px; background: linear-gradient(145deg, #4568f5, #2948bc); color: white; box-shadow: 0 7px 18px rgb(41 72 188 / 18%); }
.assistant-empty-mark svg { width: 37px; height: 37px; }
.assistant-empty-title { color: hsl(var(--foreground)); font-size: 16px; font-weight: 600; }
.assistant-empty-caption { margin: 0; font-size: 12px; }
.assistant-shell { position: relative; display: flex; height: 100%; min-height: 0; flex-direction: column; background: hsl(var(--background)); color: hsl(var(--foreground)); }
.assistant-resize-handle { position: absolute; z-index: 10; top: 0; bottom: 0; left: -5px; display: grid; width: 16px; place-items: center; cursor: col-resize; touch-action: none; }
.assistant-resize-handle span { width: 3px; height: 44px; border-radius: 99px; background: hsl(var(--border)); transition: background 150ms, height 150ms; }
.assistant-resize-handle:hover span, .assistant-resize-handle:focus-visible span { height: 68px; background: hsl(var(--primary)); }
.assistant-resize-handle:focus-visible { outline: 2px solid hsl(var(--primary)); outline-offset: -2px; }
.assistant-header { display: flex; min-height: 66px; align-items: center; gap: 11px; padding: 10px 18px 10px 22px; border-bottom: 1px solid hsl(var(--border)); }
.assistant-brand-mark, .assistant-answer-mark { display: grid; width: 34px; height: 34px; flex: none; place-items: center; border-radius: 11px; background: linear-gradient(145deg, #4568f5, #2948bc); color: #fff; font-size: 15px; font-weight: 700; box-shadow: 0 4px 10px rgb(41 72 188 / 18%); }
.assistant-brand-mark svg, .assistant-answer-mark svg { width: 72%; height: 72%; }
.assistant-heading { display: grid; min-width: 116px; gap: 2px; }
.assistant-heading h2 { margin: 0; font-size: 15px; font-weight: 650; line-height: 1.35; }
.assistant-heading > span { color: hsl(var(--muted-foreground)); font-size: 11px; }
.assistant-context-chip { overflow: hidden; max-width: min(270px, 34%); margin-left: auto; text-overflow: ellipsis; white-space: nowrap; }
.assistant-scope-select :deep(.ant-select-selector) { border-color: hsl(var(--primary) / .3) !important; background: hsl(var(--primary) / .06) !important; color: hsl(var(--primary)); border-radius: 6px !important; }
.assistant-scope-select :deep(.ant-select-arrow) { color: hsl(var(--primary)); }
.assistant-close { width: 28px; min-width: 28px; padding-inline: 0; color: hsl(var(--muted-foreground)); font-size: 18px; }
.assistant-scope-note { display: flex; min-height: 36px; align-items: center; gap: 8px; padding: 0 22px; background: hsl(var(--primary) / .045); color: hsl(var(--muted-foreground)); font-size: 12px; }
.assistant-scope-dot { width: 7px; height: 7px; flex: none; border-radius: 50%; background: #31a779; box-shadow: 0 0 0 3px rgb(49 167 121 / 12%); }
.assistant-thread { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 21px; overflow-y: auto; padding: 23px 22px 18px; scroll-behavior: smooth; }
.assistant-turn { display: grid; gap: 16px; }
.assistant-question-row { display: flex; justify-content: flex-end; }
.assistant-question { max-width: 86%; padding: 10px 14px; border: 1px solid hsl(var(--primary) / .08); border-radius: 16px 16px 4px 16px; background: hsl(var(--primary) / .085); color: hsl(var(--foreground)); font-size: 13px; line-height: 1.65; }
.assistant-answer-row { display: flex; align-items: flex-start; gap: 10px; }
.assistant-answer-mark { width: 27px; height: 27px; border-radius: 9px; font-size: 12px; }
.assistant-answer-content { min-width: 0; flex: 1; }
.assistant-answer-text { color: hsl(var(--foreground)); font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.assistant-answer-text :deep(p) { margin: 0 0 7px; }
.assistant-answer-text :deep(p:last-child) { margin-bottom: 0; }
.assistant-answer-text :deep(ul), .assistant-answer-text :deep(ol) { margin: 5px 0; padding-left: 20px; }
.assistant-evidence { margin-top: 12px; border-top: 1px solid hsl(var(--border)); padding-top: 10px; color: hsl(var(--muted-foreground)); font-size: 12px; }
.assistant-evidence summary { width: fit-content; cursor: pointer; color: hsl(var(--primary)); font-weight: 550; }
.assistant-stage-list { margin-top: 9px; border: 1px solid hsl(var(--border)); border-radius: 9px; }
.assistant-stage { padding: 8px 11px; border-bottom: 1px solid hsl(var(--border)); }
.assistant-stage:last-child { border-bottom: 0; }
.assistant-stage-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: hsl(var(--foreground)); font-weight: 550; }
.assistant-stage-detail { margin-top: 3px; line-height: 1.55; overflow-wrap: anywhere; }
.assistant-source-list { display: grid; gap: 5px; margin: 8px 0 0; padding-left: 18px; line-height: 1.55; }
.assistant-answer-meta { margin-top: 10px; color: hsl(var(--muted-foreground)); font-size: 10px; }
.assistant-loading { display: flex; align-items: center; gap: 9px; color: hsl(var(--muted-foreground)); font-size: 12px; }
.assistant-error { padding: 10px 12px; border: 1px solid hsl(var(--destructive) / .2); border-radius: 9px; background: hsl(var(--destructive) / .06); color: hsl(var(--destructive)); font-size: 12px; }
.assistant-followups { display: grid; gap: 8px; max-height: 140px; overflow-y: auto; padding: 10px 18px 4px; color: hsl(var(--muted-foreground)); font-size: 12px; }
.assistant-followup-list { display: flex; flex-wrap: wrap; gap: 7px; }
.assistant-followup-list :deep(.ant-btn) { height: auto; min-height: 28px; white-space: normal; text-align: left; }
.assistant-composer { display: grid; gap: 8px; padding: 12px 18px 14px 22px; border-top: 1px solid hsl(var(--border)); background: hsl(var(--background)); }
.assistant-composer :deep(textarea) { min-height: 58px; border-color: hsl(var(--border)); border-radius: 10px; resize: vertical; font-size: 13px; line-height: 1.55; }
.assistant-composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: hsl(var(--muted-foreground)); font-size: 10px; }
.assistant-composer-footer :deep(.ant-btn) { min-width: 72px; }
:global(.dark) .assistant-shell { background: hsl(var(--background)); }
:global(.dark) .assistant-question { background: hsl(var(--primary) / .17); }
@media (max-width: 640px) {
  .assistant-resize-handle { display: none; }
  .assistant-header { gap: 8px; padding-left: 14px; }
  .assistant-heading { min-width: 0; }
  .assistant-heading > span { display: none; }
  .assistant-context-chip { max-width: 27%; font-size: 10px; }
  .assistant-scope-note { padding-inline: 14px; }
  .assistant-thread { padding: 17px 14px; }
  .assistant-composer { padding-inline: 14px; }
}

/* 使用项目既有颜色和控件，将正文、证据和追问的层级拉开。 */
.assistant-header { min-height: 60px; padding: 10px 16px 10px 24px; flex-wrap: nowrap; }
.assistant-heading { flex: 1; }
.assistant-brand-mark { width: 32px; height: 32px; border-radius: 9px; box-shadow: none; }
.assistant-heading { min-width: 90px; }
.assistant-heading h2 { font-size: 14px; }
.assistant-context-chip { max-width: 26%; }
.assistant-function { display: inline-flex; max-width: 185px; align-items: center; gap: 8px; flex: none; }
.assistant-function span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assistant-function-icon { width: 14px; height: 14px; flex: none; align-self: center; }
.assistant-scope-note { padding: 8px 22px; line-height: 1.5; }
.assistant-thread { gap: 22px; padding: 20px 20px 24px; }
.assistant-turn { gap: 12px; }
.assistant-question { max-width: 86%; padding: 9px 13px; border-radius: 12px 12px 3px 12px; }
.assistant-answer-row { gap: 9px; }
.assistant-answer-mark { width: 26px; height: 26px; border-radius: 8px; box-shadow: none; }
.assistant-answer-content { flex: 1; padding: 1px 0; }
.assistant-answer-text { font-size: 13px; line-height: 1.75; }
.assistant-evidence { margin-top: 8px; padding: 8px 11px; border: 1px solid hsl(var(--border)); border-radius: 8px; background: hsl(var(--muted) / .25); }
.assistant-evidence summary { font-weight: 500; }
.assistant-stage-list { background: hsl(var(--background)); }

.assistant-followup-list { gap: 6px; }
.assistant-composer { padding: 10px 18px 14px; border-top: 0; }
@media (max-width: 640px) {
  .assistant-header { flex-wrap: nowrap; gap: 7px; }
  .assistant-heading { flex: 1; }
  .assistant-context-chip { max-width: 40%; }
}
</style>
