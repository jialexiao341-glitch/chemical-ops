<script lang="ts" setup>
import type { AgentApi, AiApi } from '#/api';

import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';

import { Button, Input, InputNumber, message, Modal, Select, Spin, Tag } from 'antdv-next';

import {
  cancelAgentTaskApi,
  cancelActionProposalApi,
  confirmActionProposalApi,
  createActionProposalApi,
  deleteConversationApi,
  createAgentChatApi, continueAgentChatApi, continueAgentTaskApi, getAgentTaskApi,
  confirmPurchaseRequestDraftApi,
  generateBriefingApi,
  getProductListApi,
  getUnitListApi,
  getAIMessagesApi,
  getConversationListApi,
  parseNaturalFiltersApi,
  proposePurchaseRequestDraftApi,
  streamChatApi, routeAiRequestApi,
  updateConversationApi,
} from '#/api';
import { AI_FILTER_TARGETS } from '#/utils/ai-list-filters';
import { formatAmount, formatDateTime, formatQuantity } from '#/utils/format';
import { renderMarkdown } from '#/utils/markdown';

import QueryEvidence from './query-evidence.vue';
import AgentChatTask from './agent-chat-task.vue';
import AgentSourcePopover from './agent-source-popover.vue';
import { answerSources } from './answer-sources';
import { createAgentPoller } from './agent-polling';
import { canConfirmActionProposal } from './action-proposal-policy';
import { acceptTask, primaryTaskResults } from './task-view';
import { useConversation } from './use-conversation';
import { useChatStream } from './use-chat-stream';
import assistantLogo from './chemicalops-ai.svg';

defineOptions({ name: 'AiWorkspace' });
const router = useRouter();
const route = useRoute();
const { hasAccessByCodes, hasAccessByRoles } = useAccess();
const canCreatePurchaseDraft = hasAccessByCodes(['procurement.requests.write']);
const canPushBriefing = hasAccessByRoles(['SYS_ADMIN', 'PROCUREMENT_MANAGER']);

const AI_DATASET_READ_PERMISSIONS: Record<string, string | string[]> = {
  accepted_orders_finance_gaps: 'finance.reconciliations.read',
  approved_requests_without_rfq: 'procurement.requests.read',
  deliveries: 'warehouse.deliveries.read',
  exceptions: 'operations.exceptions.read',
  finance_invoices: 'finance.invoices.read',
  finance_payments: 'finance.payments.read',
  finance_reconciliations: 'finance.reconciliations.read',
  finance_settlements: 'finance.settlements.read',
  inventory: 'warehouse.inventory.read',
  inventory_by_batch: 'warehouse.inventory.read',
  inventory_movement_trace: 'warehouse.inventory.read',
  inventory_transactions: 'warehouse.inventory.read',
  overdue_unfulfilled_orders: [
    'procurement.orders.read',
    'warehouse.inventory.read',
    'master.products.read',
  ],
  purchase_orders: 'procurement.orders.read',
  purchase_requests: 'procurement.requests.read',
  quality_acceptances: 'quality.acceptances.read',
  rfqs: 'procurement.rfqs.read',
  supplier_quote_delivery_profile: 'master.suppliers.read',
  supplier_quotes: 'procurement.rfqs.read',
  suppliers: 'master.suppliers.read',
  weekly_order_risks: 'procurement.orders.read',
};

function canReadDataset(dataset?: string) {
  const permission = dataset ? AI_DATASET_READ_PERMISSIONS[dataset] : undefined;
  if (!permission) return false;
  return Array.isArray(permission)
    ? permission.every((code) => hasAccessByCodes([code]))
    : hasAccessByCodes([permission]);
}

/** 聊天界面的一条消息 */
interface UiMessage {
  content: string;
  agentTaskId?: string;
  agentTask?: AgentApi.Task;
  agentError?: string;
  citations?: any[];
  id: string;
  /** 后端 Text2SQL 查询链路，仅助手消息可能携带 */
  queryTrace?: any;
  batchProgress?: AiApi.BatchProgress;
  cancelPending?: boolean;
  draftProposal?: AiApi.PurchaseDraftPreview;
  draftCreatedRequestNo?: string;
  draftInteraction?: boolean;
  sourceRecords?: Array<{
    dataset: string;
    filters?: Record<string, string | number>;
    label: string;
    record_id?: null | number;
  }>;
  role: 'assistant' | 'user';
  /** 流式回复是否仍在输出 */
  streaming?: boolean;
  /** 识别请求失败的本地提示不作为下一轮模型历史。 */
  localOnly?: boolean;
}

const { conversations, conversationsLoading, conversationSearch, visibleConversations, loadConversations } = useConversation<AiApi.Conversation>(() => getConversationListApi(100));
const sidebarExpanded = ref(false);
const sidebarCollapsed = ref(false);
const menuConversationId = ref<number>();
const editingConversationId = ref<number>();
const editingTitle = ref('');
const activeConversationId = ref<number>();

const messages = ref<UiMessage[]>([]);
const inputText = ref('');
const sending = ref(false);
const stopping = ref(false);
const canStop = computed(() => Boolean(streamAbort.value || currentAgent.value?.status === 'RUNNING'));
const slashMenuOpen = ref(false);
const slashMenuActiveIndex = ref(0);
const historyLoading = ref(false);
const messagesRef = ref<HTMLElement>();
const { scrollToBottom, renderMessage } = useChatStream(messagesRef, renderMarkdown);
const filterPanelOpen = ref(false);
const filterDataset = ref('purchase_requests');
const filterQuestion = ref('');
const filterResult = ref<AiApi.NLFilterResult>();
const filterDraft = ref<Record<string, string>>({});
const filterKeyword = ref('');
const filterRange = ref<AiApi.NLFilterResult['time_range']>();
const filterParsing = ref(false);
const draftMode = ref(false);
const draftPrepared = ref(false);
const draftMissingFields = ref<string[]>([]);
const draftFollowups = ref<string[]>([]);
const draftPurpose = ref('');
const draftPriority = ref('NORMAL');
const draftBudget = ref<number>();
const draftCurrency = ref('CNY');
const draftExpectedDate = ref<any>();
const draftItems = ref<Array<{ product_id?: number; requested_name: string; quantity?: number; unit_id?: number; technical_requirements?: string }>>([{ requested_name: '' }]);
const draftProducts = ref<Array<{ id: number; product_code: string; product_name: string; model?: string | null; packaging_spec?: string | null; purity_value?: string | null; purity_unit?: string | null; unit_id: number }>>([]);
const draftUnits = ref<Array<{ id: number; unit_name: string }>>([]);
const draftProductsLoading = ref(false);
const canReadDraftProducts = computed(() => hasAccessByCodes(['master.products.read']) || hasAccessByRoles(['SYS_ADMIN']));
const draftFormReady = computed(() => Boolean(draftPurpose.value.trim()) && draftItems.value.length > 0 && draftItems.value.every((item, index) => item.requested_name.trim() && Number(item.quantity) > 0 && Number(item.unit_id) > 0 && (!needsDraftProductChoice(index) || Number(item.product_id) > 0 || (item.product_id === -1 && item.requested_name.trim()))));
const creatingDraftMessageId = ref<string>();
const actionProposalBusy = ref(false);
const filterFieldNames = computed(() => Object.keys(filterDraft.value));
const conversationGroups = computed(() => {
  const groups = new Map<string, AiApi.Conversation[]>();
  for (const item of [...visibleConversations.value].sort((a, b) => Number(b.pinned) - Number(a.pinned))) {
    const date = formatDateTime(item.last_message_at || item.created_at);
    const label = item.pinned ? '置顶会话' : /^\d{4}-\d{2}/.test(date) ? date.slice(0, 7) : '更早';
    const group = groups.get(label) ?? [];
    group.push(item);
    groups.set(label, group);
  }
  return [...groups].map(([label, items]) => ({ items, label }));
});
const canApplyFilters = computed(() => {
  const target = AI_FILTER_TARGETS.find(
    (item) => item.dataset === filterResult.value?.dataset,
  );
  if (!target || !canReadDataset(target.dataset)) return false;
  return (
    Object.entries(filterDraft.value).some(
      ([key, value]) => Boolean(target.fields[key] && value.trim()),
    ) || Boolean(target.keyword && filterKeyword.value.trim())
  );
});
const filterDatasetOptions = computed(() =>
  AI_FILTER_TARGETS
    .filter((item) => item.dataset !== 'inventory' && canReadDataset(item.dataset))
    .map(({ dataset, label }) => ({ label, value: dataset })),
);
type SlashCommand = 'agent' | 'briefing' | 'briefing-push' | 'filter' | 'purchase-draft';
type SlashCommandOption = {
  description: string;
  icon: 'briefing' | 'draft' | 'filter' | 'send';
  label: string;
  value: SlashCommand;
};

const slashCommands = computed((): SlashCommandOption[] => [
  { description: '在聊天中查库存、核对产品规格和供应商报价', icon: 'filter', label: '采购只读查询', value: 'agent' },
  ...(filterDatasetOptions.value.length ? [{ description: '用自然语言设置条件，并带入业务列表', icon: 'filter' as const, label: '自然语言筛选', value: 'filter' as const }] : []),
  ...(canCreatePurchaseDraft ? [{ description: '整理采购信息，核对后创建草稿', icon: 'draft' as const, label: '采购申请草稿', value: 'purchase-draft' as const }] : []),
  { description: '查看本次生成的运营晨报', icon: 'briefing', label: '生成运营晨报', value: 'briefing' },
  ...(canPushBriefing ? [{ description: '确认接收对象后生成并推送晨报', icon: 'send' as const, label: '生成并推送', value: 'briefing-push' as const }] : []),
]);

function visibleSourceRecords(item: UiMessage) {
  return (item.sourceRecords ?? []).filter((record) => canReadDataset(record.dataset));
}

function sourceGroups(item: UiMessage) {
  const groups = new Map<string, ReturnType<typeof answerSources>>();
  for (const source of answerSources(item.citations, canReadDataset)) {
    const entries = groups.get(source.label) ?? [];
    entries.push(source);
    groups.set(source.label, entries);
  }
  return [...groups].map(([label, entries]) => ({ label, entries }));
}

/** 每个子任务只关联自己的来源，历史回放与即时回复复用同一引用。 */
function queryViews(item: UiMessage): Array<UiMessage & { question?: string }> {
  const batch = item.citations?.find((citation) => citation.type === 'multi_intent')?.batch;
  if (!batch) return item.queryTrace && canReadDataset(item.queryTrace.dataset) ? [item] : [];
  return batch.tasks.flatMap((task: any) => (task.citations ?? [])
    .filter((citation: any) => citation.query_trace && canReadDataset(citation.query_trace.dataset))
    .map((citation: any) => ({ id: `${item.id}:${task.id}`, role: 'assistant', content: '',
      question: task.question, queryTrace: citation.query_trace, sourceRecords: citation.source_records ?? [] })));
}
function batchToolViews(item: UiMessage): Array<{ question: string; task: AgentApi.Task }> {
  const batch = item.citations?.find((citation) => citation.type === 'multi_intent')?.batch;
  return (batch?.tasks ?? []).filter((task: any) => ['inventory', 'quotes'].includes(task.kind) && task.evidence?.length)
    .map((task: any) => ({ question: task.question, task: { id: `${item.id}:${task.id}`, revision: 0,
      status: task.status, reply: task.answer ?? '', error_code: task.error_code, messages: [],
      trace: task.evidence.map((result: AgentApi.Result, index: number) => ({ step: index + 1,
        action: 'call_tool', status: 'SUCCEEDED', tool: result.tool, result })) } }));
}

const agentMode = ref(false);
let chatEpoch = 0;
const agentReads = new Map<string, number>();
const streamAbort = shallowRef<AbortController>();
const currentAgent = computed(() => messages.value.filter((item) => !item.localOnly).at(-1)?.agentTask);
const agentPoller = createAgentPoller({
  hidden: () => document.hidden,
  pending: () => messages.value.some((item) => item.agentTask?.status === 'RUNNING'),
  refresh: async () => { await Promise.all(messages.value.filter((item) => item.agentTask?.status === 'RUNNING').map(refreshAgent)); },
  timeout: () => {
    messages.value = messages.value.map((item) => item.agentTask?.status === 'RUNNING'
      ? { ...item, agentError: '查询仍在后台运行，自动刷新已暂停，请重新打开会话查看或停止任务。' } : item);
  },
});
function stopAgentPolling() { agentPoller.stop(); }
function onVisibilityChange() { if (document.hidden) agentPoller.stop(); else agentPoller.schedule(); }
async function stopCurrentWork() {
  if (stopping.value) return;
  stopping.value = true;
  const epoch = chatEpoch;
  try {
    streamAbort.value?.abort();
    const item = messages.value.findLast((entry) => entry.agentTask?.status === 'RUNNING');
    if (item?.agentTaskId) {
      const task = await cancelAgentTaskApi(item.agentTaskId);
      applyAgent(task, item.id, epoch);
      scheduleAgentPolling();
    }
  } finally { stopping.value = false; }
}
function resetChatWork() { agentPoller.reset(); chatEpoch += 1; streamAbort.value?.abort(); stopAgentPolling(); agentMode.value = false; }
function applyAgent(task: AgentApi.Task, id: string, epoch: number) {
  if (epoch !== chatEpoch) return;
  messages.value = messages.value.map((item) => item.id === id && acceptTask(item.agentTask, task)
    ? { ...item, agentTask: task, agentTaskId: task.id, agentError: undefined, content: '', streaming: false } : item);
}
function scheduleAgentPolling() { agentPoller.schedule(); }
async function refreshAgent(item: UiMessage) {
  if (!item.agentTaskId) return;
  const epoch = chatEpoch;
  const generation = (agentReads.get(item.agentTaskId) ?? 0) + 1;
  agentReads.set(item.agentTaskId, generation);
  try {
    const task = await getAgentTaskApi(item.agentTaskId);
    if (agentReads.get(item.agentTaskId) === generation) applyAgent(task, item.id, epoch);
  }
  catch {
    if (epoch === chatEpoch && agentReads.get(item.agentTaskId) === generation) messages.value = messages.value.map((entry) => entry.role === 'assistant' && entry.agentTaskId === item.agentTaskId
      ? { ...entry, streaming: false, agentError: '任务无法读取，请核对登录、权限或服务状态后重试。' } : entry);
  }
}
async function sendAgent(text: string, continuation?: AgentApi.Continue, routeToken?: string) {
  if (sending.value) return;
  const previous = currentAgent.value;
  if (previous?.status === 'RUNNING') { message.info('正在查询，请等待结果自动更新。'); return; }
  const epoch = ++chatEpoch;
  agentPoller.reset();
  stopAgentPolling();
  const assistantId = nextId();
  messages.value = messages.value.map((item) => item.agentTask
    ? { ...item, content: item.agentTask.reply, agentTask: undefined } : item);
  messages.value.push({ content: text, id: nextId(), role: 'user', agentTaskId: previous?.id },
    { content: '', id: assistantId, role: 'assistant', streaming: true });
  sending.value = true;
  agentMode.value = false;
  scrollToBottom();
  try {
    const task = continuation && previous
      ? await (previous.conversation_id ? continueAgentChatApi : continueAgentTaskApi)(previous.id, { ...continuation, route_token: routeToken })
      : await createAgentChatApi(text, activeConversationId.value, routeToken);
    if (epoch !== chatEpoch) return;
    applyAgent(task, assistantId, epoch);
    activeConversationId.value = task.conversation_id ?? activeConversationId.value;
    messages.value = messages.value.map((item) => item.id === assistantId || item.id === messages.value.at(-2)?.id
      ? { ...item, agentTaskId: task.id } : item);
    if (task.conversation_id) await router.replace({ query: { conversation: String(task.conversation_id) } });
    void loadConversations();
    scheduleAgentPolling();
  } catch {
    if (epoch === chatEpoch) {
      messages.value = messages.value.map((item) => item.id === assistantId
        ? { ...item, streaming: false, content: '未取得任务结果，请重新打开会话核对最新状态后操作。' } : item);
      void loadConversations();
    }
  } finally {
    if (epoch === chatEpoch) { sending.value = false; scrollToBottom(); }
  }
}
async function continueAgent(item: UiMessage, data: AgentApi.Continue) {
  if (item.agentTask?.id !== currentAgent.value?.id) return;
  await sendAgent(data.question, data);
}
let messageSeed = 0;
function nextId() {
  messageSeed += 1;
  return `msg-${messageSeed}`;
}

/** 打开会话历史 */
function historyMessages(items: AiApi.Message[]): UiMessage[] {
  return items.map((item) => ({
    agentTaskId: item.citations?.find((citation: any) => citation.type === 'agent_task')?.task_id,
    content: item.content,
    citations: Array.isArray(item.citations) ? item.citations : [],
    id: String(item.id),
    queryTrace: (item.citations as any)?.[0]?.query_trace,
    sourceRecords: (Array.isArray(item.citations) ? item.citations : []).flatMap((citation: any) => citation.source_records ?? []),
    role: item.role === 'user' ? 'user' : 'assistant',
  }));
}

async function openConversation(conversation: AiApi.Conversation) {
  if (sending.value) {
    message.warning('正在回复中，请稍候');
    return;
  }
  resetChatWork();
  const epoch = chatEpoch;
  activeConversationId.value = conversation.id;
  menuConversationId.value = undefined;
  sidebarExpanded.value = false;
  draftMode.value = false;
  draftFollowups.value = [];
  historyLoading.value = true;
  try {
    const res = await getAIMessagesApi(conversation.id);
    if (epoch !== chatEpoch) return;
    messages.value = historyMessages(res.items);
    // 一项任务只在最新助手回复中展示可交互结果，旧轮保留原追问文字。
    const latest = new Map<string, UiMessage>();
    for (const item of messages.value) if (item.role === 'assistant' && item.agentTaskId) latest.set(item.agentTaskId, item);
    await Promise.all([...latest.values()].map((item) => refreshAgent(item)));
    if (epoch !== chatEpoch) return;
    await router.replace({ query: { conversation: String(conversation.id) } });
    scheduleAgentPolling();
    scrollToBottom();
  } finally {
    if (epoch === chatEpoch) historyLoading.value = false;
  }
}

/** 开新会话 */
function newConversation() {
  if (sending.value) {
    return;
  }
  resetChatWork();
  historyLoading.value = false;
  void router.replace({ path: '/ai/workspace', query: {} });
  activeConversationId.value = undefined;
  menuConversationId.value = undefined;
  sidebarExpanded.value = false;
  draftMode.value = false;
  draftFollowups.value = [];
  slashMenuOpen.value = false;
  messages.value = [];
  inputText.value = '';
}

let menuTrigger: HTMLElement | undefined;
async function toggleConversationMenu(id: number, event: Event) {
  menuTrigger = event.currentTarget as HTMLElement;
  menuConversationId.value = menuConversationId.value === id ? undefined : id;
  await nextTick();
  menuTrigger.parentElement?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
}
function onConversationMenuKeydown(event: KeyboardEvent) {
  const menu = event.currentTarget as HTMLElement;
  const items = [...menu.querySelectorAll<HTMLElement>('[role="menuitem"]')];
  const index = items.indexOf(document.activeElement as HTMLElement);
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault(); event.stopPropagation();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  } else if (event.key === 'Escape' || event.key === 'Tab') {
    menuConversationId.value = undefined;
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); menuTrigger?.focus(); }
  }
}

function beginRename(conversation: AiApi.Conversation) {
  menuConversationId.value = undefined;
  editingConversationId.value = conversation.id;
  editingTitle.value = conversation.title || `会话 #${conversation.id}`;
  void nextTick(() => document.querySelector<HTMLInputElement>('.ai-rename-input')?.focus());
}

async function saveRename(conversation: AiApi.Conversation) {
  if (editingConversationId.value !== conversation.id) return;
  editingConversationId.value = undefined;
  const title = editingTitle.value.trim();
  if (!title || title === conversation.title) return;
  try {
    const updated = await updateConversationApi(conversation.id, { title });
    conversations.value = conversations.value.map((item) => item.id === updated.id ? updated : item);
  } catch {
    message.error('重命名失败，请重试');
  }
}

async function togglePinned(conversation: AiApi.Conversation) {
  menuConversationId.value = undefined;
  try {
    const updated = await updateConversationApi(conversation.id, { pinned: !conversation.pinned });
    conversations.value = conversations.value.map((item) => item.id === updated.id ? updated : item);
  } catch {
    message.error('置顶状态更新失败，请重试');
  }
}

function closeHistoryMenu(event: MouseEvent) {
  if (!(event.target as Element).closest('.ai-history-menu, .ai-history-more')) {
    menuConversationId.value = undefined;
  }
}

function toggleSidebar() {
  if (window.matchMedia('(max-width: 640px)').matches) {
    sidebarExpanded.value = !sidebarExpanded.value;
  } else {
    sidebarCollapsed.value = !sidebarCollapsed.value;
  }
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
async function onSend(retryFailed = false) {
  const text = inputText.value.trim();
  if ((!text && !(draftMode.value && draftFormReady.value)) || sending.value || historyLoading.value || actionProposalBusy.value) {
    return;
  }
  if (currentAgent.value?.status === 'RUNNING') { message.info('正在查询，请等待结果自动更新。'); return; }
  if (draftMode.value) {
    if (!canCreatePurchaseDraft) { draftMode.value = false; message.error('你没有创建采购申请草稿的权限。'); return; }
    if (!draftPrepared.value) {
      if (!text) return;
      await previewPurchaseRequestDraft(text);
      return;
    }
    if (!draftFormReady.value) { message.warning('请补全标记为缺失的采购信息。'); return; }
    await previewPurchaseRequestDraft();
    return;
  }
  let routeToken: string | undefined;
  const epoch = chatEpoch;
  const history = [...messages.value];
  const pendingAssistantId = nextId();
  inputText.value = '';
  messages.value = [
    ...history,
    { content: text, id: nextId(), role: 'user', localOnly: true },
    { content: '', id: pendingAssistantId, role: 'assistant', streaming: true, localOnly: true },
  ];
  sending.value = true;
  scrollToBottom();
  try {
    const decision = retryFailed ? { route: 'batch', route_token: undefined }
      : await routeAiRequestApi(text, activeConversationId.value);
    if (epoch !== chatEpoch) return;
    routeToken = decision.route_token;
    if (decision.route === 'purchase_draft') {
      messages.value = history;
      sending.value = false;
      if (!canCreatePurchaseDraft) {
        inputText.value = text;
        message.error('你没有创建采购申请草稿的权限。');
        return;
      }
      draftFollowups.value = [];
      draftPrepared.value = false;
      draftMissingFields.value = [];
      draftMode.value = true;
      await previewPurchaseRequestDraft(text);
      return;
    }
    if (['purchase_update', 'purchase_submit', 'rfq_draft'].includes(decision.route)) {
      messages.value = history;
      sending.value = false;
      await prepareActionProposal(text, decision.route, 'understanding' in decision ? decision.understanding : { slots: {} });
      return;
    }
    if (decision.route === 'agent') {
      messages.value = history;
      sending.value = false;
      const continuation = currentAgent.value?.status === 'WAITING_INPUT'
        ? { question: text, revision: currentAgent.value.revision }
        : undefined;
      await sendAgent(text, continuation, routeToken);
      return;
    }
  } catch {
    if (epoch === chatEpoch) {
      if (!inputText.value) inputText.value = text;
      messages.value = messages.value.map((item) => item.id === pendingAssistantId
        ? { ...item, content: '这次请求未能完成，尚未开始查询。请稍后重试。', streaming: false } : item);
      scrollToBottom();
    }
    return; // 保留输入，不能退回前端关键词分流。
  } finally {
    if (epoch === chatEpoch) sending.value = false;
  }
  messages.value = [
    ...history,
    { content: text, id: nextId(), role: 'user' },
    { content: '', id: nextId(), role: 'assistant', streaming: true },
  ];
  sending.value = true;
  const abort = new AbortController();
  streamAbort.value = abort;
  const assistantId = messages.value.at(-1)!.id;
  scrollToBottom();

  // 后端要求 OpenAI 兼容格式：只传 user/assistant 文本历史
  const payload = history
    .filter((item) => !item.streaming && !item.draftInteraction && !item.agentTaskId && !item.localOnly)
    .map((item) => ({
      content: item.content,
      role: item.role as 'assistant' | 'user',
    }))
    .concat({ content: text, role: 'user' as const });

  const updateLast = (patch: Partial<UiMessage>) => {
    if (epoch !== chatEpoch || messages.value.at(-1)?.id !== assistantId) return;
    const list = messages.value;
    const last = list.at(-1);
    if (!last) {
      return;
    }
    Object.assign(last, patch, { content: patch.content ?? last.content });
    scrollToBottom();
  };

  let pendingText = '';
  let deltaFrame: number | undefined;
  const flushText = () => {
    if (deltaFrame !== undefined) cancelAnimationFrame(deltaFrame);
    deltaFrame = undefined;
    if (pendingText) {
      updateLast({ content: (messages.value.at(-1)?.content ?? '') + pendingText });
      pendingText = '';
    }
  };
  try {
    await streamChatApi(payload, activeConversationId.value ?? null, {
      onProgress(progress) {
        if (epoch !== chatEpoch || abort.signal.aborted) return;
        // 进度只更新状态；正文走 delta，明细与来源等 done 后展示。
        updateLast({ batchProgress: progress });
        if (activeConversationId.value !== progress.conversation_id) {
          activeConversationId.value = progress.conversation_id;
          void router.replace({ query: { conversation: String(progress.conversation_id) } });
        }
      },
      onCancelled() {
        flushText();
        const hasBatch = Boolean(messages.value.at(-1)?.batchProgress);
        updateLast({ streaming: false, cancelPending: hasBatch, ...(hasBatch ? { content: '已取消后续查询，正在核对已完成项…' } : {}) });
      },
      onDelta(content) {
        if (abort.signal.aborted) return;
        pendingText += content;
        deltaFrame ??= requestAnimationFrame(flushText);
      },
      onDone(payloadDone) {
        flushText();
        if (abort.signal.aborted || epoch !== chatEpoch) return;
        updateLast({
          batchProgress: undefined, cancelPending: false,
          content: payloadDone.answer ?? '',
          citations: Array.isArray(payloadDone.citations) ? payloadDone.citations : [],
          queryTrace: payloadDone.query_trace,
          sourceRecords: (Array.isArray(payloadDone.citations) ? payloadDone.citations : []).flatMap((citation: any) => citation.source_records ?? []),
          streaming: false,
        });
        activeConversationId.value = payloadDone.conversation_id;
        void router.replace({ query: { conversation: String(payloadDone.conversation_id) } });
        void loadConversations();
      },
      onError(errMessage) {
        flushText();
        updateLast({
          content: `⚠ ${errMessage}`,
          cancelPending: Boolean(messages.value.at(-1)?.batchProgress),
          batchProgress: undefined,
          streaming: false,
        });
      },
    }, routeToken, { signal: abort.signal, retryFailed });
  } finally {
    flushText();
    if (streamAbort.value === abort) streamAbort.value = undefined;
    if (epoch !== chatEpoch) return;
    if (abort.signal.aborted && activeConversationId.value && messages.value.at(-1)?.cancelPending) {
      // 断开后服务端先保存取消终态；短暂轮询只读取本人会话，不重新执行查询。
      for (let attempt = 0; attempt < 4; attempt++) {
        try {
          const res = await getAIMessagesApi(activeConversationId.value);
          if (epoch !== chatEpoch) return;
          const latest = res.items.at(-1);
          const lastUser = res.items.filter((item) => item.role === 'user').at(-1);
          const batch = latest?.citations?.find((citation: any) => citation.type === 'multi_intent')?.batch;
          if (lastUser?.content === text && batch && batch.tasks.every((task: any) => !['PENDING', 'PLANNED', 'RUNNING'].includes(task.status))) {
            messages.value = historyMessages(res.items);
            break;
          }
        } catch { /* 保留本地已完成结果，允许稍后刷新会话核对。 */ }
        await new Promise((resolve) => setTimeout(resolve, 150 * 2 ** attempt));
      }
      if (messages.value.at(-1)?.cancelPending) updateLast({ batchProgress: undefined, content: '已取消后续查询；已完成项保留，请刷新会话核对最终状态。' });
    }
    sending.value = false;
    scrollToBottom();
  }
}

async function prepareActionProposal(
  question: string,
  intent: string,
  understanding: { action_fields?: Record<string, unknown> | null; slots: { request_no?: string | null } },
) {
  const requestNo = understanding.slots.request_no;
  const userMessageId = nextId();
  const assistantMessageId = nextId();
  messages.value = [
    ...messages.value,
    { content: question, id: userMessageId, role: 'user' },
    { content: '正在校验单据、权限和候选差异…', id: assistantMessageId, role: 'assistant', streaming: true },
  ];
  if (!requestNo) {
    messages.value = messages.value.map((item) => item.id === assistantMessageId
      ? { ...item, content: '需要准确的采购申请编号，当前请求没有创建提案。', streaming: false }
      : item);
    message.warning('需要准确的采购申请编号，当前请求没有创建提案。');
    return;
  }
  if (intent !== 'rfq_draft' && !canCreatePurchaseDraft) {
    messages.value = messages.value.map((item) => item.id === assistantMessageId
      ? { ...item, content: '当前账号没有采购申请写入权限，未创建提案。', streaming: false }
      : item);
    message.error('你没有采购申请写入权限。');
    return;
  }
  if (intent === 'rfq_draft' && !(hasAccessByRoles(['SYS_ADMIN']) ||
    (hasAccessByCodes(['procurement.rfqs.write']) && hasAccessByCodes(['master.suppliers.read'])))) {
    messages.value = messages.value.map((item) => item.id === assistantMessageId
      ? { ...item, content: '创建询价提案需要询价写入和供应商读取权限。', streaming: false }
      : item);
    message.error('创建询价提案需要询价写入和供应商读取权限。');
    return;
  }
  const actionType = intent === 'purchase_update'
    ? 'purchase_request.update_draft'
    : intent === 'purchase_submit'
      ? 'purchase_request.submit'
      : 'rfq.create_draft';
  const payload = intent === 'purchase_update'
    ? { request_no: requestNo, changes: understanding.action_fields ?? {} }
    : intent === 'purchase_submit'
      ? { request_no: requestNo }
      : { source_request_no: requestNo, ...(understanding.action_fields ?? {}) };
  actionProposalBusy.value = true;
  try {
    const proposal = await createActionProposalApi(actionType, payload, makeIdempotencyKey());
    const canConfirm = canConfirmActionProposal(proposal, proposal.preview_version, false);
    const diff = proposal.diff.map((entry) => `${String(entry.field)}：${JSON.stringify(entry.after)}`).join('\n');
    const suppliers = proposal.evidence.find((entry) => entry.type === 'suppliers') as any;
    const supplierSummary = suppliers?.items?.map((item: any) => item.supplier_name).filter(Boolean).join('、');
    messages.value = messages.value.map((item) => item.id === assistantMessageId
      ? { ...item, content: canConfirm ? `待确认提案已生成。\n${diff}${supplierSummary ? `\n受邀供应商：${supplierSummary}` : ''}` : proposal.blockers.join('；') || '当前提案不能确认，请补充信息后重试。', streaming: false }
      : item);
    if (!canConfirm) return;
    Modal.confirm({
      title: intent === 'purchase_update' ? '确认修改采购申请' : intent === 'purchase_submit' ? '确认提交采购申请' : '确认创建询价草稿',
      content: `申请：${requestNo}\n${diff}${supplierSummary ? `\n供应商：${supplierSummary}` : ''}\n确认后仅执行预览所列动作。`,
      okText: intent === 'purchase_submit' ? '确认提交' : intent === 'rfq_draft' ? '确认创建询价草稿' : '确认修改',
      onOk: async () => {
        actionProposalBusy.value = true;
        try {
          const result = await confirmActionProposalApi<Record<string, any>>(proposal.confirmation_id, proposal.preview_version);
          const resourceNo = result.request_no || result.rfq_no || result.id;
          const status = result.status ? `，状态：${result.status}` : '';
          messages.value = messages.value.map((item) => item.id === assistantMessageId
            ? { ...item, content: `${item.content}\n\n已执行提案${resourceNo ? `，单号：${resourceNo}` : ''}${status}。` }
            : item);
          message.success('已按确认的预览执行动作');
        } finally {
          actionProposalBusy.value = false;
        }
      },
      onCancel: async () => {
        await cancelActionProposalApi(proposal.confirmation_id, proposal.preview_version);
      },
    });
  } catch (error: any) {
    messages.value = messages.value.map((item) => item.id === assistantMessageId
      ? { ...item, content: error?.message || '动作预览生成失败，未执行写入。', streaming: false }
      : item);
  } finally {
    actionProposalBusy.value = false;
    scrollToBottom();
  }
}

function makeIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function progressTask(item: UiMessage): AgentApi.Task {
  return { id: item.id, revision: 0, status: 'RUNNING', reply: '', error_code: null, messages: [], trace: [] };
}
function canRetryBatch(item: UiMessage) {
  const batch = item.citations?.find((citation) => citation.type === 'multi_intent')?.batch;
  return !sending.value && !item.cancelPending && !item.batchProgress && item.id === messages.value.at(-1)?.id
    && batch?.tasks.every((task: any) => !['PENDING', 'PLANNED', 'RUNNING'].includes(task.status))
    && batch?.tasks.some((task: any) => ['FAILED', 'BLOCKED', 'CANCELLED'].includes(task.status));
}
async function retryBatch() {
  inputText.value = '重试上一组失败或已取消的查询项，保留已完成项。';
  await onSend(true);
}
async function reloadActiveConversation() {
  if (!activeConversationId.value || sending.value) return;
  const epoch = chatEpoch;
  const res = await getAIMessagesApi(activeConversationId.value);
  if (epoch === chatEpoch) { messages.value = historyMessages(res.items); scrollToBottom(); }
}

async function previewPurchaseRequestDraft(freeText?: string) {
  if (freeText) await loadDraftFormOptions();
  const payload: import('#/api').PurchaseRequestApi.RequestPayload = {
    purpose: draftPurpose.value.trim(),
    priority: draftPriority.value,
    budget_amount: draftBudget.value ?? null,
    currency_code: draftCurrency.value,
    expected_date: typeof draftExpectedDate.value === 'string' ? draftExpectedDate.value : draftExpectedDate.value?.format?.('YYYY-MM-DD') ?? null,
    items: draftItems.value.map((item) => ({
      product_id: Number(item.product_id) > 0 ? item.product_id : null,
      requested_name: item.requested_name.trim(),
      quantity: Number(item.quantity),
      unit_id: Number(item.unit_id),
      technical_requirements: item.technical_requirements?.trim() || null,
    })),
  };
  const text = freeText ?? `采购用途：${payload.purpose}；物料：${payload.items.map((item) => `${item.requested_name} ${formatQuantity(item.quantity)} ${draftUnits.value.find((unit) => unit.id === item.unit_id)?.unit_name ?? ''}`).join('；')}`;
  inputText.value = '';
  const history = [...messages.value];
  const userId = nextId();
  const assistantId = nextId();
  messages.value = [
    ...history,
    { content: text, draftInteraction: true, id: userId, role: 'user' },
    { content: '', draftInteraction: true, id: assistantId, role: 'assistant', streaming: true },
  ];
  sending.value = true;
  scrollToBottom();
  try {
    const requestEpoch = chatEpoch;
    const result = await proposePurchaseRequestDraftApi(
      freeText ? [...draftFollowups.value, freeText].join('\n') : payload,
      activeConversationId.value,
    );
    if (requestEpoch !== chatEpoch) return;
    draftMissingFields.value = result.missing_fields;
    if (result.missing_fields.length > 0) {
      draftPurpose.value = result.draft.purpose ?? '';
      draftPriority.value = result.draft.priority ?? 'NORMAL';
      draftBudget.value = result.draft.budget_amount == null ? undefined : Number(result.draft.budget_amount);
      draftCurrency.value = result.draft.currency_code ?? 'CNY';
      draftExpectedDate.value = result.draft.expected_date ?? undefined;
      draftItems.value = result.draft.items.map((item) => ({
        product_id: item.product_id ?? undefined,
        requested_name: item.requested_name ?? '',
        quantity: item.quantity == null ? undefined : Number(item.quantity),
        unit_id: item.unit_id ?? undefined,
        technical_requirements: item.technical_requirements ?? undefined,
      }));
      if (!draftItems.value.length) draftItems.value = [{ requested_name: '' }];
      draftPrepared.value = true;
      draftMode.value = true;
      draftFollowups.value = freeText ? [...draftFollowups.value, freeText] : draftFollowups.value;
    } else {
      draftPrepared.value = false;
      draftMode.value = false;
      draftFollowups.value = [];
    }
    const responseText = result.missing_fields.length
      ? `我已从描述中识别到${draftItems.value.length}项采购信息。已提供的内容已保留，请在输入区补充标记为缺失的项目，再生成草稿预览。\n\n尚缺：${result.missing_fields.join('、')}`
      : '已识别并整理采购信息，下面是草稿预览。请核对后确认创建。';
    messages.value = messages.value.map((item) =>
      item.id === assistantId
        ? {
            ...item,
            content: responseText,
            ...(result.missing_fields.length ? {} : { draftProposal: result }),
            streaming: false,
          }
        : item,
    );
  } catch (error: any) {
    if (!inputText.value) inputText.value = text;
    draftMode.value = true;
    messages.value = messages.value.map((item) =>
      item.id === assistantId
        ? { ...item, content: `⚠ ${error?.message || '草稿建议生成失败'}`, streaming: false }
        : item,
    );
  } finally {
    sending.value = false;
    scrollToBottom();
  }
}

function confirmCreatePurchaseDraft(item: UiMessage) {
  if (!canCreatePurchaseDraft) { message.error('你没有创建采购申请草稿的权限。'); return; }
  const proposal = item.draftProposal;
  if (!proposal || !proposal.confirmation_id || !proposal.preview_version || item.draftCreatedRequestNo) return;
  const confirmationId = proposal.confirmation_id;
  const previewVersion = proposal.preview_version;
  const itemSummary = proposal.display_items
    .map((line) => `${line.requested_name} ${formatQuantity(line.quantity)} ${line.unit_name}`)
    .join('；');
  Modal.confirm({
    content: `用途：${proposal.draft.purpose}。明细：${itemSummary}。确认后会创建状态为“草稿”的采购申请，不会提交审批。`,
    okText: '确认创建草稿',
    onOk: async () => {
      creatingDraftMessageId.value = item.id;
      try {
        const created = await confirmPurchaseRequestDraftApi(confirmationId, previewVersion);
        const requestNo = created.request_no || String(created.id);
        messages.value = messages.value.map((messageItem) =>
          messageItem.id === item.id
            ? {
                ...messageItem,
                content: `${messageItem.content}\n\n已创建草稿 ${requestNo}，当前状态：草稿。你可以在采购申请列表中继续检查和编辑。`,
                draftCreatedRequestNo: requestNo,
                sourceRecords: [
                  {
                    dataset: 'purchase_requests',
                    filters: { keywords: requestNo },
                    label: `采购申请 ${requestNo}`,
                  },
                ],
              }
            : messageItem,
        );
        message.success(`已创建采购申请草稿 ${requestNo}`);
      } finally {
        creatingDraftMessageId.value = undefined;
      }
    },
    title: '确认创建采购申请草稿',
  });
}



function openDataset(dataset: string) {
  if (!canReadDataset(dataset)) return;
  const paths: Record<string, string> = {
    accepted_orders_finance_gaps: '/finance/reconciliations',
    approved_requests_without_rfq: '/procurement/requests',
    deliveries: '/warehouse/deliveries',
    exceptions: '/operations/exceptions',
    finance_invoices: '/finance/invoices',
    finance_payments: '/finance/payments',
    finance_reconciliations: '/finance/reconciliations',
    finance_settlements: '/finance/settlements',
    inventory: '/warehouse/inventory',
    inventory_by_batch: '/warehouse/inventory',
    inventory_movement_trace: '/warehouse/inventory',
    inventory_transactions: '/warehouse/transactions',
    purchase_orders: '/procurement/orders',
    purchase_requests: '/procurement/requests',
    quality_acceptances: '/quality/acceptances',
    rfqs: '/procurement/rfqs',
    suppliers: '/master/suppliers',
    supplier_quote_delivery_profile: '/master/suppliers',
    supplier_quotes: '/procurement/rfqs',
    weekly_order_risks: '/procurement/orders',
  };
  const path = paths[dataset];
  if (path) void router.push(path);
}

function openSourceRecord(record: NonNullable<UiMessage['sourceRecords']>[number]) {
  if (!canReadDataset(record.dataset)) return;
  if (record.dataset === 'rfqs' && record.record_id) {
    void router.push({
      path: '/procurement/rfqs',
      query: { ai_record_id: String(record.record_id) },
    });
    return;
  }
  if (record.dataset === 'purchase_orders' && record.record_id) {
    void router.push({
      name: 'PurchaseOrderDetail',
      params: { id: record.record_id },
    });
    return;
  }
  const financeTypes: Record<string, { kind: string; path: string }> = {
    finance_invoices: { kind: 'invoices', path: '/finance/invoices' },
    finance_payments: { kind: 'payments', path: '/finance/payments' },
    finance_reconciliations: { kind: 'reconciliations', path: '/finance/reconciliations' },
    finance_settlements: { kind: 'settlements', path: '/finance/settlements' },
  };
  const financeTarget = financeTypes[record.dataset];
  if (financeTarget && record.record_id) {
    void router.push({
      path: financeTarget.path,
      query: {
        ai_record_id: String(record.record_id),
        ai_record_type: financeTarget.kind,
      },
    });
    return;
  }
  const target = AI_FILTER_TARGETS.find((item) => item.dataset === record.dataset);
  if (!target) return;
  if (record.dataset === 'quality_acceptances' && record.record_id) {
    void router.push({
      path: target.path,
      query: { ai_record_id: String(record.record_id) },
    });
    return;
  }
  if (
    (record.dataset === 'purchase_requests' || record.dataset === 'deliveries') &&
    record.record_id
  ) {
    void router.push({
      path: target.path,
      query: { ai_record_id: String(record.record_id) },
    });
    return;
  }
  const recordFilters = record.filters ?? {};
  const { keywords, ...filters } = recordFilters;
  void router.push({
    path: target.path,
    query: {
      ai_filters: JSON.stringify({
        dataset: target.dataset,
        filters,
        keywords: typeof keywords === 'string' ? keywords : null,
      }),
    },
  });
}

async function generateBriefing(push: boolean) {
  if (push && !canPushBriefing) { message.error('你没有推送运营晨报的权限。'); return; }
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
  if (!canPushBriefing) { message.error('你没有推送运营晨报的权限。'); return; }
  Modal.confirm({
    content: '晨报将发送给系统管理员和采购经理，是否继续？',
    okText: '确认推送',
    onOk: () => generateBriefing(true),
    title: '确认晨报接收对象',
  });
}

async function parseListFilters() {
  if (!filterQuestion.value.trim() || filterParsing.value) return;
  if (!canReadDataset(filterDataset.value)) { message.error('你没有读取该业务列表的权限。'); return; }
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
  if (!target || !filterResult.value || !canReadDataset(target.dataset)) return;

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
  if (event.isComposing || event.keyCode === 229) return;
  if (slashMenuOpen.value) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      slashMenuActiveIndex.value =
        (slashMenuActiveIndex.value + direction + slashCommands.value.length) % slashCommands.value.length;
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      slashMenuOpen.value = false;
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      selectSlashCommand(slashCommands.value[slashMenuActiveIndex.value]?.value);
      return;
    }
  }

  // 输入框为空时键入“/”，立即打开功能选择菜单。
  if (event.key === '/' && !inputText.value) {
    event.preventDefault();
    openSlashMenu();
    return;
  }

  // Enter 发送，Shift+Enter 换行
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    onSend();
  }
}

function openSlashMenu() {
  slashMenuActiveIndex.value = 0;
  slashMenuOpen.value = true;
}

function onComposerInput(event: Event) {
  const target = event.target as HTMLTextAreaElement | null;
  if (target?.value === '/') {
    inputText.value = '';
    openSlashMenu();
  } else if (target?.value) {
    slashMenuOpen.value = false;
  }
}

async function selectSlashCommand(command?: SlashCommand) {
  slashMenuOpen.value = false;
  inputText.value = '';

  if (command === 'filter' && !filterDatasetOptions.value.length) return;
  if (command === 'purchase-draft' && !canCreatePurchaseDraft) return;
  if (command === 'briefing-push' && !canPushBriefing) return;

  if (command === 'agent') {
    if (currentAgent.value?.status === 'WAITING_INPUT' || currentAgent.value?.status === 'RUNNING') { message.info('请先完成当前查询。'); return; }
    agentMode.value = true;
    draftMode.value = false;
    return;
  }
  agentMode.value = false;
  if (command === 'filter') {
    if (!filterDatasetOptions.value.some((option) => option.value === filterDataset.value)) {
      filterDataset.value = filterDatasetOptions.value[0]?.value ?? '';
    }
    filterPanelOpen.value = true;
    filterQuestion.value = '';
    filterResult.value = undefined;
    await nextTick();
    document.querySelector<HTMLInputElement>('.ai-filter-question input')?.focus();
    return;
  }
  if (command === 'purchase-draft') {
    draftFollowups.value = [];
    draftPrepared.value = false;
    draftMissingFields.value = [];
    draftPurpose.value = '';
    draftPriority.value = 'NORMAL';
    draftBudget.value = undefined;
    draftCurrency.value = 'CNY';
    draftExpectedDate.value = undefined;
    draftItems.value = [{ requested_name: '' }];
    draftMode.value = true;
    void loadDraftFormOptions();
    await nextTick();
    return;
  }
  if (command === 'briefing') {
    await generateBriefing(false);
    return;
  }
  if (command === 'briefing-push') {
    confirmBriefingPush();
  }
}

async function loadDraftFormOptions() {
  try {
    const units = await getUnitListApi({ silent: true });
    draftUnits.value = units.filter((unit) => unit.status === 'ACTIVE').map(({ id, unit_name }) => ({ id, unit_name }));
    if (canReadDraftProducts.value) {
      draftProductsLoading.value = true;
      const result = await getProductListApi({ page: 1, page_size: 100, status: 'ACTIVE' }, { silent: true });
      draftProducts.value = result.items.map((product) => ({
        id: product.id, product_code: product.product_code, product_name: product.product_name,
        model: product.model, packaging_spec: product.packaging_spec, purity_value: product.purity_value,
        purity_unit: product.purity_unit, unit_id: product.unit_id,
      }));
    }
  } catch {
    message.error('加载产品或计量单位失败，请稍后重试。');
  } finally {
    draftProductsLoading.value = false;
  }
}

async function searchDraftProducts(keyword: string) {
  if (!canReadDraftProducts.value) return;
  draftProductsLoading.value = true;
  try {
    const result = await getProductListApi({ page: 1, page_size: 100, keyword: keyword.trim() || undefined, status: 'ACTIVE' }, { silent: true });
    draftProducts.value = result.items.map((product) => ({
      id: product.id, product_code: product.product_code, product_name: product.product_name,
      model: product.model, packaging_spec: product.packaging_spec, purity_value: product.purity_value,
      purity_unit: product.purity_unit, unit_id: product.unit_id,
    }));
  } catch {
    message.error('搜索产品目录失败，请稍后重试。');
  } finally {
    draftProductsLoading.value = false;
  }
}

function addDraftItem() { draftItems.value.push({ requested_name: '' }); }
function needsDraftProductChoice(index: number) {
  return draftMissingFields.value.some((field) => field.startsWith(`第 ${index + 1} 项产品规格`));
}
function draftPriorityLabel(value: string) {
  return ({ LOW: '低', NORMAL: '普通', HIGH: '高', URGENT: '紧急' } as Record<string, string>)[value] ?? value;
}
function removeDraftItem(index: number) {
  if (draftItems.value.length > 1) draftItems.value.splice(index, 1);
}
function onDraftProductChange(item: (typeof draftItems.value)[number]) {
  const product = draftProducts.value.find((candidate) => candidate.id === item.product_id);
  if (!product) return;
  item.requested_name = product.product_name;
  item.unit_id = product.unit_id;
}

watch(
  () => route.query.draft_context,
  (rawContext) => {
    if (typeof rawContext !== 'string' || !rawContext.trim()) return;
    newConversation();
    draftMode.value = true;
    draftFollowups.value = [rawContext.trim().slice(0, 1500)];
    inputText.value = rawContext.trim().slice(0, 1500);
    message.info('已带入提醒背景。请补充真实采购物料、数量、单位和用途，再生成草稿预览。');
    const query = { ...route.query };
    delete query.draft_context;
    void router.replace({ path: route.path, query });
  },
  { immediate: true },
);

watch(() => route.query.conversation, (value) => {
  const id = Number(value);
  if (id === activeConversationId.value || sending.value) return;
  const conversation = conversations.value.find((item) => item.id === id);
  if (conversation) void openConversation(conversation);
  else if (!value && activeConversationId.value) newConversation();
});

onMounted(() => {
  void loadConversations().then(async () => {
    const id = Number(route.query.conversation);
    const conversation = conversations.value.find((item) => item.id === id);
    if (conversation) await openConversation(conversation);
    else if (typeof route.query.task === 'string') {
      // 旧独立页面收藏地址重定向到聊天，仅按本人任务 API 恢复。
      const taskId = route.query.task;
      const item: UiMessage = { id: nextId(), role: 'assistant', content: '', agentTaskId: taskId };
      messages.value = [item];
      await refreshAgent(item);
      if (item.agentTaskId && messages.value[0]?.agentTask?.conversation_id) {
        const task = messages.value[0].agentTask;
        activeConversationId.value = task.conversation_id ?? undefined;
      }
      scheduleAgentPolling();
    }
  });
  document.addEventListener('click', closeHistoryMenu);
  document.addEventListener('visibilitychange', onVisibilityChange);
});
onUnmounted(() => { document.removeEventListener('visibilitychange', onVisibilityChange); resetChatWork(); document.removeEventListener('click', closeHistoryMenu); });
</script>

<template>
  <Page auto-content-height>
    <div class="ai-workspace flex h-full min-h-0">
      <!-- 左侧会话列表 -->
      <aside class="ai-sidebar flex shrink-0 flex-col" :class="{ 'is-collapsed': sidebarCollapsed, 'is-expanded': sidebarExpanded }">
        <div class="ai-brand-row">
          <div class="ai-brand"><img :src="assistantLogo" alt="" /> <span>化运 AI</span></div>
          <button class="ai-icon-button ai-sidebar-toggle" type="button" aria-label="切换会话侧栏" title="收起或展开会话侧栏" @click="toggleSidebar">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg>
          </button>
        </div>
        <div class="ai-search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 5 5"/></svg>
          <input v-model="conversationSearch" type="search" aria-label="搜索会话" placeholder="搜索对话" />
        </div>
        <button class="ai-new-chat" type="button" @click="newConversation">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 20a8 8 0 1 0-8-8v7l3-2"/><path d="M12 8v8M8 12h8"/></svg>
          开启新对话
        </button>
        <div class="ai-history-label">会话记录</div>
        <Spin :spinning="conversationsLoading" class="ai-history min-h-0 flex-1 overflow-y-auto">
          <p v-if="visibleConversations.length === 0" class="ai-no-history">{{ conversationSearch ? '没有找到相关会话' : '还没有会话' }}</p>
          <div v-else class="ai-history-list">
            <section v-for="group in conversationGroups" :key="group.label" class="ai-history-group">
              <h2 class="ai-history-group-label">{{ group.label }}</h2>
              <div
              v-for="item in group.items"
              :key="item.id"
              class="ai-history-item"
              :class="{
                'is-active': item.id === activeConversationId,
              }"
              role="button"
              tabindex="0"
              @click="openConversation(item)"
              @keydown.enter.self="openConversation(item)"
              @keydown.space.self.prevent="openConversation(item)"
            >
                <div class="ai-history-content">
                  <input v-if="editingConversationId === item.id" v-model="editingTitle" class="ai-rename-input" maxlength="255" aria-label="会话名称" @click.stop @keydown.enter.stop="saveRename(item)" @keydown.esc.stop="editingConversationId = undefined" @blur="saveRename(item)" />
                  <span v-else class="ai-history-title" :title="item.title || `会话 #${item.id}`">{{ item.title || `会话 #${item.id}` }}</span>
                  <span class="ai-history-date">{{ formatDateTime(item.last_message_at || item.created_at) }}</span>
                </div>
                <button class="ai-icon-button ai-history-more" type="button" :aria-label="`管理会话 ${item.title || item.id}`" :aria-expanded="menuConversationId === item.id" aria-haspopup="menu" title="管理会话" @click.stop="toggleConversationMenu(item.id, $event)">
                  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>
                </button>
                <div v-if="menuConversationId === item.id" class="ai-history-menu" role="menu" @click.stop @keydown="onConversationMenuKeydown">
                  <button type="button" role="menuitem" @click.stop="beginRename(item)">重命名</button>
                  <button type="button" role="menuitem" @click.stop="togglePinned(item)">{{ item.pinned ? '取消置顶' : '置顶会话' }}</button>
                  <button class="is-danger" type="button" role="menuitem" @click.stop="menuConversationId = undefined; removeConversation(item)">删除会话</button>
                </div>
              </div>
            </section>
          </div>
        </Spin>
      </aside>

      <!-- 右侧对话区 -->
      <main class="ai-main flex min-w-0 flex-1 flex-col" :class="{ 'is-empty': messages.length === 0 }">
        <div class="ai-toolbar text-sm font-medium">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div>
              <span class="ai-toolbar-title">化运 AI 助手</span>
            </div>
            <Button size="small" @click="router.push('/ai/tasks')">Agent Inbox</Button>
          </div>
          <div v-if="filterPanelOpen" class="mt-3 rounded-md border border-border p-3 text-sm font-normal">
            <div class="mb-2 flex items-center justify-between">
              <span class="font-medium">自然语言筛选</span>
              <Button size="small" type="text" @click="filterPanelOpen = false">关闭</Button>
            </div>
            <div class="grid gap-2 sm:grid-cols-[180px_1fr_auto]">
              <Select v-model:value="filterDataset" :options="filterDatasetOptions" />
              <Input class="ai-filter-question" v-model:value="filterQuestion" placeholder="例如：只看本月已批准的采购申请" @press-enter="parseListFilters" />
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
          ref="messagesRef" role="log" aria-live="polite" aria-label="对话记录"
          class="ai-messages min-h-0 flex-1 space-y-4 overflow-y-auto"
        >
          <Spin :spinning="historyLoading">
            <div v-if="messages.length === 0" class="ai-welcome">
              <img :src="assistantLogo" alt="" />
              <div>
                <h1>你好，今天想了解什么？</h1>
                <p>采购、库存、质量与运营信息，随时为你解答。</p>
              </div>
            </div>
            <div
              v-for="item in messages"
              :key="item.id"
              class="ai-message-row flex"
              :class="item.role === 'user' ? 'justify-end' : 'justify-start'"
            >
              <!-- 用户消息按纯文本展示；助手消息渲染 Markdown -->
              <div
                v-if="item.role === 'user'"
                class="ai-user-message max-w-[75%] whitespace-pre-wrap px-4 py-3 text-sm"
              >
                {{ item.content }}
              </div>
              <div
                v-else
                class="ai-assistant-message min-w-0 px-4 py-3 text-sm"
                :class="[item.queryTrace?.rows?.length || item.agentTask || queryViews(item).length || batchToolViews(item).length || item.batchProgress ? 'w-full max-w-[1100px]' : 'max-w-[85%]', { 'is-agent': item.agentTask }]"
              >
                <div v-if="item.content && !item.agentTask && !item.streaming" class="mt-2 flex flex-wrap items-center gap-2">
                  <AgentSourcePopover v-for="group in sourceGroups(item)" :key="group.label" :entries="group.entries" :source-label="group.label" @open-record="openSourceRecord" @open-dataset="openDataset" />
                  <span v-if="sourceGroups(item).some((group) => group.entries.some((source) => source.status))" class="text-muted-foreground text-xs">历史答案已保留；部分来源可能已更新、失效或尚未核验，请查看来源状态。</span>
                </div>
                <div
                  v-if="item.content && !item.agentTask"
                  class="chat-md [&_a]:text-blue-500 [&_a]:underline [&_code]:bg-black/20 [&_code]:rounded [&_code]:px-1 [&_li]:ml-4 [&_ol]:list-decimal [&_p]:my-1 [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:my-1"
                  v-html="renderMessage(item.id, item.content)"
                ></div>
                <span v-else-if="item.streaming && !item.batchProgress && !item.agentTask" class="inline-flex items-center gap-2" role="status" aria-live="polite">
                  <Spin size="small" aria-hidden="true" />
                  <span>正在思考…</span>
                </span>
                <AgentChatTask v-if="item.agentTask" :task="item.agentTask" :busy="sending" @continue="continueAgent(item, $event)" />
                <AgentChatTask v-if="item.batchProgress" :task="progressTask(item)" :progress="item.batchProgress" :busy="false" :show-actions="!item.cancelPending" />
                <Button v-if="canRetryBatch(item)" type="text" size="small" @click="retryBatch">重试未完成项</Button>
                <Button v-if="item.cancelPending && !sending" type="text" size="small" @click="reloadActiveConversation">刷新会话</Button>
                <div v-if="item.agentError" role="alert"><p>{{ item.agentError }}</p><Button size="small" @click="refreshAgent(item)">重试读取</Button></div>
                <div v-if="item.draftProposal && canCreatePurchaseDraft" class="mt-3 space-y-2 rounded-md border border-border/70 bg-background/70 p-3 text-xs">
                  <div class="font-medium">采购申请草稿预览 · 尚未保存</div>
                  <div v-if="item.draftProposal.clarification_question" role="status" class="text-amber-700">{{ item.draftProposal.clarification_question }}</div>
                  <div>用途：{{ item.draftProposal.draft.purpose }}</div>
                  <div>优先级：{{ item.draftProposal.draft.priority || 'NORMAL' }} · 币种：{{ item.draftProposal.draft.currency_code || 'CNY' }}</div>
                  <div v-if="item.draftProposal.draft.budget_amount">预算：{{ formatAmount(item.draftProposal.draft.budget_amount) }}</div>
                  <ul class="list-disc space-y-1 pl-5">
                    <li v-for="(line, index) in item.draftProposal.display_items" :key="`${line.requested_name}-${index}`">
                      {{ line.requested_name }}：{{ formatQuantity(line.quantity) }} {{ line.unit_name }}
                      <span v-if="line.product_name" class="text-muted-foreground">（关联产品：{{ line.product_name }}）</span>
                      <span v-if="line.budget_price" class="text-muted-foreground">· 单价 {{ formatAmount(line.budget_price, 6) }}</span>
                    </li>
                  </ul>
                  <ul v-if="item.draftProposal.warnings.length" class="list-disc pl-5 text-amber-700">
                    <li v-for="warning in item.draftProposal.warnings" :key="warning">{{ warning }}</li>
                  </ul>
                  <details v-if="item.draftProposal.evidence.length" class="border-t border-border/50 pt-2">
                    <summary class="cursor-pointer text-muted-foreground">产品、库存与报价查询依据（{{ item.draftProposal.evidence.length }} 项）</summary>
                    <ul class="list-disc space-y-1 pl-5">
                      <li v-for="(entry, index) in item.draftProposal.evidence" :key="`${entry.tool}-${index}`">
                        {{ entry.label }}：{{ entry.rows?.length ? `${entry.rows.length} 条记录` : entry.totals?.length ? entry.totals.map((total: any) => `${formatQuantity(total.available_quantity)} ${total.unit_name}`).join('、') : '无匹配记录' }}
                        <span v-if="entry.sources?.length" class="text-muted-foreground"> · 来源 {{ entry.sources.map((source: any) => `${source.resource}#${source.record_id}`).join('、') }}</span>
                        <span v-if="entry.scope" class="text-muted-foreground"> · {{ entry.scope }}</span>
                        <ul v-if="entry.rows?.length" class="list-disc pl-5 text-muted-foreground">
                          <li v-for="(row, rowIndex) in entry.rows" :key="rowIndex">
                            <template v-if="entry.tool === 'catalog.search_products'">{{ row.product_name }} · {{ row.product_code }} · {{ row.model || '未登记型号' }} / {{ row.packaging_spec || '未登记包装' }}</template>
                            <template v-else-if="entry.tool === 'supplier_quotes.compare'">{{ row.supplier_name }}：{{ formatAmount(row.unit_price, 6) }} {{ row.currency_code }}/{{ row.unit_name }} · {{ row.cost_analysis?.complete ? `总成本 ${formatAmount(row.cost_analysis.total_cost)} ${row.currency_code}` : `总成本不完整：${row.cost_analysis?.reasons.join('；') || '缺少信息'}` }} · {{ row.rank ? `可比组排名 ${row.rank}` : '不可比，不排序' }}<span v-if="row.valid_until"> · 有效至 {{ row.valid_until }}</span></template>
                            <template v-else>{{ row.rfq_no }} · 询价明细 #{{ row.rfq_item_id }} · {{ row.specification || '未登记规格' }}</template>
                          </li>
                        </ul>
                      </li>
                    </ul>
                  </details>
                  <div class="text-muted-foreground">确认后仅创建状态为“草稿”的采购申请；仍需你在业务模块中检查并自行提交审批。</div>
                  <div class="flex justify-end">
                    <Button
                      :disabled="!item.draftProposal.confirmation_id || Boolean(item.draftCreatedRequestNo) || Boolean(creatingDraftMessageId)"
                      :loading="creatingDraftMessageId === item.id"
                      type="primary"
                      @click="confirmCreatePurchaseDraft(item)"
                    >
                      {{ item.draftCreatedRequestNo ? `已创建 ${item.draftCreatedRequestNo}` : '确认创建草稿' }}
                    </Button>
                  </div>
                </div>
                <template v-for="view in queryViews(item)" :key="view.id">
                  <p v-if="view.question" class="mt-3 font-medium">{{ view.question }}</p>
                  <QueryEvidence :trace="view.queryTrace" :source-records="visibleSourceRecords(view)" @open-dataset="openDataset" @open-source-record="openSourceRecord" />
                </template>
                <template v-for="entry in batchToolViews(item)" :key="entry.task.id">
                  <details v-if="entry.task.status === 'SUCCEEDED' && entry.task.trace.some((step) => step.result?.tool === 'inventory.query_available')" class="mt-3 border-t border-border/50 pt-2">
                    <summary class="text-muted-foreground cursor-pointer select-none text-xs font-medium">
                      规格明细与数据来源（{{ primaryTaskResults(entry.task).filter((step) => step.result?.tool === 'inventory.query_available').length }} 个规格） · {{ entry.question }}
                    </summary>
                    <AgentChatTask :task="entry.task" :busy="false" :show-actions="false" compact-details />
                  </details>
                  <template v-else>
                    <p class="mt-3 font-medium">{{ entry.question }}</p>
                    <AgentChatTask :task="entry.task" :busy="false" :show-actions="false" />
                  </template>
                </template>
              </div>
            </div>
          </Spin>
        </div>

        <div class="ai-composer-shell">
          <div class="ai-composer">
            <div v-if="slashMenuOpen" class="ai-slash-menu" role="listbox" aria-label="选择 AI 功能">
              <button
                v-for="(command, index) in slashCommands"
                :key="command.value"
                class="ai-slash-command"
                :class="{ 'is-active': slashMenuActiveIndex === index }"
                role="option"
                :aria-selected="slashMenuActiveIndex === index"
                type="button"
                @mouseenter="slashMenuActiveIndex = index"
                @click="selectSlashCommand(command.value)"
              >
                <svg class="ai-slash-command-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <template v-if="command.icon === 'filter'"><path d="M3 4h14l-5.5 6v5l-3 1v-6L3 4Z" /></template>
                  <template v-else-if="command.icon === 'draft'"><path d="M6 2.8h5l4 4v10.4H6z"/><path d="M11 2.8v4h4M8.5 11h4M8.5 14h4"/></template>
                  <template v-else-if="command.icon === 'briefing'"><path d="M3 16.5h14M5 14V9m5 5V4m5 10v-7"/><path d="m4 7 5-3 5 3 3-2"/></template>
                  <template v-else><path d="M3 10h12M10 5l5 5-5 5"/><path d="M14 4h3v12h-3"/></template>
                </svg>
                <span class="ai-slash-command-copy">
                  <span class="ai-slash-command-label">{{ command.label }}</span>
                  <span class="ai-slash-command-description">{{ command.description }}</span>
                </span>
              </button>
            </div>
            <div v-if="draftMode && draftPrepared" class="ai-draft-form">
              <div class="ai-draft-mode-heading"><Tag color="blue">/ 采购申请草稿模式</Tag><span>Agent 已识别的内容已保留，只需补全缺失项</span></div>
              <div class="ai-draft-recognized">
                <strong>已识别</strong>
                <span>{{ draftPurpose || '采购用途待补充' }}</span>
                <span v-for="(item, index) in draftItems" :key="index">{{ item.requested_name || `物料 ${index + 1} 待补充` }}{{ item.quantity ? ` · ${formatQuantity(item.quantity)}` : '' }}{{ draftUnits.find((unit) => unit.id === item.unit_id)?.unit_name ? ` ${draftUnits.find((unit) => unit.id === item.unit_id)?.unit_name}` : '' }}{{ item.technical_requirements ? ` · ${item.technical_requirements}` : '' }}</span>
                <span v-if="draftExpectedDate">期望到货：{{ draftExpectedDate }}</span>
                <span v-if="draftBudget != null">预算：{{ formatAmount(draftBudget) }} {{ draftCurrency }}</span>
                <span v-if="draftPriority !== 'NORMAL'">优先级：{{ draftPriorityLabel(draftPriority) }}</span>
              </div>
              <Input v-if="!draftPurpose.trim()" v-model:value="draftPurpose" :maxlength="1000" placeholder="缺少：采购用途" />
              <div v-for="(item, index) in draftItems" :key="index" class="ai-draft-item">
                <div class="ai-draft-item-heading"><strong>物料 {{ index + 1 }}</strong><button v-if="draftItems.length > 1" type="button" class="ai-mode-exit" @click="removeDraftItem(index)">移除</button></div>
                <Select v-if="needsDraftProductChoice(index) && canReadDraftProducts" v-model:value="item.product_id" show-search :filter-option="false" :loading="draftProductsLoading" :options="[...draftProducts.map((product) => ({ value: product.id, label: `${product.product_name} · ${product.product_code}${product.purity_value != null && product.purity_value !== '' ? ` · ${formatQuantity(product.purity_value)}${product.purity_unit ?? ''}` : ''}${product.packaging_spec ? ` · ${product.packaging_spec}` : ''}${product.model ? ` · ${product.model}` : ''}` })), { value: -1, label: '目录外物料（手动填写）' }]" placeholder="请选择准确产品规格" @search="searchDraftProducts" @change="onDraftProductChange(item)" />
                <Input v-if="needsDraftProductChoice(index) && item.product_id === -1" v-model:value="item.requested_name" placeholder="目录外物料名称" />
                <Input v-if="!item.requested_name" v-model:value="item.requested_name" placeholder="缺少：物料名称" />
                <div class="ai-draft-grid ai-draft-line-grid">
                  <InputNumber v-if="item.quantity == null" v-model:value="item.quantity" class="w-full" :min="0.000001" :precision="6" placeholder="缺少：数量" />
                  <span v-else class="ai-draft-known-value">数量：{{ formatQuantity(item.quantity) }}</span>
                  <Select v-if="item.unit_id == null" v-model:value="item.unit_id" :options="draftUnits.map((unit) => ({ label: unit.unit_name, value: unit.id }))" placeholder="缺少：计量单位" />
                  <span v-else class="ai-draft-known-value">单位：{{ draftUnits.find((unit) => unit.id === item.unit_id)?.unit_name || '已识别' }}</span>
                </div>
              </div>
              <Button type="dashed" block @click="addDraftItem">＋ 添加物料</Button>
            </div>
            <div v-else-if="draftMode" class="ai-draft-query-heading"><Tag color="blue">/ 采购申请草稿模式</Tag><span>描述需求，Agent 会先提取已有信息，再询问缺项</span></div>
            <Input.TextArea
              v-if="!draftMode || !draftPrepared"
              v-model:value="inputText"
              class="ai-composer-input"
              :maxlength="2000"
              :rows="2"
              :placeholder="currentAgent?.status === 'WAITING_INPUT' ? '补充产品名称、规格或询价编号…' : agentMode ? '描述要查询的库存或供应商报价…' : draftMode ? '例如：实验室补充甲醇分析纯 50 升，预计 11 月 5 日到货…' : '给化运 AI 发送消息，输入 / 选择功能'"
              @keydown="onTextKeydown"
              @input="onComposerInput"
            />
            <div class="ai-composer-actions">
              <div class="flex min-w-0 items-center gap-3">
                <span class="ai-composer-hint">{{ currentAgent?.status === 'WAITING_INPUT' ? '补充信息后继续当前查询' : agentMode ? '采购只读查询' : draftMode ? (draftPrepared ? '补齐缺失信息后生成草稿预览' : '发送需求，由 Agent 识别已有采购信息') : 'Enter 发送 · Shift+Enter 换行' }}</span>
                <button v-if="agentMode" class="ai-mode-exit" type="button" @click="agentMode = false">退出只读查询</button>
                <button v-if="draftMode" class="ai-mode-exit" type="button" @click="draftMode = false">退出草稿模式</button>
              </div>
              <button v-if="canStop" class="ai-send" type="button" :disabled="stopping" aria-label="停止查询" title="停止查询" @click="stopCurrentWork"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1" /></svg></button>
              <button v-else class="ai-send" type="button" :disabled="sending || historyLoading || currentAgent?.status === 'RUNNING' || (draftMode ? (draftPrepared ? !draftFormReady : !inputText.trim()) : !inputText.trim())" :aria-label="draftMode ? (draftPrepared ? '生成草稿预览' : '识别采购信息') : '发送消息'" :title="draftMode ? (draftPrepared ? '生成草稿预览' : '识别采购信息') : '发送消息'" @click="onSend()">
                <svg v-if="!sending" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg>
                <span v-else class="ai-send-loading">···</span>
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  </Page>
</template>

<style scoped>
.ai-workspace {
  --ai-blue: #4568f5;
  --ai-blue-strong: #3659e8;
  --ai-ink: #172033;
  --ai-muted: #818b9e;
  position: relative;
  overflow: hidden;
  border: 1px solid #e7ebf1;
  border-radius: 14px;
  background: #fff;
  color: var(--ai-ink);
}

.ai-sidebar {
  flex: 0 0 280px;
  width: 280px;
  min-width: 0;
  min-height: 0;
  padding: 20px 14px 14px;
  border-right: 1px solid #e9edf3;
  background: #f8f9fb;
}
.ai-sidebar.is-collapsed { flex-basis: 68px; width: 68px; align-items: center; padding-inline: 8px; }
.ai-sidebar.is-collapsed .ai-brand-row { flex-direction: column; gap: 12px; padding: 0; }
.ai-sidebar.is-collapsed .ai-sidebar-toggle { position: static; }
.ai-sidebar.is-collapsed .ai-brand span,
.ai-sidebar.is-collapsed .ai-search,
.ai-sidebar.is-collapsed .ai-history-label,
.ai-sidebar.is-collapsed .ai-history { display: none; }
.ai-sidebar.is-collapsed .ai-new-chat { width: 46px; overflow: hidden; font-size: 0; }
.ai-sidebar.is-collapsed .ai-new-chat svg { flex: none; }

.ai-brand-row,
.ai-brand,
.ai-new-chat,
.ai-history-item,
.ai-composer-actions {
  display: flex;
  align-items: center;
}

.ai-brand-row { position: relative; justify-content: center; min-height: 32px; padding: 0 34px; }
.ai-brand { justify-content: center; gap: 9px; white-space: nowrap; color: var(--ai-blue); font-size: 19px; font-weight: 700; letter-spacing: -.04em; }
.ai-brand img { width: 29px; height: 29px; }
.ai-icon-button,
.ai-history-delete {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #7e8798;
  cursor: pointer;
}
.ai-icon-button svg, .ai-history-delete svg { width: 18px; height: 18px; }
.ai-icon-button:hover, .ai-history-delete:hover { background: #e9edf4; color: var(--ai-ink); }
.ai-sidebar-toggle { position: absolute; top: 1px; right: 0; display: grid; }
.ai-search { display: flex; width: 100%; min-width: 0; height: 38px; align-items: center; gap: 9px; margin-top: 20px; padding: 0 11px; border: 1px solid #e2e7ef; border-radius: 10px; background: #fff; color: #8792a4; transition: border-color .18s, box-shadow .18s; }
.ai-search:focus-within { border-color: #9db0ff; box-shadow: 0 0 0 3px rgb(69 104 245 / 9%); }
.ai-search svg { width: 17px; height: 17px; flex: none; }
.ai-search input { width: 100%; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--ai-ink); font: inherit; font-size: 13px; }
.ai-search input::placeholder { color: #9aa4b5; }
.ai-new-chat {
  justify-content: center;
  gap: 8px;
  width: 100%;
  min-height: 46px;
  margin: 14px 0 28px;
  border: 1px solid #e7eaf0;
  border-radius: 999px;
  background: #fff;
  box-shadow: 0 2px 4px rgb(30 46 77 / 5%);
  color: var(--ai-ink);
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: border-color .18s, box-shadow .18s;
}
.ai-new-chat svg { width: 19px; height: 19px; }
.ai-new-chat:hover { border-color: #b9c7ff; box-shadow: 0 4px 12px rgb(69 104 245 / 10%); }
.ai-history-label { padding: 0 12px 9px; color: var(--ai-muted); font-size: 12px; font-weight: 600; }
.ai-history { min-width: 0; margin: 0 -5px; overflow-x: hidden; }
.ai-history :deep(.ant-spin-container) { min-width: 0; }
.ai-history-list { display: grid; min-width: 0; gap: 12px; }
.ai-history-group { min-width: 0; }
.ai-history-group-label { margin: 0; padding: 4px 12px 8px; color: var(--ai-muted); font-size: 12px; font-weight: 600; }
.ai-history-item { position: relative; min-width: 0; min-height: 56px; gap: 4px; padding: 7px 7px 7px 12px; border-radius: 10px; cursor: pointer; font-size: 13px; }
.ai-history-item:hover, .ai-history-item.is-active { background: #ecf0f5; }
.ai-history-item:focus-visible { outline: 2px solid var(--ai-blue); outline-offset: -2px; }
.ai-history-content { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 3px; overflow: hidden; }
.ai-history-title { display: block; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ai-history-date { color: var(--ai-muted); font-size: 11px; white-space: nowrap; }
.ai-history-more { flex: 0 0 28px; opacity: 0; }
.ai-history-item:hover .ai-history-more, .ai-history-item:focus-within .ai-history-more { opacity: 1; }
.ai-history-menu { position: absolute; top: 42px; right: 5px; z-index: 10; display: grid; width: 128px; padding: 5px; border: 1px solid #e7ebf1; border-radius: 12px; background: #fff; box-shadow: 0 12px 28px rgb(25 38 65 / 15%); }
.ai-history-menu button { padding: 8px 10px; border: 0; border-radius: 7px; background: transparent; color: var(--ai-ink); cursor: pointer; text-align: left; font-size: 13px; }
.ai-history-menu button:hover, .ai-history-menu button:focus-visible { background: #f1f3f7; }
.ai-history-menu button.is-danger { color: #d53d4a; }
.ai-rename-input { width: 100%; min-width: 0; padding: 1px 4px; border: 1px solid #9db0ff; border-radius: 4px; outline: 0; font: inherit; }
.ai-no-history { padding: 12px; color: var(--ai-muted); font-size: 13px; }

.ai-main { min-height: 0; background: #fff; }
.ai-toolbar { padding: 16px 24px 12px; border-bottom: 1px solid #f0f1f4; }
.ai-toolbar-title { font-size: 14px; font-weight: 650; }
.ai-toolbar :deep(.ant-btn) { border-radius: 9px; }
.ai-messages { padding: 24px clamp(20px, 5vw, 88px); }
.ai-main.is-empty .ai-messages { flex: 0 0 auto; margin-top: auto; overflow: visible; padding-bottom: 0; }
.ai-welcome { display: flex; align-items: center; justify-content: center; gap: 14px; }
.ai-welcome img { width: 47px; height: 47px; }
.ai-welcome h1 { margin: 0; color: #151b29; font-size: clamp(22px, 2vw, 28px); font-weight: 650; letter-spacing: -.03em; }
.ai-welcome p { margin: 3px 0 0; color: var(--ai-muted); font-size: 13px; }
.ai-message-row { max-width: 1100px; margin: 0 auto 20px; }
.ai-user-message { border-radius: 16px 16px 4px 16px; background: #e8edff; color: #263568; line-height: 1.7; }
.ai-assistant-message { border-radius: 4px 16px 16px; background: #f5f7fa; color: var(--ai-ink); line-height: 1.75; }
.ai-assistant-message.is-agent { padding: 8px 0 12px; background: transparent; border-radius: 0; max-width: 760px; }
.ai-composer-shell { width: 100%; padding: 12px clamp(20px, 5vw, 88px) 22px; }
.ai-main.is-empty .ai-composer-shell { max-width: 1160px; margin: 24px auto auto; padding-bottom: 0; }
.ai-composer { position: relative; max-width: 1100px; margin: 0 auto; padding: 12px 14px 10px; border: 1px solid #e0e5ed; border-radius: 22px; background: #fff; box-shadow: 0 10px 28px rgb(37 52 88 / 6%); transition: border-color .18s, box-shadow .18s; }
.ai-draft-form { display: grid; gap: 10px; padding: 2px 2px 10px; }
.ai-draft-mode-heading, .ai-draft-query-heading, .ai-draft-item-heading { display: flex; align-items: center; gap: 10px; }
.ai-draft-mode-heading > span, .ai-draft-field > span { color: #818b9e; font-size: 12px; }
.ai-draft-query-heading { padding: 2px 2px 10px; color: #818b9e; font-size: 12px; }
.ai-draft-recognized { display: grid; gap: 4px; padding: 9px 11px; border-radius: 10px; background: #f5f7fb; color: #5c667b; font-size: 12px; }
.ai-draft-recognized strong { color: #4568f5; font-weight: 600; }
.ai-draft-known-value { align-self: center; color: #5c667b; font-size: 13px; }
.ai-draft-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 14px; }
.ai-draft-field { display: grid; gap: 5px; }
.ai-draft-item { display: grid; gap: 8px; padding: 10px; border: 1px solid #e9edf3; border-radius: 12px; background: #fafbfc; }
.ai-draft-item-heading { justify-content: space-between; color: #45516a; font-size: 13px; }
.ai-draft-line-grid { grid-template-columns: minmax(90px, .7fr) minmax(120px, .8fr) minmax(180px, 1.5fr); }
.ai-slash-menu { position: absolute; right: 14px; bottom: calc(100% + 10px); left: 14px; z-index: 5; display: grid; gap: 2px; padding: 7px; border: 1px solid #e4e8f0; border-radius: 14px; background: #fff; box-shadow: 0 14px 34px rgb(30 44 72 / 16%); }
.ai-slash-command { display: flex; min-width: 0; align-items: center; gap: 10px; padding: 8px 10px; border: 0; border-radius: 9px; background: transparent; color: #343b45; cursor: pointer; text-align: left; }
.ai-slash-command:hover, .ai-slash-command.is-active { background: #f1f2f3; }
.ai-slash-command-icon { width: 17px; height: 17px; flex: none; color: #606873; }
.ai-slash-command-copy { display: flex; min-width: 0; align-items: baseline; gap: 9px; }
.ai-slash-command-label { flex: none; font-size: 13px; font-weight: 500; }
.ai-slash-command-description { overflow: hidden; color: #9aa0a8; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.ai-composer:focus-within { border-color: #9db0ff; box-shadow: 0 10px 28px rgb(69 104 245 / 10%); }
.ai-composer-input :deep(textarea) { min-height: 62px; padding: 3px 5px; border: 0; background: transparent; box-shadow: none; resize: none; font-size: 15px; line-height: 1.55; }
.ai-composer-input :deep(textarea:focus) { border: 0; box-shadow: none; }
.ai-composer-input :deep(textarea::placeholder) { color: #a0aaba; }
.ai-composer-actions { justify-content: space-between; padding: 3px 0 0 5px; }
.ai-composer-hint { color: #a1aab9; font-size: 11px; }
.ai-mode-exit { border: 0; background: transparent; color: var(--ai-blue); cursor: pointer; font-size: 11px; }
.ai-mode-exit:hover { color: var(--ai-blue-strong); text-decoration: underline; }
.ai-send { display: grid; width: 36px; height: 36px; place-items: center; border: 0; border-radius: 50%; background: var(--ai-blue); color: #fff; cursor: pointer; transition: background .18s, transform .18s; }
.ai-send svg { width: 20px; height: 20px; }
.ai-send:hover:not(:disabled) { background: var(--ai-blue-strong); transform: translateY(-1px); }
.ai-send:disabled { background: #b9c6ff; cursor: not-allowed; }
.ai-send-loading { font-size: 17px; line-height: 1; }
.ai-icon-button:focus-visible, .ai-new-chat:focus-visible, .ai-history-delete:focus-visible, .ai-send:focus-visible { outline: 2px solid var(--ai-blue); outline-offset: 2px; }

:global(.dark .ai-workspace) { --ai-ink: #e2e8f0; --ai-muted: #94a3b8; border-color: #334155; background: #111827; }
:global(.dark .ai-workspace .ai-sidebar) { border-color: #334155; background: #151c28; }
:global(.dark .ai-workspace .ai-icon-button), :global(.dark .ai-workspace .ai-history-delete) { color: #94a3b8; }
:global(.dark .ai-workspace .ai-icon-button:hover), :global(.dark .ai-workspace .ai-history-delete:hover) { background: #273449; color: #f1f5f9; }
:global(.dark .ai-workspace .ai-search), :global(.dark .ai-workspace .ai-new-chat), :global(.dark .ai-workspace .ai-history-menu), :global(.dark .ai-workspace .ai-composer), :global(.dark .ai-workspace .ai-slash-menu) { border-color: #374151; background: #1f2937; color: #e2e8f0; }
:global(.dark .ai-workspace .ai-search input) { color: #e2e8f0; }
:global(.dark .ai-workspace .ai-search input::placeholder), :global(.dark .ai-workspace .ai-composer-input textarea::placeholder) { color: #94a3b8; }
:global(.dark .ai-workspace .ai-history-item:hover), :global(.dark .ai-workspace .ai-history-item.is-active), :global(.dark .ai-workspace .ai-history-menu button:hover), :global(.dark .ai-workspace .ai-history-menu button:focus-visible) { background: #273449; }
:global(.dark .ai-workspace .ai-history-menu) { box-shadow: 0 12px 28px rgb(0 0 0 / 30%); }
:global(.dark .ai-workspace .ai-history-menu button) { color: #e2e8f0; }
:global(.dark .ai-workspace .ai-main) { background: #111827; }
:global(.dark .ai-workspace .ai-toolbar) { border-color: #273449; }
:global(.dark .ai-workspace .ai-welcome h1) { color: #f8fafc; }
:global(.dark .ai-workspace .ai-user-message) { background: #26365d; color: #e0e7ff; }
:global(.dark .ai-workspace .ai-assistant-message) { background: #1f2937; color: #e2e8f0; }
:global(.dark .ai-workspace .ai-assistant-message.is-agent) { background: transparent; color: #e2e8f0; }
:global(.dark .ai-workspace .ai-slash-command) { color: #e2e8f0; }
:global(.dark .ai-workspace .ai-slash-command:hover), :global(.dark .ai-workspace .ai-slash-command.is-active) { background: #273449; }
:global(.dark .ai-workspace .ai-slash-command-icon), :global(.dark .ai-workspace .ai-slash-command-description) { color: #94a3b8; }
:global(.dark .ai-workspace .ai-composer) { box-shadow: 0 10px 28px rgb(0 0 0 / 20%); }
:global(.dark .ai-workspace .ai-composer-hint) { color: #94a3b8; }
:global(.dark .ai-workspace .ai-send:disabled) { background: #465582; color: #cbd5e1; }

@media (max-width: 900px) {
  .ai-sidebar { padding-inline: 10px; }
  .ai-toolbar { padding: 12px 16px; }
  .ai-toolbar :deep(.ant-btn) { height: 30px; padding-inline: 9px; font-size: 12px; }
  .ai-messages, .ai-composer-shell { padding-inline: 20px; }
  .ai-draft-grid, .ai-draft-line-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 640px) {
  .ai-sidebar { flex-basis: 68px; width: 68px; align-items: center; padding-inline: 8px; }
  .ai-sidebar.is-expanded { position: absolute; inset: 0 auto 0 0; z-index: 2; width: min(280px, 82vw); align-items: stretch; box-shadow: 12px 0 30px rgb(24 38 67 / 12%); }
  .ai-brand-row { flex-direction: column; gap: 14px; padding: 0; }
  .ai-sidebar-toggle { position: static; }
  .ai-sidebar.is-expanded .ai-brand-row { flex-direction: row; padding: 0 34px; }
  .ai-sidebar.is-expanded .ai-sidebar-toggle { position: absolute; }
  .ai-brand span, .ai-history, .ai-history-label, .ai-search { display: none; }
  .ai-sidebar.is-expanded .ai-brand span, .ai-sidebar.is-expanded .ai-history, .ai-sidebar.is-expanded .ai-history-label { display: block; }
  .ai-sidebar.is-expanded .ai-search { display: flex; }
  .ai-new-chat { width: 48px; overflow: hidden; font-size: 0; }
  .ai-sidebar.is-expanded .ai-new-chat { width: 100%; font-size: 14px; }
  .ai-new-chat svg { flex: none; }
  .ai-toolbar .text-muted-foreground { display: none; }
  .ai-welcome { flex-direction: column; text-align: center; }
  .ai-welcome img { width: 40px; height: 40px; }
  .ai-welcome h1 { font-size: 21px; }
  .ai-user-message, .ai-assistant-message { max-width: 100%; }
}
</style>
