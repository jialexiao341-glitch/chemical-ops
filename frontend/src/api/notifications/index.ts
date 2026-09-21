import type { NotificationItem } from "#src/layout/widgets/notification/types";
import { request } from "#src/utils/request";

interface BackendNotification {
	id: number
	title: string
	content: string
	is_read: number
	created_at: string
}

interface BackendNotificationPage {
	items: BackendNotification[]
}

export function fetchNotifications(): Promise<NotificationItem[]> {
	return request
		.get("notifications")
		.json<BackendNotificationPage>()
		.then(({ items }) => items.map(item => ({
			avatar: "",
			date: new Date(item.created_at).toLocaleString("zh-CN"),
			isRead: item.is_read === 1,
			message: item.content,
			title: item.title,
		})));
}
