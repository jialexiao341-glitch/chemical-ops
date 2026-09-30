import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace FinanceApi {
  /** 财务对账单，对应后端 ReconciliationRead */
  export interface Reconciliation {
    cancelled_at?: null | string;
    cancel_reason?: null | string;
    closed_at?: null | string;
    confirmed_at?: null | string;
    confirmed_by?: null | number;
    created_at: string;
    created_by: number;
    currency_code: string;
    id: number;
    items_version: number;
    amount_precision: number;
    note?: null | string;
    po_id: number;
    reconciliation_no: string;
    status: string;
    supplier_id: number;
    total_amount: string;
    updated_at: string;
  }

  export interface ReconciliationCreatePayload {
    note?: string;
    po_id: number;
  }

  /** 发票，对应后端 InvoiceRead */
  export interface Invoice {
    amount_excl_tax: string;
    amount_incl_tax: string;
    created_at: string;
    currency_code: string;
    id: number;
    invoice_code?: null | string;
    invoice_date: string;
    invoice_no: string;
    invoice_number: string;
    note?: null | string;
    po_id: number;
    reconciliation_id: number;
    reject_reason?: null | string;
    source_file_id?: null | number;
    status: string;
    submitted_by: number;
    supplier_id: number | string;
    tax_amount: string;
    updated_at: string;
    verified_at?: null | string;
    verified_by?: null | number;
  }

  export interface InvoiceCreatePayload {
    amount_excl_tax: number | string;
    amount_incl_tax: number | string;
    invoice_code?: string;
    invoice_date: string;
    invoice_number: string;
    note?: string;
    reconciliation_id: number;
    tax_amount?: number | string;
  }

  /** 付款记录，对应后端 PaymentRead */
  export interface Payment {
    approved_at?: null | string;
    approved_by?: null | number;
    amount: string;
    created_at: string;
    currency_code: string;
    id: number;
    note?: null | string;
    paid_at?: null | string;
    paid_by?: null | number;
    payment_method: string;
    payment_no: string;
    po_id: number;
    reconciliation_id: number;
    reject_reason?: null | string;
    requested_by: number;
    status: string;
    supplier_id: number;
    transaction_ref?: null | string;
    updated_at: string;
  }

  export interface PaymentCreatePayload {
    amount: number | string;
    note?: string;
    payment_method: string;
    reconciliation_id: number;
  }

  export interface PaymentPaidPayload {
    note?: string;
    transaction_ref: string;
  }

  /** 结算单，对应后端 SettlementRead */
  export interface Settlement {
    cancel_reason?: null | string;
    cancelled_at?: null | string;
    confirmed_at?: null | string;
    confirmed_by?: null | number;
    created_at: string;
    created_by: number;
    currency_code: string;
    id: number;
    note?: null | string;
    po_id: number;
    reconciliation_id: number;
    settlement_amount: string;
    settlement_no: string;
    status: string;
    supplier_id: number;
    updated_at: string;
  }

  export interface SettlementCreatePayload {
    note?: string;
    reconciliation_id: number;
  }

  export interface ListParams extends PageQuery {
    reconciliation_id?: number;
    status?: string;
    supplier_id?: number;
  }
}

export interface ReconciliationItem {
  id: number;
  po_item_id: number;
  line_no: number;
  product_name: string;
  unit_name: string;
  ordered_quantity: string;
  received_quantity: string;
  accepted_quantity: string;
  returned_quantity: string;
  reconciliation_quantity: string;
  unit_price: string;
  tax_rate: string;
  amount_excl_tax: string;
  tax_amount: string;
  amount_incl_tax: string;
  return_treatment: string;
  treatment_note: null | string;
  warnings: string[];
  basis_json: {
    receipts: { delivery_no: string; quantity: string; status: string }[];
    returns: { return_no: string; returned_quantity: string; status: string }[];
  };
}

export interface ReconciliationItems {
  reconciliation_id: number;
  version_no: number;
  available_versions: number[];
  amount_precision: number;
  currency_code: string;
  total_amount: string;
  source_changed: boolean;
  warnings: string[];
  items: ReconciliationItem[];
}

export function getReconciliationItemsApi(id: number, version?: number) {
  return requestClient.get<ReconciliationItems>(`/finance/reconciliations/${id}/items`, { params: { version } });
}

export function refreshReconciliationItemsApi(id: number, data: {
  amount_precision: number;
  decisions: { po_item_id: number; return_treatment: string; treatment_note?: string }[];
}) {
  return requestClient.post<ReconciliationItems>(`/finance/reconciliations/${id}/items/refresh`, data);
}

export interface InvoiceMatchAllocation {
  reconciliation_item_id: number;
  amount_excl_tax: string;
  tax_amount: string;
  difference_note?: null | string;
  product_name?: string;
  line_no?: number;
}

export interface InvoiceMatches {
  invoice_id: number;
  reconciliation_version: number;
  source_changed: boolean;
  legacy: boolean;
  warnings: string[];
  items: {
    reconciliation_item_id: number;
    line_no: number;
    product_name: string;
    amount_incl_tax: string;
    remaining_amount: string;
    verified_amount: string;
  }[];
  versions: {
    id: number;
    version_no: number;
    reconciliation_version: number;
    allocations: InvoiceMatchAllocation[];
    note: null | string;
    created_by: number;
    created_at: string;
  }[];
}

export function getInvoiceMatchesApi(id: number) {
  return requestClient.get<InvoiceMatches>(`/finance/invoices/${id}/matches`);
}

export function saveInvoiceMatchesApi(id: number, data: {
  reconciliation_version: number;
  allocations: InvoiceMatchAllocation[];
  note?: string;
}) {
  return requestClient.post<InvoiceMatches>(`/finance/invoices/${id}/matches`, data);
}

export function voidInvoiceApi(id: number, reason: string) {
  return requestClient.post<FinanceApi.Invoice>(`/finance/invoices/${id}/void`, { reason });
}

// ---------- 财务对账 ----------

/** 分页查询财务对账单 */
export async function getReconciliationListApi(
  params?: FinanceApi.ListParams,
) {
  return requestClient.get<PageResult<FinanceApi.Reconciliation>>(
    '/finance/reconciliations',
    { params },
  );
}

/** 查询财务对账单详情 */
export async function getReconciliationApi(id: number) {
  return requestClient.get<FinanceApi.Reconciliation>(
    `/finance/reconciliations/${id}`,
  );
}

/** 创建财务对账单（只有收货与质量验收全部完成的订单可建） */
export async function createReconciliationApi(
  data: FinanceApi.ReconciliationCreatePayload,
) {
  return requestClient.post<FinanceApi.Reconciliation>(
    '/finance/reconciliations',
    data,
  );
}

/** 确认财务对账单（DRAFT/DISPUTED → CONFIRMED） */
export async function confirmReconciliationApi(
  id: number,
  reason?: string,
) {
  return requestClient.post<FinanceApi.Reconciliation>(
    `/finance/reconciliations/${id}/confirm`,
    { reason: reason ?? null },
  );
}

/** 发起财务对账争议（DRAFT/CONFIRMED → DISPUTED，原因必填） */
export async function disputeReconciliationApi(id: number, reason: string) {
  return requestClient.post<FinanceApi.Reconciliation>(
    `/finance/reconciliations/${id}/dispute`,
    { reason },
  );
}

// ---------- 供应商发票 ----------

/** 分页查询供应商发票 */
export async function getInvoiceListApi(params?: FinanceApi.ListParams) {
  return requestClient.get<PageResult<FinanceApi.Invoice>>(
    '/finance/invoices',
    { params },
  );
}

/** 查询供应商发票详情 */
export async function getInvoiceApi(id: number) {
  return requestClient.get<FinanceApi.Invoice>(`/finance/invoices/${id}`);
}

/** 录入供应商发票（价税合计 = 不含税 + 税额） */
export async function createInvoiceApi(data: FinanceApi.InvoiceCreatePayload) {
  return requestClient.post<FinanceApi.Invoice>(
    '/finance/invoices',
    data,
  );
}

/** 提交发票核验（DRAFT/REJECTED → SUBMITTED） */
export async function submitInvoiceApi(id: number) {
  return requestClient.post<FinanceApi.Invoice>(
    `/finance/invoices/${id}/submit`,
  );
}

/** 人工复核发票（SUBMITTED → VERIFIED；不代表税务平台验真） */
export async function verifyInvoiceApi(id: number) {
  return requestClient.post<FinanceApi.Invoice>(
    `/finance/invoices/${id}/verify`,
  );
}

/** 驳回发票（SUBMITTED → REJECTED，原因必填） */
export async function rejectInvoiceApi(id: number, reason: string) {
  return requestClient.post<FinanceApi.Invoice>(
    `/finance/invoices/${id}/reject`,
    { reason },
  );
}

// ---------- 付款 ----------

/** 分页查询付款记录 */
export async function getPaymentListApi(params?: FinanceApi.ListParams) {
  return requestClient.get<PageResult<FinanceApi.Payment>>(
    '/finance/payments',
    { params },
  );
}

/** 查询付款详情 */
export async function getPaymentApi(id: number) {
  return requestClient.get<FinanceApi.Payment>(`/finance/payments/${id}`);
}

/** 发起付款申请（仅 CONFIRMED 对账单，REQUESTED） */
export async function createPaymentApi(
  data: FinanceApi.PaymentCreatePayload,
) {
  return requestClient.post<FinanceApi.Payment>('/finance/payments', data);
}

/** 审批付款申请（REQUESTED → APPROVED，需 payments.approve 权限） */
export async function approvePaymentApi(id: number) {
  return requestClient.post<FinanceApi.Payment>(
    `/finance/payments/${id}/approve`,
  );
}

/** 驳回付款申请（REQUESTED → REJECTED，原因必填） */
export async function rejectPaymentApi(id: number, reason: string) {
  return requestClient.post<FinanceApi.Payment>(
    `/finance/payments/${id}/reject`,
    { reason },
  );
}

/** 登记人工核对的付款结果（APPROVED → PAID；不代表银行回执） */
export async function markPaymentPaidApi(
  id: number,
  data: FinanceApi.PaymentPaidPayload,
) {
  return requestClient.post<FinanceApi.Payment>(
    `/finance/payments/${id}/paid`,
    data,
  );
}

// ---------- 采购结算 ----------

/** 分页查询采购结算单 */
export async function getSettlementListApi(params?: FinanceApi.ListParams) {
  return requestClient.get<PageResult<FinanceApi.Settlement>>(
    '/finance/settlements',
    { params },
  );
}

/** 查询采购结算详情 */
export async function getSettlementApi(id: number) {
  return requestClient.get<FinanceApi.Settlement>(`/finance/settlements/${id}`);
}

/** 创建采购结算单（仅已确认且足额付款的对账单） */
export async function createSettlementApi(
  data: FinanceApi.SettlementCreatePayload,
) {
  return requestClient.post<FinanceApi.Settlement>(
    '/finance/settlements',
    data,
  );
}

/** 确认结算单（DRAFT → CONFIRMED，同时关闭对账单，需 settlements.approve） */
export async function confirmSettlementApi(id: number) {
  return requestClient.post<FinanceApi.Settlement>(
    `/finance/settlements/${id}/confirm`,
  );
}

/** 取消结算单（DRAFT → CANCELLED，原因必填） */
export async function cancelSettlementApi(id: number, reason: string) {
  return requestClient.post<FinanceApi.Settlement>(
    `/finance/settlements/${id}/cancel`,
    { reason },
  );
}
