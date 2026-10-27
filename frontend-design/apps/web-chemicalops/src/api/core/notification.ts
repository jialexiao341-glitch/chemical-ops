import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace NotificationApi {
  /** 站内通知，对应后端 NotificationRead */
  export interface Notification {
    content: string;
    created_at: string;
    id: number;
    /** 0 未读，1 已读 */
    is_read: number;
    notification_type: string;
    read_at?: null | string;
    recipient_id: number;
    related_id?: null | number;
    related_type?: null | string;
    title: string;
  }

  export interface UnreadCount {
    unread_count: number;
  }

  export interface ReadAllResult {
    updated_count: number;
  }
}

/**
 * 查询当前用户的通知。
 *
 * 后端只返回发给当前登录用户的通知，无需传接收人。
 */
export async function getNotificationListApi(
  params?: PageQuery & { unread_only?: boolean },
) {
  return requestClient.get<PageResult<NotificationApi.Notification>>(
    '/notifications',
    { params },
  );
}

/** 未读数量，用于顶部铃铛角标 */
export async function getUnreadCountApi() {
  return requestClient.get<NotificationApi.UnreadCount>(
    '/notifications/unread-count',
  );
}

/** 标记单条通知已读 */
export async function markNotificationReadApi(id: number) {
  const result = await requestClient.request<NotificationApi.Notification>(`/notifications/${id}/read`, { method: 'PATCH' });
  notifyNotificationChanged();
  return result;
}

/** 全部标记为已读 */
export async function markAllNotificationsReadApi() {
  const result = await requestClient.post<NotificationApi.ReadAllResult>(
    '/notifications/read-all',
  );
  notifyNotificationChanged();
  return result;
}

/** 解析本人通知对应的提案；详情接口会再次校验提案和资源。 */
export async function resolveProposalNotificationApi(id: number) {
  return requestClient.get<{ confirmation_id: string }>(`/notifications/${id}/proposal`);
}

export function notifyNotificationChanged() {
  window.dispatchEvent(new Event('chemicalops:notifications-changed'));
}
