<script lang="ts" setup>
import type { AiApi } from '#/api';

import { computed, nextTick, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import { Button, Empty, Input, message, Modal, Select, Spin, Tag } from 'antdv-next';

import {
  deleteConversationApi,
  generateBriefingApi,
  getAIMessagesApi,
  getConversationListApi,
  parseNaturalFiltersApi,
  streamChatApi,
} from '#/api';
import { AI_FILTER_TARGETS } from '#/utils/ai-list-filters';
import { formatDateTime } from '#/utils/format';
import { renderMarkdown } from '#/utils/markdown';

defineOptions({ name: 'AiWorkspace' });
const router = useRouter();

/** 聊天界面的一条消息 */
interface UiMessage {
  content: string;
  citations?: any[];
  id: string;
  /** 后端 Text2SQL 查询链路，仅助手消息可能携带 */
  queryTrace?: any;
  /** 查询链路详情是否展开（默认收起，点击查看） */
  traceOpen?: boolean;
  openCitationIds?: number[];
  role: 'assistant' | 'user';
  /** 流式回复是否仍在输出 */
  streaming?: boolean;
}

const conversations = ref<AiApi.Conversation[]>([]);
const conversationsLoading = ref(false);
const activeConversationId = ref<number>();

const messages = ref<UiMessage[]>([]);
const inputText = ref('');
const sending = ref(false);
const historyLoading = ref(false);
const messagesRef = ref<HTMLElement>();
const filterPanelOpen = ref(false);
const filterDataset = ref('purchase_requests');
const filterQuestion = ref('');
const filterResult = ref<AiApi.NLFilterResult>();
const filterDraft = ref<Record<string, string>>({});
const filterKeyword = ref('');
const filterRange = ref<AiApi.NLFilterResult['time_range']>();
const filterParsing = ref(false);
const filterFieldNames = computed(() => Object.keys(filterDraft.value));
const canApplyFilters = computed(() => {
  const target = AI_FILTER_TARGETS.find(
    (item) => item.dataset === filterResult.value?.dataset,
  );
  if (!target) return false;
  return (
    Object.entries(filterDraft.value).some(
      ([key, value]) => Boolean(target.fields[key] && value.trim()),
    ) || Boolean(target.keyword && filterKeyword.value.trim())
  );
});
const filterDatasetOptions = AI_FILTER_TARGETS.map(({ dataset, label }) => ({
  label,
  value: dataset,
}));

let messageSeed = 0;
function nextId() {
  messageSeed += 1;
  return `msg-${messageSeed}`;
}

async function loadConversations() {
  conversationsLoading.value = true;
  try {
    const res = await getConversationListApi();
    conversations.value = res.items;
  } finally {
    conversationsLoading.value = false;
  }
}

function scrollToBottom() {
  nextTick(() => {
    const el = messagesRef.value;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  });
}

/** 打开会话历史 */
async function openConversation(conversation: AiApi.Conversation) {
  if (sending.value) {
    message.warning('正在回复中，请稍候');
    return;
  }
  activeConversationId.value = conversation.id;
  historyLoading.value = true;
  try {
    const res = await getAIMessagesApi(conversation.id);
    messages.value = res.items.map((item) => ({
      content: item.content,
      citations: Array.isArray(item.citations) ? item.citations : [],
      id: String(item.id),
      queryTrace: (item.citations as any)?.[0]?.query_trace,
      role: item.role === 'user' ? 'user' : 'assistant',
    }));
    scrollToBottom();
  } finally {
    historyLoading.value = false;
  }
}

/** 开新会话 */
function newConversation() {
  if (sending.value) {
    return;
  }
  activeConversationId.value = undefined;
  messages.value = [];
  inputText.value = '';
}

async function removeConversation(conversation: AiApi.Conversation) {
  Modal.confirm({
    content: `删除会话「${conversation.title ?? `会话 #${conversation.id}`}」后历史消息不可恢复。`,
    okButtonProps: { danger: true },
    okText: '删除',
    onOk: async () => {
      await deleteConversationApi(conversation.id);
      message.success('会话已删除');
      if (activeConversationId.value === conversation.id) {
        newConversation();
      }
      await loadConversations();
    },
    title: '删除会话',
  });
}

/** 发送消息并消费 SSE 流 */
async function onSend() {
  const text = inputText.value.trim();
  if (!text || sending.value) {
    return;
  }
  inputText.value = '';
  const history = [...messages.value];
  messages.value = [
    ...history,
    { content: text, id: nextId(), role: 'user' },
    { content: '', id: nextId(), role: 'assistant', streaming: true },
  ];
  sending.value = true;
  scrollToBottom();

  // 后端要求 OpenAI 兼容格式：只传 user/assistant 文本历史
  const payload = history
    .filter((item) => !item.streaming)
    .map((item) => ({
      content: item.content,
      role: item.role as 'assistant' | 'user',
    }))
    .concat({ content: text, role: 'user' as const });

  const updateLast = (patch: Partial<UiMessage>) => {
    const list = messages.value;
    const last = list.at(-1);
    if (!last) {
      return;
    }
    // 显式回填 content，避免 noUncheckedIndexedAccess 下 spread 空值导致类型丢失
    messages.value = [
      ...list.slice(0, -1),
      { ...last, ...patch, content: patch.content ?? last.content },
    ];
    scrollToBottom();
  };

  try {
    await streamChatApi(payload, activeConversationId.value ?? null, {
      onDelta(content) {
        const list = messages.value;
        updateLast({
          content: (list[list.length - 1]?.content ?? '') + content,
        });
      },
      onDone(payloadDone) {
        updateLast({
          content: payloadDone.answer ?? '',
          citations: Array.isArray(payloadDone.citations) ? payloadDone.citations : [],
          queryTrace: payloadDone.query_trace,
          streaming: false,
        });
        activeConversationId.value = payloadDone.conversation_id;
        void loadConversations();
      },
      onError(errMessage) {
        updateLast({
          content: `⚠ ${errMessage}`,
          streaming: false,
        });
      },
    });
  } finally {
    sending.value = false;
    scrollToBottom();
  }
}

/** 展开/收起某条消息的查询链路详情 */
function toggleTrace(id: string) {
  messages.value = messages.value.map((item) =>
    item.id === id ? { ...item, traceOpen: !item.traceOpen } : item,
  );
}

function toggleCitation(messageId: string, sectionId: number) {
  messages.value = messages.value.map((item) => {
    if (item.id !== messageId) return item;
    const open = item.openCitationIds ?? [];
    return {
      ...item,
      openCitationIds: open.includes(sectionId)
        ? open.filter((id) => id !== sectionId)
        : [...open, sectionId],
    };
  });
}

function safeCitationUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:'
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

function openDataset(dataset: string) {
  const paths: Record<string, string> = {
    accepted_orders_finance_gaps: '/finance/reconciliations',
    approved_requests_without_rfq: '/procurement/requests',
    deliveries: '/warehouse/deliveries',
    exceptions: '/operations/exceptions',
    finance_reconciliations: '/finance/reconciliations',
    inventory: '/warehouse/inventory',
    inventory_by_batch: '/warehouse/inventory',
    inventory_movement_trace: '/warehouse/inventory',
    purchase_orders: '/procurement/orders',
    purchase_requests: '/procurement/requests',
    quality_acceptances: '/quality/acceptances',
    suppliers: '/master/suppliers',
    supplier_quote_delivery_profile: '/master/suppliers',
    weekly_order_risks: '/procurement/orders',
  };
  const path = paths[dataset];
  if (path) void router.push(path);
}

async function generateBriefing(push: boolean) {
  try {
    const result = await generateBriefingApi(push);
    if (result.pushed) {
      message.success(`晨报已推送给 ${result.notified_count} 位接收人`);
    }
    Modal.info({
      content: result.content,
      title: `运营晨报 · ${formatDateTime(result.generated_at)}`,
      width: 560,
    });
  } catch (error: any) {
    message.error(error?.message || '晨报生成失败');
  }
}

function confirmBriefingPush() {
  Modal.confirm({
    content: '晨报将发送给系统管理员和采购经理，是否继续？',
    okText: '确认推送',
    onOk: () => generateBriefing(true),
    title: '确认晨报接收对象',
  });
}

async function parseListFilters() {
  if (!filterQuestion.value.trim() || filterParsing.value) return;
  filterParsing.value = true;
  filterResult.value = undefined;
  try {
    const result = await parseNaturalFiltersApi(
      filterDataset.value,
      filterQuestion.value.trim(),
    );
    filterResult.value = result;
    filterDraft.value = { ...result.filters };
    filterKeyword.value = result.keywords || '';
    filterRange.value = result.time_range ? { ...result.time_range } : null;
  } catch (error: any) {
    message.error(error?.message || '筛选条件解析失败');
  } finally {
    filterParsing.value = false;
  }
}

function removeFilterField(name: string) {
  const next = { ...filterDraft.value };
  delete next[name];
  filterDraft.value = next;
}

function applyListFilters() {
  const target = AI_FILTER_TARGETS.find(
    (item) => item.dataset === filterResult.value?.dataset,
  );
  if (!target || !filterResult.value) return;

  const filters: Record<string, string> = {};
  const unsupported: string[] = [];
  for (const [name, value] of Object.entries(filterDraft.value)) {
    if (!value.trim()) continue;
    if (target.fields[name]) filters[name] = value.trim();
    else unsupported.push(name);
  }
  if (filterRange.value) unsupported.push('时间范围');
  const keywords = target.keyword ? filterKeyword.value.trim() : '';
  if (filterKeyword.value.trim() && !target.keyword) unsupported.push('关键字');
  if (unsupported.length) {
    message.warning(`目标列表暂不支持：${unsupported.join('、')}；这些条件不会应用`);
  }
  void router.push({
    path: target.path,
    query: {
      ai_filters: JSON.stringify({
        dataset: target.dataset,
        filters,
        keywords: keywords || null,
      }),
    },
  });
}

function onTextKeydown(event: KeyboardEvent) {
  // Enter 发送，Shift+Enter 换行
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    onSend();
  }
}

onMounted(loadConversations);
</script>

<template>
  <Page auto-content-height>
    <div class="flex h-full gap-4">
      <!-- 左侧会话列表 -->
      <div
        class="flex w-64 shrink-0 flex-col rounded-lg border bg-card p-3"
      >
        <Button block class="mb-3" type="primary" @click="newConversation">
          + 新会话
        </Button>
        <Spin :spinning="conversationsLoading" class="min-h-0 flex-1 overflow-y-auto">
          <Empty
            v-if="conversations.length === 0"
            description="还没有会话"
            image-style="height: 60px"
          />
          <div v-else class="space-y-1">
            <div
              v-for="item in conversations"
              :key="item.id"
              class="cursor-pointer rounded-md px-2 py-2 hover:bg-accent"
              :class="{
                'bg-accent': item.id === activeConversationId,
              }"
              @click="openConversation(item)"
            >
              <div class="flex items-center justify-between gap-1">
                <span class="truncate text-sm">
                  {{ item.title || `会话 #${item.id}` }}
                </span>
                <Button
                  danger
                  size="small"
                  type="text"
                  @click.stop="removeConversation(item)"
                >
                  ×
                </Button>
              </div>
              <div
                class="text-muted-foreground mt-1 flex items-center gap-2 text-xs"
              >
                <Tag class="!mr-0">{{ item.business_scene }}</Tag>
                <span>{{ formatDateTime(item.last_message_at) }}</span>
              </div>
            </div>
          </div>
        </Spin>
      </div>

      <!-- 右侧对话区 -->
      <div class="flex min-w-0 flex-1 flex-col rounded-lg border bg-card">
        <div class="border-b px-4 py-3 text-sm font-medium">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div>
              AI 助手
              <span class="text-muted-foreground ml-2 text-xs font-normal">
                支持自然语言查询与分析，仅查询不执行业务操作
              </span>
            </div>
            <div class="flex gap-2">
              <Button @click="filterPanelOpen = !filterPanelOpen">自然语言筛选</Button>
              <Button @click="generateBriefing(false)">生成运营晨报</Button>
              <Button type="primary" @click="confirmBriefingPush">生成并推送</Button>
            </div>
          </div>
          <details class="mt-2 text-xs font-normal">
            <summary class="text-muted-foreground cursor-pointer select-none">
              当前支持范围
            </summary>
            <div class="text-muted-foreground mt-2 space-y-1 leading-5">
              <p>业务查询：采购申请及询价缺口、订单履约风险、产品批次库存、库存变动追溯、已验收订单财务进度、供应商报价与交期，以及采购订单、到货、质量验收、运营异常、对账和供应商。</p>
              <p>其他领用/盘点分析、退货补货和跨模块单据全链路追溯尚未接入。金额按币种分别展示，库存数量按单位分别展示；本地开发数据为模拟样本。</p>
              <p>可尝试：“本周哪些订单逾期或短交”“乙醇各仓库批次可用库存”“这批库存为什么被扣减”。</p>
            </div>
          </details>
          <div v-if="filterPanelOpen" class="mt-3 rounded-md border border-border p-3 text-sm font-normal">
            <div class="grid gap-2 sm:grid-cols-[180px_1fr_auto]">
              <Select v-model:value="filterDataset" :options="filterDatasetOptions" />
              <Input v-model:value="filterQuestion" placeholder="例如：只看本月已批准的采购申请" @press-enter="parseListFilters" />
              <Button :loading="filterParsing" :disabled="!filterQuestion.trim()" type="primary" @click="parseListFilters">解析条件</Button>
            </div>
            <div v-if="filterResult" class="mt-3 space-y-2">
              <div class="text-muted-foreground text-xs">检查并编辑条件；确认后会带入所选业务列表的筛选栏。</div>
              <div v-for="name in filterFieldNames" :key="name" class="flex items-center gap-2">
                <Tag class="!mr-0">{{ name }}</Tag>
                <Input v-model:value="filterDraft[name]" size="small" />
                <Button size="small" type="text" danger @click="removeFilterField(name)">移除</Button>
              </div>
              <div v-if="filterKeyword" class="flex items-center gap-2">
                <Tag class="!mr-0">关键字</Tag>
                <Input v-model:value="filterKeyword" size="small" />
              </div>
              <div v-if="filterRange" class="flex flex-wrap items-center gap-2">
                <Tag color="orange" class="!mr-0">列表暂不支持时间范围</Tag>
                <span class="text-muted-foreground text-xs">
                  {{ filterRange.date_from || '不限' }} 至 {{ filterRange.date_to || '不限' }}；该条件不会带入列表。可在 AI 对话中直接查询相同时间范围。
                </span>
                <Button size="small" type="text" danger @click="filterRange = null">移除</Button>
              </div>
              <ul v-if="filterResult.dropped.length" class="text-amber-700 list-disc pl-5 text-xs">
                <li v-for="item in filterResult.dropped" :key="item">未识别：{{ item }}</li>
              </ul>
              <div class="flex justify-end">
                <Button :disabled="!canApplyFilters" type="primary" @click="applyListFilters">确认并打开业务列表</Button>
              </div>
            </div>
          </div>
        </div>

        <div
          ref="messagesRef"
          class="min-h-0 flex-1 space-y-4 overflow-y-auto p-4"
        >
          <Spin :spinning="historyLoading">
            <Empty
              v-if="messages.length === 0"
              class="mt-16"
              description="试着问：本周采购订单金额趋势如何？"
            />
            <div
              v-for="item in messages"
              :key="item.id"
              class="flex"
              :class="item.role === 'user' ? 'justify-end' : 'justify-start'"
            >
              <!-- 用户消息按纯文本展示；助手消息渲染 Markdown -->
              <div
                v-if="item.role === 'user'"
                class="bg-primary max-w-[75%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm text-primary-foreground"
              >
                {{ item.content }}
              </div>
              <div
                v-else
                class="bg-accent max-w-[75%] rounded-lg px-3 py-2 text-sm"
              >
                <div
                  v-if="item.content"
                  class="chat-md [&_a]:text-blue-500 [&_a]:underline [&_code]:bg-black/20 [&_code]:rounded [&_code]:px-1 [&_li]:ml-4 [&_ol]:list-decimal [&_p]:my-1 [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:my-1"
                  v-html="renderMarkdown(item.content)"
                ></div>
                <span v-else-if="item.streaming" class="animate-pulse">
                  正在思考…
                </span>
                <div
                  v-if="item.queryTrace"
                  class="border-border/50 mt-2 border-t pt-2 text-xs opacity-80"
                >
                  <div class="mb-2 rounded-md border border-border/70 bg-background/70 p-2">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span class="font-medium">数据来源：</span>
                        {{ item.queryTrace.dataset_label || item.queryTrace.dataset || '业务数据' }}
                        <span v-if="item.queryTrace.executed_at" class="text-muted-foreground ml-2">
                          查询于 {{ formatDateTime(item.queryTrace.executed_at) }}
                        </span>
                      </div>
                      <Button
                        v-if="item.queryTrace.dataset"
                        size="small"
                        type="link"
                        @click="openDataset(item.queryTrace.dataset)"
                      >打开对应业务列表</Button>
                    </div>
                    <div v-if="item.queryTrace.unit_note" class="text-muted-foreground mt-1">
                      口径：{{ item.queryTrace.unit_note }}
                    </div>
                  </div>
                  <!-- 默认收起：标题行常驻摘要，点击展开槽位与 SQL -->
                  <button
                    class="flex w-full cursor-pointer items-center gap-1 text-left select-none"
                    type="button"
                    @click="toggleTrace(item.id)"
                  >
                    <span
                      class="transition-transform"
                      :class="item.traceOpen ? 'rotate-90' : ''"
                    >▸</span>
                    <span>
                      查询链路 ·
                      {{ item.queryTrace.dataset_label || item.queryTrace.dataset || '-' }} ·
                      命中 {{ item.queryTrace.row_count }} 行
                    </span>
                    <span class="text-muted-foreground">
                      {{ item.traceOpen ? '收起' : '查看' }}
                    </span>
                  </button>
                  <template v-if="item.traceOpen">
                    <!-- 已抽取槽位：label: display_value，empty 状态降透明度区分 -->
                    <div
                      v-if="item.queryTrace.slots?.length"
                      class="mt-2 flex flex-wrap gap-1"
                    >
                      <Tag
                        v-for="slot in item.queryTrace.slots"
                        :key="slot.name"
                        class="!mr-0"
                        :class="slot.status === 'filled' ? '' : 'opacity-50'"
                        :color="slot.status === 'filled' ? 'blue' : undefined"
                      >
                        {{ slot.label }}：{{ slot.display_value }}
                      </Tag>
                    </div>
                    <pre
                      class="mt-2 max-h-32 overflow-auto whitespace-pre-wrap"
                    >{{ item.queryTrace.sql }}</pre>
                  </template>
                </div>
                <details v-if="item.citations?.some((citation) => citation.type === 'doc_kb')" class="mt-3 border-t border-border/50 pt-2">
                  <summary class="text-muted-foreground cursor-pointer select-none text-xs font-medium">
                    资料来源（{{ item.citations.filter((citation) => citation.type === 'doc_kb').length }}）
                  </summary>
                  <div class="mt-2 space-y-2">
                    <article
                      v-for="citation in item.citations.filter((value) => value.type === 'doc_kb')"
                      :key="citation.section_id ?? `${citation.cas_no}-${citation.section_key}`"
                      class="rounded-md border border-border/70 bg-background/70 p-2 text-xs"
                    >
                      <div class="flex flex-wrap items-center gap-2">
                        <span class="font-medium">{{ citation.document_title || citation.title || citation.name_zh || citation.cas_no }}</span>
                        <Tag v-if="citation.source_status === 'missing' || (citation.source_status !== 'unverified' && citation.parse_status && citation.parse_status !== 'PARSED')" color="red" class="!mr-0">来源已不存在或不可用</Tag>
                        <Tag v-else-if="citation.source_status === 'unverified'" color="orange" class="!mr-0">历史来源信息不完整，无法核验</Tag>
                        <Tag v-else color="green" class="!mr-0">来源有效</Tag>
                      </div>
                      <div class="text-muted-foreground mt-1 flex flex-wrap gap-x-3 gap-y-1">
                        <span>CAS {{ citation.cas_no || '—' }}</span>
                        <span>{{ citation.doc_type || '资料' }}{{ citation.section_no ? ` · SECTION ${citation.section_no}` : '' }}</span>
                        <span>{{ citation.section_key || citation.title || '章节' }}</span>
                        <span v-if="citation.document_id">文档 #{{ citation.document_id }}</span>
                        <span v-if="citation.updated_at">更新于 {{ formatDateTime(citation.updated_at) }}</span>
                      </div>
                      <a
                        v-if="safeCitationUrl(citation.source_url)"
                        class="mt-2 inline-flex text-blue-600 hover:underline"
                        :href="safeCitationUrl(citation.source_url)"
                        rel="noopener noreferrer"
                        target="_blank"
                      >打开原始来源</a>
                      <button
                        v-if="citation.content"
                        class="mt-2 cursor-pointer text-blue-600 hover:underline"
                        type="button"
                        @click="toggleCitation(item.id, citation.section_id ?? -1)"
                      >
                        {{ (item.openCitationIds ?? []).includes(citation.section_id ?? -1) ? '收起章节摘录' : '预览章节摘录' }}
                      </button>
                      <p v-if="(item.openCitationIds ?? []).includes(citation.section_id ?? -1)" class="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap border-t border-border/60 pt-2 leading-5">
                        {{ citation.content }}
                      </p>
                    </article>
                  </div>
                </details>
              </div>
            </div>
          </Spin>
        </div>

        <div class="border-t p-3">
          <div class="flex items-end gap-2">
            <Input.TextArea
              v-model:value="inputText"
              :maxlength="2000"
              :rows="2"
              placeholder="输入问题，Enter 发送，Shift+Enter 换行"
              @keydown="onTextKeydown"
            />
            <Button
              :disabled="sending || !inputText.trim()"
              :loading="sending"
              type="primary"
              @click="onSend"
            >
              发送
            </Button>
          </div>
        </div>
      </div>
    </div>
  </Page>
</template>
