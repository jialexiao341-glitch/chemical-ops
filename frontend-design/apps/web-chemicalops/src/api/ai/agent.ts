import { requestClient } from '#/api/request';

export namespace AgentApi {
  export interface Source {
    resource: string;
    record_id: number;
    parent_id?: null | number;
  }
  export interface Product {
    product_id: number;
    product_code: string;
    product_name: string;
    model: null | string;
    packaging_spec: null | string;
    unit_name: string;
  }
  export interface RfqItem {
    rfq_item_id: number;
    rfq_id: number;
    rfq_no: string;
    specification: null | string;
    technical_requirements: null | string;
  }
  export interface InventoryRow {
    balance_id: number;
    warehouse_id: number;
    warehouse_name: string;
    batch_no: string;
    expiry_date: null | string;
    available_quantity: string;
    unit_name: string;
    status: string;
  }
  export interface Quote {
    quote_item_id: number;
    quote_no: string;
    quote_version: number;
    quote_date: string;
    valid_until: null | string;
    supplier_name: string;
    supplier_model: null | string;
    currency_code: string;
    unit_price: string;
    unit_name: string;
    tax_rate: null | string;
    rank: null | number;
    quoted_quantity: string;
    moq_quantity: null | string;
    lead_days: null | number;
  }
  interface ResultBase {
    total_rows: number;
    truncated: boolean;
    sources: Source[];
  }
  export type Result =
    | (ResultBase & { tool: 'catalog.search_products'; rows: Product[] })
    | (ResultBase & { tool: 'supplier_quotes.find_rfq_items'; rows: RfqItem[] })
    | (ResultBase & {
        tool: 'inventory.query_available';
        product_id: number;
        product_name: string;
        observed_at: string;
        scope: string;
        warnings: string[];
        totals: Array<{ available_quantity: string; unit_name: string }>;
        rows: InventoryRow[];
      })
    | (ResultBase & {
        tool: 'supplier_quotes.compare';
        rfq_id: number;
        rfq_no: string;
        observed_at: string;
        scope: string;
        comparison_basis: string;
        specification: null | string;
        technical_requirements: null | string;
        warnings: string[];
        rows: Quote[];
      });
  export interface Step {
    step: number;
    action: string;
    status: string;
    tool?: string;
    question?: string;
    error_code?: string;
    result?: Result;
    arguments?: Record<string, unknown>;
    evidence_steps?: number[];
  }
  export interface Task {
    id: string;
    conversation_id?: null | number;
    status: 'CANCELLED' | 'FAILED' | 'RUNNING' | 'SUCCEEDED' | 'WAITING_INPUT';
    revision: number;
    reply: string;
    error_code: null | string;
    messages: string[];
    trace: Step[];
  }
  export interface Continue {
    question: string;
    revision: number;
    product_id?: number;
    rfq_item_id?: number;
  }
}

// 启动/续跑立即返回编号与状态，工作台通过 GET 更新进度。
export function createAgentTaskApi(question: string) {
  return requestClient.post<AgentApi.Task>('/ai/agent/tasks/start', { question });
}
export function getAgentTaskApi(id: string) {
  return requestClient.get<AgentApi.Task>(`/ai/agent/tasks/${encodeURIComponent(id)}`);
}
export function continueAgentTaskApi(id: string, data: AgentApi.Continue) {
  return requestClient.post<AgentApi.Task>(`/ai/agent/tasks/${encodeURIComponent(id)}/continue/start`, data);
}
export function cancelAgentTaskApi(id: string) {
  return requestClient.post<AgentApi.Task>(`/ai/agent/tasks/${encodeURIComponent(id)}/cancel`);
}

export function createAgentChatApi(question: string, conversationId?: number) {
  return requestClient.post<AgentApi.Task>('/ai/agent/chat/start', { question, conversation_id: conversationId });
}
export function continueAgentChatApi(id: string, data: AgentApi.Continue) {
  return requestClient.post<AgentApi.Task>(`/ai/agent/chat/${encodeURIComponent(id)}/continue`, data);
}
