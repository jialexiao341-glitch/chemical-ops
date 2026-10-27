/**
 * AI 助手接口。
 *
 * 与其余模块不同，对话走 SSE 流式（POST /ai/chat/stream），
 * axios 不便消费流，这里用 fetch + ReadableStream 直连，
 * 鉴权头从 access store 取 Bearer token。
 *
 * SSE 事件格式（后端 service.stream_chat_for_user）：
 *   event: delta  data: {"content": "..."}      增量文本
 *   event: done   data: {"conversation_id": …, "answer": …, "query_trace": …}
 *   event: error  data: {"message": "..."}
 */
import { useAccessStore } from '@vben/stores';

import { requestClient } from '#/api/request';
import { notifyNotificationChanged } from '../core/notification';
import type { AiTaskStatus } from './task-status';
import { createSseParser } from './sse-parser';

export * from './agent';
export * from './task-status';

export namespace AiApi {
  export interface BatchProgress {
    conversation_id: number;
    completed: number;
    total: number;
    tasks: Array<{ id: string; kind: string; question: string; status: AiTaskStatus; [key: string]: any }>;
  }
  /** 会话摘要 */
  export interface Conversation {
    business_scene: string;
    created_at?: string;
    id: number;
    last_message_at?: null | string;
    pinned: boolean;
    status: string;
    title?: null | string;
    updated_at?: string;
  }

  /** 会话消息 */
  export interface Message {
    citations?: any;
    content: string;
    conversation_id: number;
    created_at?: string;
    id: number;
    role: string;
  }

  /** 流式增量事件 */
  export interface StreamHandlers {
    onProgress?: (payload: BatchProgress) => void;
    onCancelled?: () => void;
    /** 收到增量文本 */
    onDelta?: (content: string) => void;
    /** 正常结束，携带会话 ID 与完整答案 */
    onDone?: (payload: {
      answer?: string;
      citations?: any;
      conversation_id: number;
      model?: string;
      query_trace?: any;
      user_query?: string;
    }) => void;
    /** 业务错误（后端 event: error） */
    onError?: (message: string) => void;
  }

  export interface BriefingResult {
    content: string;
    generated_at: string;
    model: string;
    notified_count: number;
    pushed: boolean;
    snapshot: Record<string, unknown>;
  }

  export interface NLFilterResult {
    dataset: string;
    dataset_label: string;
    dropped: string[];
    filters: Record<string, string>;
    keywords?: null | string;
    time_range?: null | {
      date_from?: null | string;
      date_to?: null | string;
      field: string;
    };
  }

  /** 页面 Copilot 支持的业务对象类型；服务端按类型重新读取并鉴权 */
  export type ContextObjectType =
    | 'delivery'
    | 'finance_reconciliation'
    | 'inventory_balance'
    | 'purchase_order'
    | 'purchase_request'
    | 'quality_acceptance'
    | 'rfq'
    | 'supplier';

  /** 已按当前用户权限读取的业务上下文 */
  export interface ContextSnapshot {
    object_id: null | number;
    object_type: ContextObjectType | 'purchase_order_list';
    reference_no?: null | string;
    source_records: Array<{
      dataset?: string;
      filters?: Record<string, number | string>;
      label?: string;
      record_id?: null | number;
    }>;
    status?: null | string;
    suggested_questions: string[];
    summary: string[];
    title: string;
  }

  export interface OrderTraceStage {
    records: Array<Record<string, any>>;
    stage: string;
    status: string;
    summary?: null | string;
    truncated?: boolean;
  }

  export interface OrderTrace {
    conclusion?: string[];
    order_status?: string;
    po_no?: string;
    stages?: OrderTraceStage[];
    supplier?: null | string;
    unavailable_stages?: string[];
  }

  /** 页面 Copilot 的确定性回答及来源 */
  export interface ContextAskResult {
    answer: string;
    citations: Array<{
      order_trace?: OrderTrace;
      po_no?: string;
      source_records?: ContextSnapshot['source_records'];
      type: string;
    }>;
    context: ContextSnapshot;
    model: string;
    provider: string;
  }

  export interface PurchaseDraftPreview {
    confirmation_id?: null | string;
    preview_version?: null | number;
    expires_at?: null | string;
    clarification_question?: null | string;
    missing_fields: string[];
    evidence: Array<{ label: string; tool: string; rows?: any[]; totals?: any[]; scope?: string; comparison_basis?: string; sources?: Array<{ resource: string; record_id: number; parent_id?: null | number }>; observed_at?: string }>;
    display_items: Array<{
      budget_price?: null | string;
      product_name?: null | string;
      quantity: string;
      requested_name: string;
      technical_requirements?: null | string;
      unit_name: string;
    }>;
    draft: import('../procurement/purchase-requests').PurchaseRequestApi.RequestPayload;
    requires_user_confirmation: boolean;
    warnings: string[];
  }

  export interface ActionProposalPreview {
    confirmation_id: string;
    action_type: string;
    resource_type?: null | string;
    resource_id?: null | string;
    preview_version: number;
    diff: Array<Record<string, unknown>>;
    evidence: Array<Record<string, unknown>>;
    warnings: string[];
    blockers: string[];
    risk_level: string;
    status: 'PENDING' | 'EXECUTED' | 'EXPIRED' | 'CANCELLED' | 'INVALIDATED';
    expires_at: string;
    requires_user_confirmation: boolean;
  }

  export interface ActionProposalRead extends ActionProposalPreview {
    availability: 'AVAILABLE' | 'PERMISSION_REVOKED' | 'RESOURCE_UNAVAILABLE';
    business_reference?: null | string;
    created_at: string;
    source_route?: null | string;
    unavailable_reason?: null | string;
    revision_values: Record<string, unknown>;
  }

  export interface ActionProposalPage {
    items: ActionProposalRead[];
    total: number;
  }
}

/** 生成运营晨报；推送时由调用方先向用户确认接收角色。 */
export async function generateBriefingApi(push = false) {
  return requestClient.post<AiApi.BriefingResult>('/ai/briefing', {
    notify_role_codes: ['SYS_ADMIN', 'PROCUREMENT_MANAGER'],
    push,
  });
}

/** 将自然语言解析为目标业务列表可检查的筛选条件，不执行查询。 */
export async function parseNaturalFiltersApi(dataset: string, question: string) {
  return requestClient.post<AiApi.NLFilterResult>('/ai/parse-filters', {
    dataset,
    question,
  });
}

/** 将明确需求整理成候选采购申请表单，不写入或提交业务单据。 */
export async function proposePurchaseRequestDraftApi(
  input: string | import('../procurement/purchase-requests').PurchaseRequestApi.RequestPayload,
  conversationId?: number,
) {
  const result = await requestClient.post<AiApi.PurchaseDraftPreview>(
    '/ai/purchase-request-draft/preview',
    { ...(typeof input === 'string' ? { question: input } : { draft: input }), conversation_id: conversationId },
  );
  if (result.confirmation_id) notifyNotificationChanged();
  return result;
}

export async function createActionProposalApi(actionType: string, payload: Record<string, unknown>, idempotencyKey: string) {
  const result = await requestClient.post<AiApi.ActionProposalPreview>('/ai/action-proposals', {
    action_type: actionType,
    idempotency_key: idempotencyKey,
    payload,
  });
  notifyNotificationChanged();
  return result;
}

export async function reviseActionProposalApi(confirmationId: string, previewVersion: number, payload: Record<string, unknown>) {
  return requestClient.request<AiApi.ActionProposalPreview>(`/ai/action-proposals/${encodeURIComponent(confirmationId)}`, {
    data: { confirmation_id: confirmationId, preview_version: previewVersion, payload },
    method: 'PATCH',
  });
}

export async function cancelActionProposalApi(confirmationId: string, previewVersion: number) {
  const result = await requestClient.post<{ cancelled: boolean }>(`/ai/action-proposals/${encodeURIComponent(confirmationId)}/cancel`, {
    confirmation_id: confirmationId,
    preview_version: previewVersion,
  });
  notifyNotificationChanged();
  return result;
}

export async function confirmActionProposalApi<T = Record<string, unknown>>(confirmationId: string, previewVersion: number) {
  const result = await requestClient.post<T>(`/ai/action-proposals/${encodeURIComponent(confirmationId)}/confirm`, {
    confirmation_id: confirmationId,
    preview_version: previewVersion,
    confirm: true,
  });
  notifyNotificationChanged();
  return result;
}

export async function getActionProposalPageApi(page: number, pageSize: number, inboxOnly = true) {
  return requestClient.get<AiApi.ActionProposalPage>('/ai/action-proposals', {
    params: { page, page_size: pageSize, inbox_only: inboxOnly },
  });
}

export async function getActionProposalApi(confirmationId: string) {
  return requestClient.get<AiApi.ActionProposalRead>(
    `/ai/action-proposals/${encodeURIComponent(confirmationId)}`,
  );
}

/** 确认指定预览快照；请求不接受客户端修改后的业务字段。 */
export async function confirmPurchaseRequestDraftApi(confirmationId: string, previewVersion: number) {
  return confirmActionProposalApi<import('../procurement/purchase-requests').PurchaseRequestApi.PurchaseRequest>(confirmationId, previewVersion);
}

/** 按当前页面对象提问；只提交对象引用，业务字段和权限由服务端重新读取。 */
export async function askPageContextApi(
  question: string,
  objectType: AiApi.ContextObjectType,
  objectId: number,
) {
  return requestClient.post<AiApi.ContextAskResult>('/ai/context/ask', {
    context: { object_id: objectId, object_type: objectType },
    question,
  });
}

/** 查询当前用户的 AI 会话列表 */
export async function getConversationListApi(limit = 50) {
  return requestClient.get<{ items: AiApi.Conversation[]; total: number }>(
    '/ai/conversations',
    { params: { limit } },
  );
}

/** 查询会话历史消息 */
export async function getAIMessagesApi(conversationId: number, limit = 100, beforeId?: number) {
  return requestClient.get<{ items: AiApi.Message[]; total: number }>(
    `/ai/conversations/${conversationId}/messages`,
    { params: { limit, before_id: beforeId } },
  );
}

/** 删除会话及其消息 */
export async function deleteConversationApi(conversationId: number) {
  return requestClient.delete<{ conversation_id: number; deleted: boolean }>(
    `/ai/conversations/${conversationId}`,
  );
}

/** 重命名或置顶当前用户的会话。 */
export async function updateConversationApi(
  conversationId: number,
  update: { pinned?: boolean; title?: string },
) {
  return requestClient.request<AiApi.Conversation>(
    `/ai/conversations/${conversationId}`,
    { data: update, method: 'PATCH' },
  );
}

/** 当前是否在流式提问中（用于禁用发送按钮） */
let streaming = false;

export function isAiStreaming() {
  return streaming;
}

/**
 * 流式对话。
 *
 * messages 为 OpenAI 兼容格式的历史（至少含一条 user），
 * conversation_id 为空时后端自动新建会话。
 */
export async function streamChatApi(
  messages: Array<{ content: string; role: 'assistant' | 'user' }>,
  conversationId: null | number,
  handlers: AiApi.StreamHandlers,
  routeToken?: string,
  options: { independent?: boolean; retryFailed?: boolean; signal?: AbortSignal } = {},
): Promise<void> {
  if (!options.independent && streaming) {
    throw new Error('上一条消息尚未回复完成');
  }
  if (!options.independent) streaming = true;
  const token = useAccessStore().accessToken;
  const base = import.meta.env.VITE_GLOB_API_URL || '/api/v1';
  try {
    const response = await fetch(`${base}/ai/chat/stream`, {
      body: JSON.stringify({
        conversation_id: conversationId ?? undefined,
        conversation_scene: options.independent ? 'FLOAT' : 'GENERAL',
        messages,
        route_token: routeToken,
        retry_failed: options.retryFailed ?? false,
      }),
      headers: {
        Accept: 'text/event-stream',
        Authorization: `Bearer ${token ?? ''}`,
        'Content-Type': 'application/json',
      },
      method: 'POST',
      signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(90_000)]) : AbortSignal.timeout(90_000),
    });
    if (response.status === 401) {
      const { useAuthStore } = await import('#/store');
      await useAuthStore().logout(false, false);
    }
    if (!response.ok || !response.body) {
      let message = `AI 请求失败（HTTP ${response.status}）`;
      try {
        const body = await response.json();
        message = body.detail ?? body.message ?? message;
      } catch {
        // 非 JSON 错误体，保留默认文案
      }
      handlers.onError?.(String(message));
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let terminal = false;
    const parse = createSseParser((eventName, dataText) => {
      let payload;
      try { payload = JSON.parse(dataText); } catch { return; }
      if (terminal) return;
      if (eventName === 'delta') handlers.onDelta?.(String(payload.content ?? ''));
      else if (eventName === 'done') { terminal = true; handlers.onDone?.(payload); }
      else if (eventName === 'error') { terminal = true; handlers.onError?.(String(payload.message ?? 'AI 服务错误')); }
      else if (eventName === 'progress') handlers.onProgress?.(payload);
    });
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) { parse(decoder.decode(), true); break; }
        parse(decoder.decode(value, { stream: true }));
      }
    } finally { reader.releaseLock(); }
    if (!terminal && !options.signal?.aborted) handlers.onError?.('响应连接已中断，请刷新会话核对已完成项。');
  } catch (error: any) {
    if (options.signal?.aborted) {
      handlers.onCancelled?.();
      return;
    }
    handlers.onError?.(
      error?.name === 'TimeoutError' ? '响应超时，请刷新会话核对结果后重试' : error?.message === 'Failed to fetch'
        ? '网络异常，请检查后端服务是否已启动'
        : String(error?.message ?? error),
    );
  } finally {
    if (!options.independent) streaming = false;
  }
}

/** 所有自然语言入口采用后端统一语义路由；不在浏览器猜业务意图。 */
export function routeAiRequestApi(question: string, conversationId?: number) {
  return requestClient.post<{ route: string; route_token: string; understanding: {
    action_fields?: Record<string, unknown> | null;
    slots: { request_no?: string | null };
  } }>('/ai/route', {
    question, conversation_id: conversationId,
  });
}
export interface OperationSuggestion {
  id: number;
  exception_id: number;
  exception_no: string;
  exception_status: string;
  title: string;
  content: string;
  instruction: string;
  status: 'OPEN' | 'IGNORED' | 'CLOSED' | 'HANDED_OFF';
  task_id: null | number;
  handled_by: null | number;
  handled_at: null | string;
  created_at: string;
}

export function getOperationSuggestionsApi(page: number, pageSize: number, status?: string) {
  return requestClient.get<{ items: OperationSuggestion[]; total: number }>('/ai/operation-suggestions', { params: { page, page_size: pageSize, status } });
}
export function getOperationSuggestionApi(id: number) {
  return requestClient.get<OperationSuggestion>(`/ai/operation-suggestions/${id}`);
}
export function handleOperationSuggestionApi(id: number, action: 'ignore' | 'close' | 'handoff') {
  return requestClient.post<OperationSuggestion>(`/ai/operation-suggestions/${id}/${action}`);
}

export interface PurchaseOrderListFilters { keyword?: string; status?: string }
export function askPurchaseOrderListContextApi(question: string, filters: PurchaseOrderListFilters) {
  return requestClient.post<AiApi.ContextAskResult>('/ai/context/purchase-orders', { question, filters });
}

/** 业务上下文通过 SSE 输出真实模型增量；来源在完成事件中返回。 */
export async function streamPageContextApi(
  question: string,
  target: { objectType: AiApi.ContextObjectType; objectId: number } | { filters: PurchaseOrderListFilters },
  handlers: { onDelta: (text: string) => void; onDone: (result: AiApi.ContextAskResult) => void },
  signal: AbortSignal,
  previousQuestions: string[] = [],
) {
  const token = useAccessStore().accessToken;
  const base = import.meta.env.VITE_GLOB_API_URL || '/api/v1';
  const isList = 'filters' in target;
  const response = await fetch(`${base}/ai/context/${isList ? 'purchase-orders/stream' : 'stream'}`, {
    method: 'POST',
    headers: { Accept: 'text/event-stream', Authorization: `Bearer ${token ?? ''}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(isList ? { question, previous_questions: previousQuestions, filters: target.filters } : { question, previous_questions: previousQuestions, context: { object_type: target.objectType, object_id: target.objectId } }),
    signal: AbortSignal.any([signal, AbortSignal.timeout(90_000)]),
  });
  if (!response.ok || !response.body) throw new Error(`上下文读取失败（HTTP ${response.status}）`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let terminal = false;
  let failure = '';
  const parse = createSseParser((event, raw) => {
    if (terminal) return;
    let payload: any;
    try { payload = JSON.parse(raw); } catch { return; }
    if (event === 'delta') handlers.onDelta(String(payload.content ?? ''));
    else if (event === 'done') { terminal = true; handlers.onDone(payload as AiApi.ContextAskResult); }
    else if (event === 'error') { terminal = true; failure = String(payload.message || '回答生成失败'); }
  });
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) { parse(decoder.decode(), true); break; }
      parse(decoder.decode(value, { stream: true }));
    }
  } finally { reader.releaseLock(); }
  if (failure) throw new Error(failure);
  if (!terminal && !signal.aborted) throw new Error('响应连接已中断，请重试。');
}
