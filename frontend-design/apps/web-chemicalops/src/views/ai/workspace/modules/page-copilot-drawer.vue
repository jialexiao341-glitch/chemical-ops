<script lang="ts" setup>
/**
 * 页面 Copilot 抽屉：把当前业务对象交给服务端重新取证后回答。
 *
 * 页面只传对象类型和 ID；每次提问追加一轮问答，便于区分不同问题。
 * 回答来自确定性业务追溯或授权数据，不写回业务单据。
 */
import type { AiApi } from '#/api';

import { nextTick, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { Alert, Button, Input, Spin, Tag } from 'antdv-next';

import { askPageContextApi } from '#/api';
import { renderMarkdown } from '#/utils/markdown';

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

const [Drawer, drawerApi] = useVbenDrawer<{
  objectId: number;
  objectType: AiApi.ContextObjectType;
  question?: string;
}>({
  footer: false,
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    const target = drawerApi.getData();
    turns.value = [];
    errorMessage.value = '';
    if (!target) return;
    targetType.value = target.objectType;
    targetId.value = target.objectId;
    question.value = target.question ?? '当前进展和卡点是什么？';
    await ask();
  },
});

/** 每次提问追加一轮；失败时保留问题文本，便于用户调整后重试。 */
async function ask(next?: string) {
  const text = (next ?? question.value).trim();
  if (!text || loading.value) return;
  loading.value = true;
  errorMessage.value = '';
  question.value = '';
  try {
    const result = await askPageContextApi(text, targetType.value, targetId.value);
    turns.value.push({
      question: text,
      result,
      trace: result.citations.find((citation) => citation.type === 'order_trace')?.order_trace,
    });
    if (turns.value.length > 5) turns.value.splice(0, turns.value.length - 5);
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

function askSuggested(text: string) {
  void ask(text);
}

function stageColor(status: string) {
  if (status === 'AVAILABLE') return 'green';
  if (status === 'NO_PERMISSION') return 'gold';
  return 'blue';
}

function stageLabel(status: string) {
  return ({ AVAILABLE: '可见', NO_PERMISSION: '无权限' } as Record<string, string>)[status] ?? status;
}

/** 追溯记录只展示单据号和状态，不展开业务快照。 */
function recordTitle(record: Record<string, any>) {
  const title = record.number ?? record.batch_id ?? '关联记录';
  return record.status ? `${title}（${record.status}）` : String(title);
}

function open(objectType: AiApi.ContextObjectType, objectId: number, initialQuestion?: string) {
  drawerApi.setData({ objectId, objectType, question: initialQuestion }).open();
}

defineExpose({ open });
</script>

<template>
  <Drawer :title="turns.at(-1)?.result.context.title ?? '问 AI'" class="w-[720px] max-w-[100vw]">
    <div class="space-y-4 pb-6">
      <Alert
        show-icon
        type="info"
        message="回答基于当前账号可见的业务数据；不会修改、提交或审批任何单据。"
        description="权限、数据范围和业务状态均由服务端重新校验，页面只提交对象引用。"
      />

      <div class="space-y-2">
        <Input.TextArea
          v-model:value="question"
          :disabled="loading"
          :maxlength="2000"
          :rows="2"
          placeholder="针对当前对象提问，例如：为什么还没结算？到货情况如何？"
          @keydown.enter.exact.prevent="ask()"
        />
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs text-muted-foreground">
            {{ turns.length ? `本次已提问 ${turns.length} 次，最新一轮在最下方` : '每次提问都会按当前权限重新读取对象' }}
          </span>
          <Button :loading="loading" type="primary" @click="ask()">发送</Button>
        </div>
      </div>

      <div ref="listRef" class="max-h-[calc(100vh-300px)] space-y-4 overflow-y-auto pr-1">
        <div v-for="(turn, index) in turns" :key="`${index}-${turn.question}`" class="space-y-2">
          <div class="flex justify-end">
            <div class="max-w-[85%] rounded-lg bg-muted/40 px-3 py-2 text-sm">{{ turn.question }}</div>
          </div>
          <div class="space-y-3 rounded-lg border p-3">
            <div class="text-sm leading-6" v-html="renderMarkdown(turn.result.answer)"></div>

            <details v-if="turn.trace?.stages?.length" :open="index === turns.length - 1">
              <summary class="cursor-pointer text-sm font-medium">
                逐环节追溯（{{ turn.trace?.stages?.length ?? 0 }}）
              </summary>
              <div class="mt-2 divide-y rounded-lg border">
                <div v-for="stage in turn.trace?.stages ?? []" :key="stage.stage" class="space-y-1 px-3 py-2 text-sm">
                  <div class="flex items-center justify-between gap-2">
                    <span class="font-medium">{{ stage.stage }}</span>
                    <Tag :color="stageColor(stage.status)">{{ stageLabel(stage.status) }}</Tag>
                  </div>
                  <div v-if="stage.records.length" class="break-words text-muted-foreground">
                    {{ stage.records.map(recordTitle).join('、') }}
                  </div>
                  <div v-else-if="stage.summary" class="break-words text-muted-foreground">{{ stage.summary }}</div>
                  <div v-else class="text-muted-foreground">未找到关联记录</div>
                </div>
              </div>
            </details>

            <details v-if="turn.result.context.source_records.length">
              <summary class="cursor-pointer text-sm font-medium">
                本次读取的来源（{{ turn.result.context.source_records.length }}）
              </summary>
              <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                <li v-for="(record, recordIndex) in turn.result.context.source_records" :key="`${record.dataset}-${record.record_id}-${recordIndex}`">
                  {{ record.label ?? `${record.dataset} #${record.record_id ?? ''}` }}
                </li>
              </ul>
            </details>

            <div class="text-xs text-muted-foreground">
              {{ turn.result.model === 'order-trace' ? '订单跨模块追溯（确定性查询，未调用模型生成事实）' : turn.result.model }}
            </div>
          </div>
        </div>

        <div v-if="loading" class="flex items-center gap-2 rounded-lg border p-3 text-sm text-muted-foreground">
          <Spin />
          正在按当前权限重新读取该对象…
        </div>

        <Alert v-if="errorMessage" show-icon type="error" :message="errorMessage" />
      </div>

      <div v-if="turns.length" class="space-y-2 border-t pt-3">
        <h3 class="font-medium">可以继续问</h3>
        <div class="flex flex-wrap gap-2">
          <Button
            v-for="item in turns.at(-1)?.result.context.suggested_questions ?? []"
            :key="item"
            :disabled="loading"
            size="small"
            @click="askSuggested(item)"
          >
            {{ item }}
          </Button>
        </div>
      </div>
    </div>
  </Drawer>
</template>
