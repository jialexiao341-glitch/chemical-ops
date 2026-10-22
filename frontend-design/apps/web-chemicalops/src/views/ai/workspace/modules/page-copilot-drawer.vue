<script lang="ts" setup>
/** 全局化工助手的业务上下文面板；复用 Vben 抽屉和工作台对话组件风格。 */
import type { AiApi } from '#/api';

import { computed, nextTick, onBeforeUnmount, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { Button, Input, Spin, Tag } from 'antdv-next';

import { askPageContextApi } from '#/api';
import { renderMarkdown } from '#/utils/markdown';

const emit = defineEmits<{ 'open-change': [isOpen: boolean] }>();

interface Turn {
  question: string;
  result: AiApi.ContextAskResult;
  trace?: AiApi.OrderTrace;
}

const turns = ref<Turn[]>([]);
const question = ref('');
const loading = ref(false);
const errorMessage = ref('');
const targetType = ref<AiApi.ContextObjectType>('purchase_order');
const targetId = ref(0);
const listRef = ref<HTMLElement>();
const panelWidth = ref(560);
const expanded = ref(false);
const resizeHandle = ref<HTMLElement>();
let resizeStart: { x: number; width: number } | undefined;

const contextTypeLabel = computed(() => targetType.value === 'purchase_order' ? '采购订单' : '采购申请');
const contextTitle = computed(() => turns.value.at(-1)?.result.context.title ?? contextTypeLabel.value);
const maxPanelWidth = computed(() => Math.min(920, window.innerWidth - 8));
const widthStyle = computed(() => ({
  width: window.innerWidth <= 640 ? '100vw' : `${Math.min(panelWidth.value, window.innerWidth - 8)}px`,
  maxWidth: window.innerWidth <= 640 ? '100vw' : 'calc(100vw - 8px)',
}));

function clampWidth(value: number) {
  panelWidth.value = Math.max(420, Math.min(value, Math.min(920, window.innerWidth - 8)));
}

function toggleExpanded() {
  expanded.value = !expanded.value;
  clampWidth(expanded.value ? 920 : 560);
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
}>({
  footer: false,
  async onOpenChange(isOpen) {
    emit('open-change', isOpen);
    if (!isOpen) return;
    const target = drawerApi.getData();
    turns.value = [];
    errorMessage.value = '';
    expanded.value = false;
    clampWidth(560);
    if (!target) return;
    targetType.value = target.objectType;
    targetId.value = target.objectId;
    question.value = target.question ?? (target.objectType === 'purchase_order' ? '这单当前进展和卡点是什么？' : '这份申请当前是什么状态？');
    await ask();
  },
});

/** 按当前账号从服务端重新取数，不提交页面快照或写入业务数据。 */
async function ask(next?: string) {
  const text = (next ?? question.value).trim();
  if (!text || loading.value) return;
  loading.value = true;
  errorMessage.value = '';
  question.value = '';
  try {
    const result = await askPageContextApi(text, targetType.value, targetId.value);
    const traceCitation = result.citations.find((citation) => citation.type === 'order_trace' || citation.type === 'purchase-request-trace');
    turns.value.push({
      question: text,
      result,
      trace: traceCitation?.order_trace ?? traceCitation,
    });
    if (turns.value.length > 8) turns.value.splice(0, turns.value.length - 8);
    await scrollToLatest();
  } catch (error: any) {
    question.value = text;
    errorMessage.value = error?.message || '暂时无法读取该对象，请检查权限或稍后重试';
    await scrollToLatest();
  } finally {
    loading.value = false;
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

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onResizeMove);
  window.removeEventListener('pointerup', onResizeEnd);
  window.removeEventListener('pointercancel', onResizeEnd);
});

defineExpose({ open });
</script>

<template>
  <Drawer
    :style="widthStyle"
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
        <div class="assistant-brand-mark" aria-hidden="true">化</div>
        <div class="assistant-heading">
          <h2>化工助手</h2>
          <span>只读查询 · 基于当前账号权限</span>
        </div>
        <Tag class="assistant-context-chip" color="blue">{{ contextTitle }}</Tag>
        <Button
          class="assistant-expand"
          size="small"
          :aria-label="expanded ? '还原面板宽度' : '展开面板'"
          :title="expanded ? '还原宽度' : '展开面板'"
          @click="toggleExpanded"
        >
          {{ expanded ? '还原' : '展开' }}
        </Button>
        <Button class="assistant-close" size="small" aria-label="关闭化工助手" @click="drawerApi.close()">×</Button>
      </header>

      <div class="assistant-scope-note">
        <span class="assistant-scope-dot" />
        仅回答可见业务数据，不会修改、提交或审批单据。
      </div>

      <main ref="listRef" class="assistant-thread" aria-live="polite">
        <article v-for="(turn, index) in turns" :key="`${index}-${turn.question}`" class="assistant-turn">
          <div class="assistant-question-row">
            <div class="assistant-question">{{ turn.question }}</div>
          </div>
          <div class="assistant-answer-row">
            <div class="assistant-answer-mark" aria-hidden="true">化</div>
            <div class="assistant-answer-content">
              <div class="assistant-answer-text" v-html="renderMarkdown(turn.result.answer)" />

              <details v-if="turn.trace?.stages?.length" class="assistant-evidence">
                <summary>查看流程追溯（{{ turn.trace.stages.length }} 个环节）</summary>
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

              <details v-if="turn.result.context.source_records.length" class="assistant-evidence">
                <summary>回答依据（{{ turn.result.context.source_records.length }} 条来源）</summary>
                <ul class="assistant-source-list">
                  <li v-for="(record, recordIndex) in turn.result.context.source_records" :key="`${record.dataset}-${record.record_id}-${recordIndex}`">
                    {{ record.label ?? `${record.dataset} #${record.record_id ?? ''}` }}
                  </li>
                </ul>
              </details>
              <div class="assistant-answer-meta">
                {{ turn.result.model === 'order-trace' ? '订单跨模块追溯 · 确定性查询' : turn.result.model === 'purchase-request-trace' ? '申请采购流程追溯 · 确定性查询' : '业务信息查询 · 确定性查询' }}
              </div>
            </div>
          </div>
        </article>

        <div v-if="loading" class="assistant-loading"><Spin />正在按当前权限读取 {{ contextTypeLabel }}…</div>
        <div v-if="errorMessage" class="assistant-error" role="alert">{{ errorMessage }}</div>

        <div v-if="turns.length && turns.at(-1)?.result.context.suggested_questions.length" class="assistant-followups">
          <span>继续了解</span>
          <div class="assistant-followup-list">
            <Button
              v-for="item in turns.at(-1)?.result.context.suggested_questions ?? []"
              :key="item"
              :disabled="loading"
              size="small"
              @click="ask(item)"
            >
              {{ item }}
            </Button>
          </div>
        </div>
      </main>

      <form class="assistant-composer" @submit.prevent="ask()">
        <Input.TextArea
          v-model:value="question"
          :disabled="loading"
          :maxlength="2000"
          :rows="2"
          placeholder="继续询问当前单据…"
          aria-label="向化工助手提问"
          @keydown.enter.exact.prevent="ask()"
        />
        <div class="assistant-composer-footer">
          <span>Enter 发送 · Shift+Enter 换行</span>
          <Button :loading="loading" :disabled="!question.trim()" type="primary" html-type="submit">发送</Button>
        </div>
      </form>
    </section>
  </Drawer>
</template>

<style scoped>
.assistant-shell { position: relative; display: flex; height: 100%; min-height: 0; flex-direction: column; background: hsl(var(--background)); color: hsl(var(--foreground)); }
.assistant-resize-handle { position: absolute; z-index: 3; top: 0; bottom: 0; left: 0; display: grid; width: 10px; place-items: center; cursor: col-resize; touch-action: none; }
.assistant-resize-handle span { width: 3px; height: 44px; border-radius: 99px; background: hsl(var(--border)); transition: background 150ms, height 150ms; }
.assistant-resize-handle:hover span, .assistant-resize-handle:focus-visible span { height: 68px; background: hsl(var(--primary)); }
.assistant-resize-handle:focus-visible { outline: 2px solid hsl(var(--primary)); outline-offset: -2px; }
.assistant-header { display: flex; min-height: 66px; align-items: center; gap: 11px; padding: 10px 18px 10px 22px; border-bottom: 1px solid hsl(var(--border)); }
.assistant-brand-mark, .assistant-answer-mark { display: grid; width: 34px; height: 34px; flex: none; place-items: center; border-radius: 11px; background: linear-gradient(145deg, #4568f5, #2948bc); color: #fff; font-size: 15px; font-weight: 700; box-shadow: 0 4px 10px rgb(41 72 188 / 18%); }
.assistant-heading { display: grid; min-width: 116px; gap: 2px; }
.assistant-heading h2 { margin: 0; font-size: 15px; font-weight: 650; line-height: 1.35; }
.assistant-heading > span { color: hsl(var(--muted-foreground)); font-size: 11px; }
.assistant-context-chip { overflow: hidden; max-width: min(270px, 34%); margin-left: auto; text-overflow: ellipsis; white-space: nowrap; }
.assistant-expand { flex: none; }
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
.assistant-followups { display: grid; gap: 9px; padding-top: 13px; border-top: 1px solid hsl(var(--border)); color: hsl(var(--muted-foreground)); font-size: 11px; }
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
  .assistant-expand { display: none; }
  .assistant-scope-note { padding-inline: 14px; }
  .assistant-thread { padding: 17px 14px; }
  .assistant-composer { padding-inline: 14px; }
}
</style>
