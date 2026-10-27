/** 通知只携带通知 ID；提案身份和当前可见性由服务端解析。 */
export function proposalNotificationLink(notification: { id: number; notification_type: string; related_type?: null | string }): string | undefined {
  if (notification.notification_type !== 'AI_PROPOSAL_PENDING' || notification.related_type !== 'AI_ACTION_PROPOSAL') return;
  if (!Number.isSafeInteger(notification.id) || notification.id <= 0) return;
  return `/ai/tasks?proposal_notification=${notification.id}`;
}

export function parseProposalNotificationId(value: unknown): number | undefined {
  if (typeof value !== 'string' || !/^[1-9]\d*$/.test(value)) return;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : undefined;
}
