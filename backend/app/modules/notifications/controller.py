"""站内通知的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.notifications import service
from app.modules.notifications.schema import NotificationPage, NotificationRead, NotificationReadAllResult, NotificationUnreadCount
from app.modules.system.model import User


router = APIRouter(prefix="/notifications", tags=["站内通知"])


@router.get("", response_model=NotificationPage, summary="查询我的通知")
def list_notifications(
    unread_only: bool = Query(default=False, description="是否只查询未读通知"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("system.notifications.read")),
) -> NotificationPage:
    """分页查询当前登录用户的站内通知。"""

    items, total = service.list_notifications(db, user, unread_only=unread_only, page=page, page_size=page_size)
    return NotificationPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/unread-count", response_model=NotificationUnreadCount, summary="查询未读通知数量")
def unread_count(db: Session = Depends(get_db), user: User = Depends(require_permission("system.notifications.read"))) -> NotificationUnreadCount:
    """查询当前登录用户的未读通知数量。"""

    return NotificationUnreadCount(unread_count=service.unread_count(db, user))


@router.post("/read-all", response_model=NotificationReadAllResult, summary="全部标记为已读")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(require_permission("system.notifications.write"))) -> NotificationReadAllResult:
    """将当前登录用户的全部未读通知标记为已读。"""

    return NotificationReadAllResult(updated_count=service.mark_all_read(db, user))


@router.patch("/{notification_id}/read", response_model=NotificationRead, summary="标记通知已读")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("system.notifications.write"))) -> NotificationRead:
    """将指定通知标记为已读。"""

    return service.mark_read(db, user, notification_id)
