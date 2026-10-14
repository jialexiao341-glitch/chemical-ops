import type { PageQuery, PageResult } from '#/api/request';
import { requestClient } from '#/api/request';

export interface ReturnSource {
  source_delivery_item_id: number;
  source_po_item_id: number;
  supplier_id: number;
  supplier_name: string;
  po_no: string;
  delivery_no: string;
  line_no: number;
  product_name: string;
  batch_no: string;
  unit_name: string;
  received_quantity: string;
  returned_quantity: string;
}
export interface ReturnItem {
  id: number;
  product_name: null | string;
  unit_name: null | string;
  source_delivery_no: null | string;
  source_po_no: null | string;
  requested_quantity: string;
  returned_quantity: string;
}
export interface InventoryReturn {
  id: number;
  return_no: string;
  applicant_id: number;
  reason: string;
  status: string;
  reject_reason: null | string;
  items: ReturnItem[];
}
export function getReturnSourcesApi(balance_id: number) {
  return requestClient.get<ReturnSource[]>('/inventory/returns/sources', { params: { balance_id } });
}
export function createInventoryReturnApi(data: {
  supplier_id: number;
  reason: string;
  items: {
    product_id: number; warehouse_id: number; location_id: number;
    batch_id: number; unit_id: number; source_delivery_item_id: number;
    source_po_item_id: number; requested_quantity: string;
  }[];
}) { return requestClient.post<InventoryReturn>('/inventory/returns', data); }
export function getInventoryReturnsApi(params: PageQuery & { status?: string }) {
  return requestClient.get<PageResult<InventoryReturn>>('/inventory/returns', { params });
}
export function actInventoryReturnApi(id: number, action: 'approve' | 'cancel' | 'execute' | 'reject' | 'submit', reason?: string) {
  return requestClient.post<InventoryReturn>(`/inventory/returns/${id}/${action}`, reason ? { reason } : undefined);
}
