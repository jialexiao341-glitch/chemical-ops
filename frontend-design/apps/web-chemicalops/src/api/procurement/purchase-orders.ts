import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace PurchaseOrderApi {
  /** 采购订单明细 */
  export interface OrderItem {
    created_at?: string;
    id: number;
    line_no?: number;
    note?: null | string;
    order_quantity: string;
    planned_arrival_date?: null | string;
    po_id?: number;
    product_id: number;
    product_name_snapshot: string;
    received_quantity: string;
    source_quote_item_id?: null | number;
    status: string;
    supplier_model_snapshot?: null | string;
    supplier_product_id?: null | number;
    tax_rate?: null | string;
    unit_id: number;
    unit_price: string;
    updated_at?: string;
  }

  /** 订单审批记录 */
  export interface OrderApproval {
    acted_at?: null | string;
    action?: null | string;
    approver_id?: null | number;
    created_at?: string;
    id: number;
    node_code?: string;
    node_name?: string;
    opinion?: null | string;
    po_id?: number;
    sequence_no?: number;
  }

  /** 订单事件（状态流转轨迹） */
  export interface OrderEvent {
    created_at?: string;
    event_note?: null | string;
    event_time?: string;
    event_type: string;
    from_status?: null | string;
    id: number;
    operator_id?: null | number;
    po_id?: number;
    to_status?: null | string;
  }

  /** 采购订单，对应后端 PurchaseOrderRead */
  export interface PurchaseOrder {
    approved_at?: null | string;
    approvals?: OrderApproval[];
    buyer_id?: number;
    cancel_reason?: null | string;
    cancelled_at?: null | string;
    created_at?: string;
    currency_code?: string;
    delivery_address?: null | string;
    department_id?: null | number;
    events?: OrderEvent[];
    expected_arrival_date?: null | string;
    id: number;
    items?: OrderItem[];
    note?: null | string;
    order_amount: string;
    order_date?: null | string;
    po_no: string;
    source_comparison_id?: null | number;
    source_quote_id?: null | number;
    source_request_id?: null | number;
    status: string;
    supplier_confirmed_at?: null | string;
    supplier_id: number;
    updated_at?: string;
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }
}

/** 分页查询采购订单 */
export async function getPurchaseOrderListApi(
  params?: PurchaseOrderApi.ListParams,
) {
  return requestClient.get<PageResult<PurchaseOrderApi.PurchaseOrder>>(
    '/purchase-orders',
    { params },
  );
}

/** 查询采购订单详情（含明细、审批记录、事件轨迹） */
export async function getPurchaseOrderApi(id: number) {
  return requestClient.get<PurchaseOrderApi.PurchaseOrder>(
    `/purchase-orders/${id}`,
  );
}

/**
 * 依据中选报价生成订单草稿。
 * 报价必须覆盖全部询价明细，且产品主数据不能为空。
 */
export async function createPurchaseOrderApi(data: {
  comparison_id: number;
  delivery_address?: string;
  expected_arrival_date?: null | string;
  note?: string;
  quote_id: number;
}) {
  return requestClient.post<PurchaseOrderApi.PurchaseOrder>(
    '/purchase-orders',
    data,
  );
}

/** 更新订单草稿（地址、期望到货日期、备注） */
export async function updatePurchaseOrderApi(
  id: number,
  data: {
    delivery_address?: string;
    expected_arrival_date?: null | string;
    note?: string;
  },
) {
  return requestClient.request<PurchaseOrderApi.PurchaseOrder>(`/purchase-orders/${id}`, { data, method: 'PATCH' });
}

/** 提交订单审批 */
export async function submitPurchaseOrderApi(id: number) {
  return requestClient.post<PurchaseOrderApi.PurchaseOrder>(
    `/purchase-orders/${id}/submit`,
  );
}

/** 审批通过 */
export async function approvePurchaseOrderApi(id: number, opinion?: string) {
  return requestClient.post<PurchaseOrderApi.PurchaseOrder>(
    `/purchase-orders/${id}/approve`,
    { opinion },
  );
}

/** 驳回订单 */
export async function rejectPurchaseOrderApi(id: number, opinion?: string) {
  return requestClient.post<PurchaseOrderApi.PurchaseOrder>(
    `/purchase-orders/${id}/reject`,
    { opinion },
  );
}

/** 正式下单，进入 ORDERED */
export async function placePurchaseOrderApi(id: number) {
  return requestClient.post<PurchaseOrderApi.PurchaseOrder>(
    `/purchase-orders/${id}/place`,
  );
}

/** 取消订单 */
export async function cancelPurchaseOrderApi(id: number, reason: string) {
  return requestClient.post<PurchaseOrderApi.PurchaseOrder>(
    `/purchase-orders/${id}/cancel`,
    { reason },
  );
}
