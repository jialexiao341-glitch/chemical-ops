<script lang="ts" setup>
import type { AiApi } from '#/api';

import { nextTick, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Button, Empty, Input, message, Modal, Spin, Tag } from 'antdv-next';

import {
  deleteConversationApi,
  getAIMessagesApi,
  getConversationListApi,
  streamChatApi,
} from '#/api';
import { formatDateTime } from '#/utils/format';
import { renderMarkdown } from '#/utils/markdown';

defineOptions({ name: 'AiWorkspace' });

/** 聊天界面的一条消息 */
interface UiMessage {
  content: string;
  id: string;
  /** 后端 Text2SQL 查询链路，仅助手消息可能携带 */
  queryTrace?: any;
  /** 查询链路详情是否展开（默认收起，点击查看） */
  traceOpen?: boolean;
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
        <div
          class="border-b px-4 py-3 text-sm font-medium"
        >
          AI 助手
          <span class="text-muted-foreground ml-2 text-xs font-normal">
            支持自然语言查询与分析，仅查询不执行业务操作
          </span>
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
