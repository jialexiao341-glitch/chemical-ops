import type { PurchaseOrderApi } from './procurement/purchase-orders';
import type { PageQuery } from './request';

import { requestClient } from './request';

export namespace SupplierPortalApi {
  export interface RfqItem {
    id: number;
    line_no: number;
    requested_name: string;
    specification: null | string;
    quantity: string;
    unit_id: number;
    required_delivery_date: null | string;
    technical_requirements: null | string;
  }

  export interface RfqListItem {
    id: number;
    rfq_no: string;
    item_count: number;
    item_summary: string;
    quote_deadline: null | string;
    requested_delivery_date: null | string;
    delivery_requirements: null | string;
    status: string;
    response_status: string;
    invited_at: string;
    response_at: null | string;
  }

  export interface QuoteItem {
    id: number;
    rfq_item_id: number;
    supplier_model: null | string;
    quoted_quantity: string;
    unit_id: number;
    unit_price: string;
    tax_rate: null | string;
    moq_quantity: null | string;
    moq_unit_id: null | number;
    lead_days: null | number;
    payment_terms: null | string;
    note: null | string;
  }

  export interface SupplierQuote {
    quote_no: string;
    quote_version: number;
    quote_date: string;
    valid_until: null | string;
    currency_code: string;
    status: string;
    note: null | string;
    created_at: string;
    items: QuoteItem[];
  }

  export interface RfqDetail extends RfqListItem {
    items: RfqItem[];
    latest_quote: null | SupplierQuote;
  }

  export interface OrderPage {
    items: PurchaseOrderApi.PurchaseOrder[];
    page: number;
    page_size: number;
    total: number;
  }

  export interface OrderListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }

  export interface RfqPage {
    items: RfqListItem[];
    page: number;
    page_size: number;
    total: number;
  }

  export interface RfqListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }

  export interface QuoteItemPayload {
    rfq_item_id: number;
    supplier_model?: null | string;
    quoted_quantity: number | string;
    unit_id: number;
    unit_price: number | string;
    tax_rate?: null | number | string;
    moq_quantity?: null | number | string;
    moq_unit_id?: null | number;
    lead_days?: null | number;
    payment_terms?: null | string;
    note?: null | string;
  }

  export interface QuotePayload {
    quote_date?: null | string;
    valid_until?: null | string;
    currency_code?: string;
    note?: null | string;
    items: QuoteItemPayload[];
  }

  export interface DeliveryUpdate {
    id: number;
    po_id: number;
    po_no: string;
    previous_date: null | string;
    expected_date: string;
    note: null | string;
    submitted_at: string;
  }

  export interface ShipmentItemPayload {
    po_item_id: number;
    planned_quantity: number | string;
    batch_no?: null | string;
    package_spec?: null | string;
    production_date?: null | string;
    expiry_date?: null | string;
    note?: null | string;
  }

  export interface ShipmentPayload {
    po_id: number;
    shipment_date?: null | string;
    expected_arrival_date?: null | string;
    logistics_company?: null | string;
    tracking_no?: null | string;
    note?: null | string;
    items: ShipmentItemPayload[];
  }

  export interface Shipment {
    id: number;
    delivery_no: string;
    po_id: number;
    po_no: string;
    shipment_date: null | string;
    expected_arrival_date: null | string;
    logistics_company: null | string;
    tracking_no: null | string;
    status: string;
    note: null | string;
    created_at: string;
    items: { id: number; line_no: number; po_item_id: number; batch_no: null | string; planned_quantity: string; unit_id: number }[];
  }

  export interface QualityDocument {
    id: number;
    document_no: string;
    po_id: number;
    po_no: string;
    po_item_id: null | number;
    file_id: number;
    file_name: string;
    document_type: string;
    status: string;
    note: null | string;
    submitted_at: string;
    review_note: null | string;
  }

  export interface Reconciliation {
    id: number;
    reconciliation_no: string;
    po_id: number;
    po_no: string;
    currency_code: string;
    total_amount: string;
    status: string;
    items_version: number;
    note: null | string;
    created_at: string;
    updated_at: string;
  }

  export interface ReconciliationMessage {
    id: number;
    author_type: 'BUYER' | 'SUPPLIER';
    message: string;
    created_at: string;
  }

  export interface Page<T> {
    items: T[];
    page: number;
    page_size: number;
    total: number;
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }
}

/** 查询当前供应商账号绑定的订单。 */
export function getSupplierOrderListApi(params: SupplierPortalApi.OrderListParams) {
  return requestClient.get<SupplierPortalApi.OrderPage>(
    '/supplier-portal/orders',
    { params },
  );
}

/** 查询当前供应商自己的订单详情。 */
export function getSupplierOrderApi(orderId: number) {
  return requestClient.get<PurchaseOrderApi.PurchaseOrder>(
    `/supplier-portal/orders/${orderId}`,
  );
}

/** 确认订单。 */
export function confirmSupplierOrderApi(orderId: number) {
  return requestClient.post<PurchaseOrderApi.PurchaseOrder>(
    `/supplier-portal/orders/${orderId}/confirm`,
  );
}

/** 拒绝订单并记录原因。 */
export function rejectSupplierOrderApi(orderId: number, reason: string) {
  return requestClient.post<PurchaseOrderApi.PurchaseOrder>(
    `/supplier-portal/orders/${orderId}/reject`,
    { reason },
  );
}

/** 查询当前供应商账号受邀参与的询价。 */
export function getSupplierRfqListApi(params: SupplierPortalApi.RfqListParams) {
  return requestClient.get<SupplierPortalApi.RfqPage>('/supplier-portal/rfqs', {
    params,
  });
}

/** 查询受邀询价和当前供应商自己的最新报价。 */
export function getSupplierRfqApi(rfqId: number) {
  return requestClient.get<SupplierPortalApi.RfqDetail>(
    `/supplier-portal/rfqs/${rfqId}`,
  );
}

/** 提交新报价版本，供应商身份由服务端绑定账号确定。 */
export function submitSupplierQuoteApi(
  rfqId: number,
  data: SupplierPortalApi.QuotePayload,
) {
  return requestClient.post<SupplierPortalApi.RfqDetail>(
    `/supplier-portal/rfqs/${rfqId}/quotes`,
    data,
  );
}

export function getSupplierDeliveryUpdatesApi(params: SupplierPortalApi.ListParams) {
  return requestClient.get<SupplierPortalApi.Page<SupplierPortalApi.DeliveryUpdate>>('/supplier-portal/delivery-updates', { params });
}

export function updateSupplierExpectedDeliveryApi(orderId: number, expectedDate: string, note?: string) {
  return requestClient.put<SupplierPortalApi.DeliveryUpdate>(`/supplier-portal/orders/${orderId}/delivery-date`, { expected_date: expectedDate, note });
}

export function getSupplierShipmentListApi(params: SupplierPortalApi.ListParams) {
  return requestClient.get<SupplierPortalApi.Page<SupplierPortalApi.Shipment>>('/supplier-portal/shipments', { params });
}

export function createSupplierShipmentApi(data: SupplierPortalApi.ShipmentPayload) {
  return requestClient.post<SupplierPortalApi.Shipment>('/supplier-portal/shipments', data);
}

export function getSupplierQualityDocumentsApi(params: SupplierPortalApi.ListParams) {
  return requestClient.get<SupplierPortalApi.Page<SupplierPortalApi.QualityDocument>>('/supplier-portal/quality-documents', { params });
}

export function submitSupplierQualityDocumentApi(data: FormData) {
  return requestClient.post<SupplierPortalApi.QualityDocument>('/supplier-portal/quality-documents', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
}

export function downloadSupplierQualityDocumentApi(id: number) {
  return requestClient.get<Blob>(`/supplier-portal/quality-documents/${id}/download`, { responseType: 'blob' });
}

export function getSupplierReconciliationListApi(params: SupplierPortalApi.ListParams) {
  return requestClient.get<SupplierPortalApi.Page<SupplierPortalApi.Reconciliation>>('/supplier-portal/reconciliations', { params });
}

export function getSupplierReconciliationMessagesApi(id: number) {
  return requestClient.get<SupplierPortalApi.Page<SupplierPortalApi.ReconciliationMessage>>(`/supplier-portal/reconciliations/${id}/messages`);
}

export function addSupplierReconciliationMessageApi(id: number, message: string) {
  return requestClient.post<SupplierPortalApi.ReconciliationMessage>(`/supplier-portal/reconciliations/${id}/messages`, { message });
}

export function confirmSupplierReconciliationApi(id: number, reason?: string) {
  return requestClient.post<SupplierPortalApi.Reconciliation>(`/supplier-portal/reconciliations/${id}/confirm`, { reason });
}

export function disputeSupplierReconciliationApi(id: number, reason: string) {
  return requestClient.post<SupplierPortalApi.Reconciliation>(`/supplier-portal/reconciliations/${id}/dispute`, { reason });
}

export function getFinanceSupplierReconciliationMessagesApi(id: number) {
  return requestClient.get<SupplierPortalApi.Page<SupplierPortalApi.ReconciliationMessage>>(`/finance/reconciliations/${id}/supplier-messages`);
}

export function addFinanceSupplierReconciliationMessageApi(id: number, message: string) {
  return requestClient.post<SupplierPortalApi.ReconciliationMessage>(`/finance/reconciliations/${id}/supplier-messages`, { message });
}
