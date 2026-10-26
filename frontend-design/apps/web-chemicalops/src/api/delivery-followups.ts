import { requestClient } from './request';

export interface DeliveryFollowup {
  id: number;
  order_id: number;
  po_no: string;
  message: string;
  status: 'SENT' | 'REPLIED';
  sent_at: string;
  replied_at: string | null;
  reply_message: string | null;
  reply_expected_date: string | null;
  can_reply: boolean;
}

export function getDeliveryFollowupsApi(orderId: number, supplierMode: boolean, page = 1, pageSize = 20) {
  const prefix = supplierMode ? 'supplier-portal/orders' : 'purchase-orders';
  return requestClient.get<{ items: DeliveryFollowup[]; total: number }>(`/${prefix}/${orderId}/followups`, {
    params: { page, page_size: pageSize },
  });
}

export function sendDeliveryFollowupApi(orderId: number, confirmationId: string, previewVersion: number) {
  return requestClient.post<DeliveryFollowup>(`/purchase-orders/${orderId}/followups`, {
    confirmation_id: confirmationId, preview_version: previewVersion, confirm: true,
  });
}

export function replyDeliveryFollowupApi(orderId: number, followupId: number,
  data: { request_key: string; message: string; expected_date?: string }) {
  return requestClient.post<DeliveryFollowup>(`/supplier-portal/orders/${orderId}/followups/${followupId}/reply`, data);
}

export function resolveDeliveryFollowupApi(followupId: number, supplierMode: boolean) {
  const prefix = supplierMode ? 'supplier-portal/delivery-followups' : 'purchase-orders/followups';
  return requestClient.get<DeliveryFollowup>(`/${prefix}/${followupId}`);
}
