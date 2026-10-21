import type { PageQuery, PageResult } from '#/api/request';

import { fetchAllListPages } from '#/utils/pagination';
import { requestClient } from '#/api/request';

export namespace IssueRequestApi {
  export interface StockOption {
    available_quantity: string;
    batch_id: number;
    batch_no: string;
    id: number;
    location_id: number;
    location_name: string;
    product_id: number;
    product_name: string;
    unit_id: number;
    unit_name: string;
    warehouse_id: number;
    warehouse_name: string;
  }
  /** 领用明细 */
  export interface IssueItem {
    batch_id: number;
    id: number;
    issued_quantity: string;
    line_no: number;
    location_id: number;
    note?: null | string;
    product_id: number;
    requested_quantity: string;
    status: string;
    unit_id: number;
    warehouse_id: number;
  }

  /** 库存领用申请，对应后端 InventoryIssueRequestRead */
  export interface IssueRequest {
    applicant_id?: number;
    completed_at?: null | string;
    cancelled_at?: null | string;
    created_at?: string;
    department_id?: null | number;
    id: number;
    issue_no: string;
    items?: IssueItem[];
    approved_at?: null | string;
    approved_by?: null | number;
    purpose: string;
    reject_reason?: null | string;
    rejected_at?: null | string;
    status: string;
    updated_at?: string;
  }

  export interface ItemPayload {
    batch_id: number;
    location_id: number;
    note?: string;
    product_id: number;
    requested_quantity: number | string;
    unit_id: number;
    warehouse_id: number;
  }

  export interface Payload {
    department_id?: null | number;
    items: ItemPayload[];
    purpose: string;
  }

  export interface ListParams extends PageQuery {
    status?: string;
  }
}

/** 获取创建领用申请所需的最小可用库存选项 */
export async function getIssueOptionsApi() {
  return fetchAllListPages((page) => requestClient.get<IssueRequestApi.StockOption[]>(
    '/inventory/issue-request-options', { params: { page, page_size: 100 } },
  ));
}

/** 分页查询库存领用申请 */
export async function getIssueListApi(params?: IssueRequestApi.ListParams, options?: { silent?: boolean }) {
  return requestClient.get<PageResult<IssueRequestApi.IssueRequest>>(
    '/inventory/issue-requests',
    { ...options, params },
  );
}

/** 查询领用申请详情（含明细） */
export async function getIssueApi(id: number) {
  return requestClient.get<IssueRequestApi.IssueRequest>(
    `/inventory/issue-requests/${id}`,
  );
}

/** 创建领用申请草稿 */
export async function createIssueApi(data: IssueRequestApi.Payload) {
  return requestClient.post<IssueRequestApi.IssueRequest>(
    '/inventory/issue-requests',
    data,
  );
}

/** 修改草稿或已驳回的领用申请 */
export async function updateIssueApi(
  id: number,
  data: Partial<IssueRequestApi.Payload>,
) {
  return requestClient.request<IssueRequestApi.IssueRequest>(
    `/inventory/issue-requests/${id}`,
    { data, method: 'PATCH' },
  );
}

/** 提交审批 */
export async function submitIssueApi(id: number) {
  return requestClient.post<IssueRequestApi.IssueRequest>(
    `/inventory/issue-requests/${id}/submit`,
  );
}

/** 审批通过 */
export async function approveIssueApi(id: number) {
  return requestClient.post<IssueRequestApi.IssueRequest>(
    `/inventory/issue-requests/${id}/approve`,
  );
}

/** 驳回（必须填原因） */
export async function rejectIssueApi(id: number, reason: string) {
  return requestClient.post<IssueRequestApi.IssueRequest>(
    `/inventory/issue-requests/${id}/reject`,
    { reason },
  );
}

/** 取消（无请求体） */
export async function cancelIssueApi(id: number) {
  return requestClient.post<IssueRequestApi.IssueRequest>(
    `/inventory/issue-requests/${id}/cancel`,
  );
}

/** 执行出库（审批通过后） */
export async function executeIssueApi(id: number) {
  return requestClient.post<IssueRequestApi.IssueRequest>(
    `/inventory/issue-requests/${id}/execute`,
  );
}
