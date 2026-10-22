import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace RfqApi {
  /** 询价明细 */
  export interface RfqItem {
    created_at?: string;
    id: number;
    product_id?: null | number;
    quantity: string;
    requested_name: string;
    required_delivery_date?: null | string;
    rfq_id?: number;
    source_request_item_id?: null | number;
    specification?: null | string;
    technical_requirements?: null | string;
    unit_id: number;
  }

  /** 被邀请的供应商 */
  export interface RfqSupplier {
    invited_at?: string;
    response_status?: string;
    rfq_id?: number;
    supplier_id: number;
  }

  /** 供应商报价明细 */
  export interface QuoteItem {
    id: number;
    lead_days?: null | number;
    freight_amount?: null | string;
    freight_tax_rate?: null | string;
    freight_tax_included?: boolean | null;
    moq_quantity?: null | string;
    moq_unit_id?: null | number;
    note?: null | string;
    payment_terms?: null | string;
    quoted_quantity: string;
    quote_id?: number;
    rfq_item_id: number;
    supplier_model?: null | string;
    supplier_product_id?: null | number;
    tax_rate?: null | string;
    tax_included?: boolean | null;
    unit_id: number;
    unit_price: string;
  }

  /** 供应商报价 */
  export interface SupplierQuote {
    created_at?: string;
    currency_code?: string;
    id: number;
    items?: QuoteItem[];
    note?: null | string;
    quote_date?: null | string;
    quote_no: string;
    quote_version?: number;
    received_by?: null | number;
    rfq_id?: number;
    source_file_id?: null | number;
    status: string;
    supplier_id: number;
    updated_at?: string;
    valid_until?: null | string;
  }

  /** 比价明细行 */
  export interface ComparisonItem {
    comparison_id?: number;
    composite_score?: null | string;
    historical_score?: null | string;
    id: number;
    lead_days?: null | number;
    moq_quantity?: null | string;
    note?: null | string;
    payment_terms?: null | string;
    quoted_unit_price: null | string;
    currency_code?: null | string;
    unit_id?: null | number;
    tax_rate?: null | string;
    tax_included?: boolean | null;
    comparison_status?: string;
    comparison_reasons?: null | string[];
    quote_id: number;
    rank_no?: null | number;
    rfq_item_id: number;
    selection_flag?: number;
    supplier_id: number;
    total_amount?: null | string;
    freight_amount?: null | string;
    freight_tax_rate?: null | string;
    freight_tax_included?: boolean | null;
    cost_analysis?: null | {
      complete: boolean;
      currency_code: string;
      freight_amount: null | string;
      freight_tax: null | string;
      goods_amount: null | string;
      goods_tax: null | string;
      purchase_quantity: null | string;
      total_cost: null | string;
      reasons: string[];
    };
    quality_history?: null | { status: string; sample_count?: number; passed?: number; partial?: number; failed?: number; reason?: string };
  }

  /** 比价单 */
  export interface QuoteComparison {
    comparison_no: string;
    conclusion?: null | string;
    confirmed_at?: null | string;
    confirmed_by?: null | number;
    created_at?: string;
    created_by?: number;
    decision_analysis?: null | {
      candidate_quote_id: null | number;
      candidate_supplier_id: null | number;
      currency_code: null | string;
      reasons: string[];
      risks: string[];
      status: 'NO_RECOMMENDATION' | 'RECOMMENDED' | 'TIE';
      total_cost: null | string;
    };
    id: number;
    items?: ComparisonItem[];
    rfq_id?: number;
    selected_quote_id?: null | number;
    selection_reason?: null | string;
    status: string;
    updated_at?: string;
  }

  /** 询价单，对应后端 RFQRead */
  export interface Rfq {
    closed_at?: null | string;
    comparisons?: QuoteComparison[];
    created_at?: string;
    delivery_requirements?: null | string;
    id: number;
    items?: RfqItem[];
    quote_deadline?: null | string;
    quotes?: SupplierQuote[];
    requested_delivery_date?: null | string;
    requester_id?: number;
    rfq_no: string;
    sent_at?: null | string;
    source_request_id?: null | number;
    status: string;
    suppliers?: RfqSupplier[];
    updated_at?: string;
  }

  export interface RfqItemPayload {
    product_id?: null | number;
    quantity: number | string;
    requested_name: string;
    required_delivery_date?: null | string;
    source_request_item_id?: null | number;
    specification?: null | string;
    technical_requirements?: null | string;
    unit_id: number;
  }

  export interface RfqPayload {
    delivery_requirements?: null | string;
    items: RfqItemPayload[];
    quote_deadline?: null | string;
    requested_delivery_date?: null | string;
    source_request_id?: null | number;
    supplier_ids: number[];
  }

  export interface QuoteItemPayload {
    lead_days?: null | number;
    freight_amount?: null | number | string;
    freight_tax_rate?: null | number | string;
    freight_tax_included?: boolean | null;
    moq_quantity?: null | number | string;
    moq_unit_id?: null | number;
    note?: null | string;
    payment_terms?: null | string;
    quoted_quantity: number | string;
    rfq_item_id: number;
    supplier_model?: null | string;
    supplier_product_id?: null | number;
    tax_rate?: null | number | string;
    tax_included?: boolean | null;
    unit_id: number;
    unit_price: number | string;
  }

  export interface QuotePayload {
    currency_code: string;
    items: QuoteItemPayload[];
    note?: null | string;
    quote_date?: null | string;
    source_file_id?: null | number;
    supplier_id: number;
    valid_until?: null | string;
  }

  export interface QuoteCandidateEvidence {
    field: string;
    source_location: string;
    source_quote: string;
    value: string;
  }

  export interface QuoteCandidateItem {
    lead_days?: null | number;
    freight_amount?: null | string;
    freight_tax_rate?: null | string;
    freight_tax_included?: boolean | null;
    moq_quantity?: null | string;
    moq_unit_name?: null | string;
    payment_terms?: null | string;
    product_label?: null | string;
    quoted_quantity?: null | string;
    rfq_item_id?: null | number;
    source_location: string;
    source_quote: string;
    supplier_model?: null | string;
    tax_rate?: null | string;
    tax_included?: boolean | null;
    unit_name?: null | string;
    unit_price?: null | string;
  }

  export interface QuoteParseCandidate {
    currency_code?: null | string;
    evidence: QuoteCandidateEvidence[];
    file_id: number;
    file_name: string;
    items: QuoteCandidateItem[];
    note?: null | string;
    quote_date?: null | string;
    supplier_name?: null | string;
    valid_until?: null | string;
    warnings: string[];
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }
}

/** 分页查询询价单 */
export async function getRfqListApi(params?: RfqApi.ListParams) {
  return requestClient.get<PageResult<RfqApi.Rfq>>('/rfqs', { params });
}

/** 查询询价详情（含明细、受邀供应商、报价与比价） */
export async function getRfqApi(id: number) {
  return requestClient.get<RfqApi.Rfq>(`/rfqs/${id}`);
}

/** 创建询价单草稿 */
export async function createRfqApi(data: RfqApi.RfqPayload) {
  return requestClient.post<RfqApi.Rfq>('/rfqs', data);
}

/** 更新询价单草稿 */
export async function updateRfqApi(id: number, data: Partial<RfqApi.RfqPayload>) {
  return requestClient.request<RfqApi.Rfq>(`/rfqs/${id}`, { data, method: 'PATCH' });
}

/** 发送询价单 */
export async function sendRfqApi(id: number) {
  return requestClient.post<RfqApi.Rfq>(`/rfqs/${id}/send`);
}

/** 录入供应商报价 */
export async function createQuoteApi(id: number, data: RfqApi.QuotePayload) {
  return requestClient.post<RfqApi.Rfq>(`/rfqs/${id}/quotes`, data);
}

/** 将询价报价文件解析为待人工复核的候选值。 */
export async function parseQuoteFileApi(id: number, file: File) {
  const data = new FormData();
  data.append('file', file);
  return requestClient.post<RfqApi.QuoteParseCandidate>(
    `/rfqs/${id}/quotes/parse-file`,
    data,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  );
}

/** 生成报价比较快照 */
export async function buildComparisonApi(id: number) {
  return requestClient.post<RfqApi.QuoteComparison>(
    `/rfqs/${id}/comparison`,
  );
}

/** 查询最近一次比价结果 */
export async function getComparisonApi(id: number) {
  return requestClient.get<RfqApi.QuoteComparison>(`/rfqs/${id}/comparison`);
}

/** 确认中选报价 */
export async function selectQuoteApi(
  id: number,
  data: { comparison_id: number; quote_id: number; selection_reason: string },
) {
  return requestClient.post<RfqApi.Rfq>(`/rfqs/${id}/select-quote`, data);
}
