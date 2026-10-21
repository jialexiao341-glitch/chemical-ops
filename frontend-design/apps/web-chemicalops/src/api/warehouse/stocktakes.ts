import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace StocktakeApi {
  /** 盘点明细（账面数量由后端在创建时快照） */
  export interface StocktakeItem {
    batch_id: number;
    book_quantity: string;
    counted_quantity: string;
    difference_quantity: string;
    id: number;
    line_no: number;
    location_id: number;
    note?: null | string;
    product_id: number;
    status: string;
    stocktake_request_id: number;
    unit_id: number;
  }

  /** 库存盘点申请，对应后端 InventoryStocktakeRequestRead */
  export interface StocktakeRequest {
    applicant_id?: number;
    completed_at?: null | string;
    cancelled_at?: null | string;
    created_at?: string;
    id: number;
    items?: StocktakeItem[];
    approved_at?: null | string;
    approved_by?: null | number;
    location_id?: null | number;
    purpose: string;
    reject_reason?: null | string;
    rejected_at?: null | string;
    status: string;
    stocktake_no: string;
    updated_at?: string;
    warehouse_id: number;
  }

  export interface ItemPayload {
    batch_id: number;
    counted_quantity: number | string;
    location_id: number;
    note?: string;
    product_id: number;
    unit_id: number;
  }

  export interface Payload {
    items: ItemPayload[];
    location_id?: null | number;
    purpose: string;
    warehouse_id: number;
  }

  export interface ListParams extends PageQuery {
    status?: string;
  }
}

/** 分页查询库存盘点申请 */
export async function getStocktakeListApi(params?: StocktakeApi.ListParams, options?: { silent?: boolean }) {
  return requestClient.get<PageResult<StocktakeApi.StocktakeRequest>>(
    '/inventory/stocktakes',
    { ...options, params },
  );
}

/** 查询盘点申请详情（含明细与账实差） */
export async function getStocktakeApi(id: number) {
  return requestClient.get<StocktakeApi.StocktakeRequest>(
    `/inventory/stocktakes/${id}`,
  );
}

/** 创建盘点申请草稿（后端同时快照账面数量） */
export async function createStocktakeApi(data: StocktakeApi.Payload) {
  return requestClient.post<StocktakeApi.StocktakeRequest>(
    '/inventory/stocktakes',
    data,
  );
}

/** 修改草稿或已驳回的盘点申请 */
export async function updateStocktakeApi(
  id: number,
  data: Partial<StocktakeApi.Payload>,
) {
  return requestClient.request<StocktakeApi.StocktakeRequest>(
    `/inventory/stocktakes/${id}`,
    { data, method: 'PATCH' },
  );
}

/** 提交审批 */
export async function submitStocktakeApi(id: number) {
  return requestClient.post<StocktakeApi.StocktakeRequest>(
    `/inventory/stocktakes/${id}/submit`,
  );
}

/** 审批通过 */
export async function approveStocktakeApi(id: number) {
  return requestClient.post<StocktakeApi.StocktakeRequest>(
    `/inventory/stocktakes/${id}/approve`,
  );
}

/** 驳回（必须填原因） */
export async function rejectStocktakeApi(id: number, reason: string) {
  return requestClient.post<StocktakeApi.StocktakeRequest>(
    `/inventory/stocktakes/${id}/reject`,
    { reason },
  );
}

/** 取消（无请求体） */
export async function cancelStocktakeApi(id: number) {
  return requestClient.post<StocktakeApi.StocktakeRequest>(
    `/inventory/stocktakes/${id}/cancel`,
  );
}

/** 执行盘点差异调整（审批通过后） */
export async function executeStocktakeApi(id: number) {
  return requestClient.post<StocktakeApi.StocktakeRequest>(
    `/inventory/stocktakes/${id}/execute`,
  );
}
