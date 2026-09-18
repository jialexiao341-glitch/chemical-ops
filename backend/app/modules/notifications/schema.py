"""站内通知接口的请求与响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    """站内通知响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    recipient_id: int
    notification_type: str
    title: str
    content: str
    related_type: str | None
    related_id: int | None
    is_read: int
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    """站内通知分页响应。"""

    items: list[NotificationRead]
    total: int
    page: int
    page_size: int


class NotificationUnreadCount(BaseModel):
    """未读通知数量响应。"""

    unread_count: int


class NotificationReadAllResult(BaseModel):
    """批量标记通知已读的响应。"""

    updated_count: int
