import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace DeliveryApi {
  /** 到货明细 */
  export interface DeliveryItem {
    actual_quantity?: null | string;
    batch_no?: null | string;
    created_at?: string;
    delivery_id?: number;
    document_complete?: boolean;
    expiry_date?: null | string;
    id: number;
    note?: null | string;
    package_spec?: null | string;
    planned_quantity: string;
    po_item_id: number;
    production_date?: null | string;
    short_quantity?: null | string;
    status?: string;
  }

  /** 到货单，对应后端 DeliveryRead */
  export interface Delivery {
    actual_arrival_date?: null | string;
    created_at?: string;
    delivery_no: string;
    expected_arrival_date?: null | string;
    id: number;
    items?: DeliveryItem[];
    logistics_company?: null | string;
    note?: null | string;
    po_id: number;
    received_at?: null | string;
    received_by?: null | number;
    shipment_date?: null | string;
    status: string;
    supplier_id?: number;
    tracking_no?: null | string;
    updated_at?: string;
  }

  export interface DeliveryItemPayload {
    batch_no?: null | string;
    document_complete?: boolean;
    expiry_date?: null | string;
    note?: null | string;
    package_spec?: null | string;
    planned_quantity: number | string;
    po_item_id: number;
    production_date?: null | string;
  }

  export interface DeliveryPayload {
    expected_arrival_date?: null | string;
    items: DeliveryItemPayload[];
    logistics_company?: null | string;
    note?: null | string;
    po_id: number;
    shipment_date?: null | string;
    tracking_no?: null | string;
  }

  export interface ReceiveItem {
    actual_quantity: number | string;
    delivery_item_id: number;
    short_quantity?: number | string;
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }
}

/** 分页查询到货单 */
export async function getDeliveryListApi(params?: DeliveryApi.ListParams, options?: { silent?: boolean }) {
  return requestClient.get<PageResult<DeliveryApi.Delivery>>('/deliveries', {
    ...options,
    params,
  });
}

/** 查询到货单详情（含明细） */
export async function getDeliveryApi(id: number) {
  return requestClient.get<DeliveryApi.Delivery>(`/deliveries/${id}`);
}

/** 为已下单的采购订单登记到货计划 */
export async function createDeliveryApi(data: DeliveryApi.DeliveryPayload) {
  return requestClient.post<DeliveryApi.Delivery>('/deliveries', data);
}

/**
 * 确认收货。
 * 存在短交时后端会自动创建 SHORT_DELIVERY 异常并发送站内通知。
 */
export async function receiveDeliveryApi(
  id: number,
  data: {
    actual_arrival_date?: null | string;
    items: DeliveryApi.ReceiveItem[];
  },
) {
  return requestClient.post<DeliveryApi.Delivery>(
    `/deliveries/${id}/receive`,
    data,
  );
}
