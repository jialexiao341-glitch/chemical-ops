import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace TransferRequestApi {
  /** 调拨明细 */
  export interface TransferItem {
    batch_id: number;
    id: number;
    line_no: number;
    note?: null | string;
    product_id: number;
    requested_quantity: string;
    source_location_id: number;
    source_warehouse_id: number;
    status: string;
    target_location_id: number;
    target_warehouse_id: number;
    transferred_quantity: string;
    unit_id: number;
  }

  /** 库存调拨申请，对应后端 InventoryTransferRequestRead */
  export interface TransferRequest {
    applicant_id?: number;
    completed_at?: null | string;
    cancelled_at?: null | string;
    created_at?: string;
    id: number;
    items?: TransferItem[];
    approved_at?: null | string;
    approved_by?: null | number;
    purpose: string;
    reject_reason?: null | string;
    rejected_at?: null | string;
    status: string;
    transfer_no: string;
    updated_at?: string;
  }

  export interface ItemPayload {
    batch_id: number;
    note?: string;
    product_id: number;
    requested_quantity: number | string;
    source_location_id: number;
    source_warehouse_id: number;
    target_location_id: number;
    target_warehouse_id: number;
    unit_id: number;
  }

  export interface Payload {
    items: ItemPayload[];
    purpose: string;
  }

  export interface ListParams extends PageQuery {
    status?: string;
  }
}

/** 分页查询库存调拨申请 */
export async function getTransferListApi(
  params?: TransferRequestApi.ListParams,
) {
  return requestClient.get<PageResult<TransferRequestApi.TransferRequest>>(
    '/inventory/transfer-requests',
    { params },
  );
}

/** 查询调拨申请详情（含明细） */
export async function getTransferApi(id: number) {
  return requestClient.get<TransferRequestApi.TransferRequest>(
    `/inventory/transfer-requests/${id}`,
  );
}

/** 创建调拨申请草稿 */
export async function createTransferApi(data: TransferRequestApi.Payload) {
  return requestClient.post<TransferRequestApi.TransferRequest>(
    '/inventory/transfer-requests',
    data,
  );
}

/** 修改草稿或已驳回的调拨申请 */
export async function updateTransferApi(
  id: number,
  data: Partial<TransferRequestApi.Payload>,
) {
  return requestClient.request<TransferRequestApi.TransferRequest>(
    `/inventory/transfer-requests/${id}`,
    { data, method: 'PATCH' },
  );
}

/** 提交审批 */
export async function submitTransferApi(id: number) {
  return requestClient.post<TransferRequestApi.TransferRequest>(
    `/inventory/transfer-requests/${id}/submit`,
  );
}

/** 审批通过 */
export async function approveTransferApi(id: number) {
  return requestClient.post<TransferRequestApi.TransferRequest>(
    `/inventory/transfer-requests/${id}/approve`,
  );
}

/** 驳回（必须填原因） */
export async function rejectTransferApi(id: number, reason: string) {
  return requestClient.post<TransferRequestApi.TransferRequest>(
    `/inventory/transfer-requests/${id}/reject`,
    { reason },
  );
}

/** 取消（无请求体） */
export async function cancelTransferApi(id: number) {
  return requestClient.post<TransferRequestApi.TransferRequest>(
    `/inventory/transfer-requests/${id}/cancel`,
  );
}

/** 执行调拨（审批通过后） */
export async function executeTransferApi(id: number) {
  return requestClient.post<TransferRequestApi.TransferRequest>(
    `/inventory/transfer-requests/${id}/execute`,
  );
}
