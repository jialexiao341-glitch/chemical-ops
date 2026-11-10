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
    quote_id: number;
    supplier_id: number;
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
    tax_included: boolean | null;
    rank: null | number;
    comparison_status: 'COMPARABLE' | 'NOT_COMPARABLE';
    comparison_reasons: string[];
    quoted_quantity: string;
    moq_quantity: null | string;
    moq_unit_id: null | number;
    payment_terms: null | string;
    freight_amount: null | string;
    freight_tax_rate: null | string;
    freight_tax_included: boolean | null;
    cost_analysis: null | { complete: boolean; currency_code: string; goods_amount: null | string; goods_tax: null | string; freight_amount: null | string; freight_tax: null | string; total_cost: null | string; purchase_quantity: null | string; moq_extra_quantity: null | string; reasons: string[] };
    lead_days: null | number;
    quality_history?: null | { status: string; sample_count?: number; passed?: number; partial?: number; failed?: number; reason?: string };
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
        warehouse_id?: null | number;
        observed_at: string;
        scope: string;
        warnings: string[];
        totals: Array<{ available_quantity: string; unit_name: string; unit_id?: number }>;
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
        recommendation: null | {
          status: 'NO_RECOMMENDATION' | 'RECOMMENDED' | 'TIE';
          candidate_quote_id: null | number;
          candidate_supplier_id: null | number;
          currency_code: null | string;
          total_cost: null | string;
          reasons: string[];
          risks: string[];
        };
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
  export interface RunMeta {
    prompt_versions?: Record<string, string>;
    model?: {
      provider?: null | string;
      name?: null | string;
      usage?: null | Record<string, unknown>;
    };
    context?: {
      estimated_tokens?: null | number;
      max_tokens?: null | number;
      truncated_sections?: null | string[];
    };
    retries?: { llm?: null | number; tool?: null | number };
    error?: { code?: null | string; class?: null | string; recovery?: null | string };
  }
  export interface Task {
    can_select_all_products?: boolean;
    id: string;
    conversation_id?: null | number;
    status: 'CANCELLED' | 'FAILED' | 'RUNNING' | 'SUCCEEDED' | 'WAITING_INPUT';
    revision: number;
    reply: string;
    error_code: null | string;
    messages: string[];
    trace: Step[];
    run_meta?: RunMeta;
  }
  export interface Feedback {
    task_id: string;
    rating: 'DOWN' | 'UP';
    reason_code: null | string;
    comment: null | string;
    correction: null | string;
    prompt_version?: null | string;
    prompt_versions?: Record<string, string>;
    model_name?: null | string;
    created_at: string;
    updated_at: string;
  }
  export interface FeedbackSummary {
    days: number;
    total: number;
    up: number;
    down: number;
    by_reason: Record<string, number>;
    by_prompt_version: Record<string, number>;
  }
  export interface FeedbackAdminSummary extends FeedbackSummary {
    users: number;
    by_model: Record<string, number>;
  }
  export interface TaskPage {
    items: Task[];
    total: number;
    page: number;
    page_size: number;
  }
  export interface Continue {
    all_products?: boolean;
    route_token?: string;
    question: string;
    revision: number;
    product_id?: number;
    rfq_item_id?: number;
  }
  export interface CostAggregate {
    tasks: number;
    terminal_tasks: number;
    succeeded: number;
    success_rate: null | number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_cost: null | number;
    cost_tasks: number;
    cost_missing_tasks: number;
    partial_cost_tasks: number;
    p50_seconds: null | number;
    p95_seconds: null | number;
  }
  export interface CostGroup extends CostAggregate {
    scene?: string;
    model?: string;
    prompt_version?: string;
  }
  export interface CostSummary {
    generated_at: string;
    days: number;
    default_model: string;
    pricing: { configured: boolean; input_per_million: number; output_per_million: number };
    scope: string;
    summary: CostAggregate;
    by_scene: CostGroup[];
    by_model: CostGroup[];
    by_prompt_version: CostGroup[];
    coverage: {
      tasks: number;
      terminal_tasks: number;
      run_meta_usage: number;
      token_budget_only: number;
      unmetered: number;
      missing: number;
      calls: number;
      unmetered_calls: number;
      split_unavailable_calls: number;
      tasks_with_duration: number;
    };
    notes: string[];
  }
}

// 启动/续跑立即返回编号与状态，工作台通过 GET 更新进度。
export function createAgentTaskApi(question: string) {
  return requestClient.post<AgentApi.Task>('/ai/agent/tasks/start', { question });
}
export function getAgentTaskApi(id: string) {
  return requestClient.get<AgentApi.Task>(`/ai/agent/tasks/${encodeURIComponent(id)}`);
}
export function getAgentTaskPageApi(
  page: number,
  pageSize: number,
  status?: AgentApi.Task['status'],
  inboxOnly = false,
) {
  return requestClient.get<AgentApi.TaskPage>('/ai/agent/tasks', {
    params: { page, page_size: pageSize, status, inbox_only: inboxOnly },
  });
}
export function exportAgentTaskApi(id: string) {
  return requestClient.get<Blob>(`/ai/agent/tasks/${encodeURIComponent(id)}/export`, { responseType: 'blob' });
}
export function continueAgentTaskApi(id: string, data: AgentApi.Continue) {
  return requestClient.post<AgentApi.Task>(`/ai/agent/tasks/${encodeURIComponent(id)}/continue/start`, data);
}
export function cancelAgentTaskApi(id: string) {
  return requestClient.post<AgentApi.Task>(`/ai/agent/tasks/${encodeURIComponent(id)}/cancel`);
}

export function createAgentChatApi(question: string, conversationId?: number, routeToken?: string) {
  return requestClient.post<AgentApi.Task>('/ai/agent/chat/start', { question, conversation_id: conversationId, route_token: routeToken });
}
export function continueAgentChatApi(id: string, data: AgentApi.Continue) {
  return requestClient.post<AgentApi.Task>(`/ai/agent/chat/${encodeURIComponent(id)}/continue`, data);
}

export function submitAgentFeedbackApi(data: {
  task_id: string;
  rating: 'DOWN' | 'UP';
  reason_code?: string;
  comment?: string;
  correction?: string;
}) {
  return requestClient.post<AgentApi.Feedback>('/ai/feedback', data);
}
export function getAgentFeedbackApi(id: string) {
  return requestClient.get<AgentApi.Feedback | null>(`/ai/feedback/task/${encodeURIComponent(id)}`);
}
export function getAgentFeedbackSummaryApi(days = 7) {
  return requestClient.get<AgentApi.FeedbackSummary>('/ai/feedback/summary', { params: { days } });
}
export function getAgentFeedbackAdminSummaryApi(days = 7) {
  return requestClient.get<AgentApi.FeedbackAdminSummary>('/ai/feedback/summary/all', { params: { days } });
}
export function getAgentCostSummaryApi(days = 30) {
  return requestClient.get<AgentApi.CostSummary>('/ai/agent/cost-summary', { params: { days } });
}
