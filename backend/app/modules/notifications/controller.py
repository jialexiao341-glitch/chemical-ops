"""站内通知的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.notifications import service
from app.modules.notifications.schema import NotificationPage, NotificationRead, NotificationReadAllResult, NotificationUnreadCount
from app.modules.system.model import User


router = APIRouter(prefix="/notifications", tags=["站内通知"])


def _proposal_notification_statuses(db: Session, user: User, items):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.modules.ai.model import AIAgentActionProposal
    ids = {item.related_id for item in items if item.notification_type == "AI_PROPOSAL_PENDING"
           and item.related_type == "AI_ACTION_PROPOSAL" and item.related_id is not None}
    if not ids:
        return {}
    rows = db.execute(select(AIAgentActionProposal.id, AIAgentActionProposal.status, AIAgentActionProposal.expires_at)
                      .where(AIAgentActionProposal.id.in_(ids), AIAgentActionProposal.user_id == user.id)).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {row.id: "EXPIRED" if row.status == "PENDING" and row.expires_at <= now else row.status for row in rows}


def _safe_notification(item, proposal_statuses=None):
    result = NotificationRead.model_validate(item)
    if item.notification_type == "OPERATION_TASK_ASSIGNED":
        return result.model_copy(update={"related_id": None})
    if item.notification_type == "OPERATION_SUGGESTION":
        return result.model_copy(update={"title": "运营建议", "content": "有新的运营建议，请前往建议列表按权限查看。", "related_id": None})
    if item.notification_type == "AI_PROPOSAL_PENDING":
        statuses = proposal_statuses or {}
        status = statuses.get(item.related_id, "UNAVAILABLE")
        label = {"PENDING": "待确认", "EXECUTED": "已执行", "CANCELLED": "已取消",
                 "EXPIRED": "已过期", "INVALIDATED": "已失效"}.get(status, "不可用")
        title = item.title.replace("待确认", label)
        return result.model_copy(update={"title": title, "content": f"提案{label}，请查看详情。"})
    return result


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
    statuses = _proposal_notification_statuses(db, user, items)
    return NotificationPage(items=[_safe_notification(item, statuses) for item in items], total=total, page=page, page_size=page_size)


@router.get("/unread-count", response_model=NotificationUnreadCount, summary="查询未读通知数量")
def unread_count(db: Session = Depends(get_db), user: User = Depends(require_permission("system.notifications.read"))) -> NotificationUnreadCount:
    """查询当前登录用户的未读通知数量。"""

    return NotificationUnreadCount(unread_count=service.unread_count(db, user))


@router.post("/read-all", response_model=NotificationReadAllResult, summary="全部标记为已读")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(require_permission("system.notifications.write"))) -> NotificationReadAllResult:
    """将当前登录用户的全部未读通知标记为已读。"""

    return NotificationReadAllResult(updated_count=service.mark_all_read(db, user))


@router.get("/{notification_id}/proposal", summary="解析本人提案通知")
def resolve_proposal_notification(notification_id: int, db: Session = Depends(get_db),
                                  user: User = Depends(require_permission("system.notifications.read")),
                                  _ai_user: User = Depends(require_permission("ai.workspace.read"))):
    from sqlalchemy import select
    from app.core.errors import ResourceNotFoundError
    from app.modules.ai.model import AIAgentActionProposal
    notification = service.get_notification(db, user, notification_id)
    if notification.notification_type != "AI_PROPOSAL_PENDING" or notification.related_type != "AI_ACTION_PROPOSAL":
        raise ResourceNotFoundError("提案通知不存在")
    proposal = db.scalar(select(AIAgentActionProposal).where(
        AIAgentActionProposal.id == notification.related_id, AIAgentActionProposal.user_id == user.id))
    if proposal is None:
        raise ResourceNotFoundError("提案通知不存在")
    return {"confirmation_id": proposal.confirmation_id}


@router.get("/{notification_id}/operation-task", summary="解析分配给本人的异常任务通知")
def resolve_operation_task_notification(notification_id: int, db: Session = Depends(get_db),
                                        user: User = Depends(require_permission("system.notifications.read")),
                                        _task_user: User = Depends(require_permission("operations.exceptions.read"))):
    from sqlalchemy import select
    from app.core.errors import ResourceNotFoundError
    from app.modules.operation_exceptions.model import OperationTask
    from app.modules.operation_exceptions.service import get_my_task
    notification = service.get_notification(db, user, notification_id)
    if notification.notification_type != "OPERATION_TASK_ASSIGNED" or notification.related_type != "OPERATION_TASK":
        raise ResourceNotFoundError("任务通知不存在")
    task = db.scalar(select(OperationTask).where(OperationTask.id == notification.related_id,
                                                OperationTask.assignee_id == user.id))
    if task is None:
        raise ResourceNotFoundError("任务通知不可用或已改派")
    get_my_task(db, user, task.id)
    return {"exception_id": task.exception_id, "task_id": task.id}


@router.patch("/{notification_id}/read", response_model=NotificationRead, summary="标记通知已读")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("system.notifications.write"))) -> NotificationRead:
    """将指定通知标记为已读。"""

    item = service.mark_read(db, user, notification_id)
    return _safe_notification(item, _proposal_notification_statuses(db, user, [item]))
