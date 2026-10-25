import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace ReplenishmentApi {
  /** 补货明细 */
  export interface Item {
    created_at?: string;
    expected_date?: null | string;
    id: number;
    line_no: number;
    note?: null | string;
    product_code?: null | string;
    product_id: number;
    product_name?: null | string;
    requested_quantity: string;
    status: string;
    unit_id: number;
    unit_name?: null | string;
    updated_at?: string;
  }

  /** 补货申请，对应后端 ReplenishmentRead */
  export interface Replenishment {
    applicant_id: number;
    applicant_name?: null | string;
    approved_at?: null | string;
    approved_by?: null | number;
    cancelled_at?: null | string;
    completed_at?: null | string;
    created_at: string;
    fulfillment_po_id?: null | number;
    id: number;
    items?: Item[];
    reason: string;
    rejected_at?: null | string;
    reject_reason?: null | string;
    replenishment_no: string;
    source_delivery_id?: null | number;
    source_po_id?: null | number;
    status: string;
    supplier_code?: null | string;
    supplier_id: number;
    supplier_name?: null | string;
    updated_at: string;
  }

  export interface ListParams extends PageQuery {
    status?: string;
  }
}

/** 分页查询补货申请 */
export async function getReplenishmentListApi(
  params?: ReplenishmentApi.ListParams,
) {
  return requestClient.get<
    PageResult<ReplenishmentApi.Replenishment>
  >('/replenishments', { params });
}

/** 查询补货申请详情 */
export async function getReplenishmentApi(id: number) {
  return requestClient.get<ReplenishmentApi.Replenishment>(
    `/replenishments/${id}`,
  );
}

/** 提交补货申请 */
export async function submitReplenishmentApi(id: number) {
  return requestClient.post<ReplenishmentApi.Replenishment>(
    `/replenishments/${id}/submit`,
  );
}

/** 审批通过补货申请 */
export async function approveReplenishmentApi(id: number) {
  return requestClient.post<ReplenishmentApi.Replenishment>(
    `/replenishments/${id}/approve`,
  );
}

/** 驳回补货申请 */
export async function rejectReplenishmentApi(id: number, reason: string) {
  return requestClient.post<ReplenishmentApi.Replenishment>(
    `/replenishments/${id}/reject`,
    { reason },
  );
}

/** 取消补货申请 */
export async function cancelReplenishmentApi(id: number) {
  return requestClient.post<ReplenishmentApi.Replenishment>(
    `/replenishments/${id}/cancel`,
  );
}
