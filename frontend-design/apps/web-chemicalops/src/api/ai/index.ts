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

export * from './agent';

export namespace AiApi {
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

  export interface PurchaseDraftPreview {
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
export async function proposePurchaseRequestDraftApi(question: string) {
  return requestClient.post<AiApi.PurchaseDraftPreview>(
    '/ai/purchase-request-draft/preview',
    { question },
  );
}

/** 查询当前用户的 AI 会话列表 */
export async function getConversationListApi(limit = 50) {
  return requestClient.get<{ items: AiApi.Conversation[]; total: number }>(
    '/ai/conversations',
    { params: { limit } },
  );
}

/** 查询会话历史消息 */
export async function getAIMessagesApi(conversationId: number, limit = 100) {
  return requestClient.get<{ items: AiApi.Message[]; total: number }>(
    `/ai/conversations/${conversationId}/messages`,
    { params: { limit } },
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
): Promise<void> {
  if (streaming) {
    throw new Error('上一条消息尚未回复完成');
  }
  streaming = true;
  const token = useAccessStore().accessToken;
  const base = import.meta.env.VITE_GLOB_API_URL || '/api/v1';
  try {
    const response = await fetch(`${base}/ai/chat/stream`, {
      body: JSON.stringify({
        conversation_id: conversationId ?? undefined,
        messages,
      }),
      headers: {
        Accept: 'text/event-stream',
        Authorization: `Bearer ${token ?? ''}`,
        'Content-Type': 'application/json',
      },
      method: 'POST',
    });
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
    let buffer = '';
    // 完整事件按 "\n\n" 切分，字段行以 "event:" / "data:" 开头
    let eventName = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let sepIndex = buffer.indexOf('\n\n');
      while (sepIndex !== -1) {
        const rawEvent = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);
        let dataText = '';
        for (const line of rawEvent.split('\n')) {
          if (line.startsWith('event:')) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            dataText = line.slice(5).trim();
          }
        }
        if (!dataText) {
          sepIndex = buffer.indexOf('\n\n');
          continue;
        }
        try {
          const payload = JSON.parse(dataText);
          if (eventName === 'delta') {
            handlers.onDelta?.(String(payload.content ?? ''));
          } else if (eventName === 'done') {
            handlers.onDone?.(payload);
          } else if (eventName === 'error') {
            handlers.onError?.(String(payload.message ?? 'AI 服务错误'));
          }
        } catch {
          // 单帧解析失败不中断整个流
        }
        eventName = '';
        sepIndex = buffer.indexOf('\n\n');
      }
    }
  } catch (error: any) {
    handlers.onError?.(
      error?.message === 'Failed to fetch'
        ? '网络异常，请检查后端服务是否已启动'
        : String(error?.message ?? error),
    );
  } finally {
    streaming = false;
  }
}
