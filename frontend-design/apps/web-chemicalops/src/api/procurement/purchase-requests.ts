import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace PurchaseRequestApi {
  /** 采购申请明细 */
  export interface RequestItem {
    budget_price?: null | string;
    created_at?: string;
    expected_date?: null | string;
    fulfilled_quantity?: string;
    id?: number;
    line_no?: number;
    product_id?: null | number;
    quantity: string;
    request_id?: number;
    requested_name: string;
    status?: string;
    technical_requirements?: null | string;
    unit_id: number;
    updated_at?: string;
  }

  /** 审批记录 */
  export interface Approval {
    acted_at?: null | string;
    action?: null | string;
    approver_id?: null | number;
    created_at?: string;
    id: number;
    node_code?: string;
    node_name?: string;
    opinion?: null | string;
    request_id?: number;
    sequence_no?: number;
  }

  /** 采购申请，对应后端 PurchaseRequestRead */
  export interface PurchaseRequest {
    applicant_id?: number;
    approved_at?: null | string;
    approvals?: Approval[];
    budget_amount?: null | string;
    cancel_reason?: null | string;
    cancelled_at?: null | string;
    created_at?: string;
    currency_code?: string;
    department_id?: null | number;
    expected_date?: null | string;
    id: number;
    items?: RequestItem[];
    priority: string;
    purpose: string;
    rejected_at?: null | string;
    request_no?: string;
    status: string;
    submitted_at?: null | string;
    updated_at?: string;
  }

  export interface ItemPayload {
    budget_price?: null | number | string;
    expected_date?: null | string;
    product_id?: null | number;
    quantity: number | string;
    requested_name: string;
    technical_requirements?: null | string;
    unit_id: number;
  }

  export interface RequestPayload {
    budget_amount?: null | number | string;
    currency_code?: string;
    department_id?: null | number;
    expected_date?: null | string;
    items: ItemPayload[];
    priority?: string;
    purpose: string;
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }
}

/** 分页查询采购申请 */
export async function getPurchaseRequestListApi(
  params?: PurchaseRequestApi.ListParams,
) {
  return requestClient.get<
    PageResult<PurchaseRequestApi.PurchaseRequest>
  >('/purchase-requests', { params });
}

/** 查询采购申请详情（含明细与审批记录） */
export async function getPurchaseRequestApi(id: number) {
  return requestClient.get<PurchaseRequestApi.PurchaseRequest>(
    `/purchase-requests/${id}`,
  );
}

/** 创建采购申请草稿 */
export async function createPurchaseRequestApi(
  data: PurchaseRequestApi.RequestPayload,
) {
  return requestClient.post<PurchaseRequestApi.PurchaseRequest>(
    '/purchase-requests',
    data,
  );
}

/** 更新采购申请草稿 */
export async function updatePurchaseRequestApi(
  id: number,
  data: Partial<PurchaseRequestApi.RequestPayload>,
) {
  return requestClient.request<PurchaseRequestApi.PurchaseRequest>(`/purchase-requests/${id}`, { data, method: 'PATCH' });
}

/** 提交采购申请 */
export async function submitPurchaseRequestApi(id: number) {
  return requestClient.post<PurchaseRequestApi.PurchaseRequest>(
    `/purchase-requests/${id}/submit`,
  );
}

/** 审批通过 */
export async function approvePurchaseRequestApi(
  id: number,
  opinion?: string,
) {
  return requestClient.post<PurchaseRequestApi.PurchaseRequest>(
    `/purchase-requests/${id}/approve`,
    { opinion },
  );
}

/** 驳回 */
export async function rejectPurchaseRequestApi(id: number, opinion?: string) {
  return requestClient.post<PurchaseRequestApi.PurchaseRequest>(
    `/purchase-requests/${id}/reject`,
    { opinion },
  );
}

/** 取消采购申请 */
export async function cancelPurchaseRequestApi(id: number, reason: string) {
  return requestClient.post<PurchaseRequestApi.PurchaseRequest>(
    `/purchase-requests/${id}/cancel`,
    { reason },
  );
}
