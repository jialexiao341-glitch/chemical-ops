"""站内通知的创建、查询和已读处理逻辑。"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import ResourceNotFoundError
from app.modules.notifications import crud
from app.modules.notifications.model import Notification
from app.modules.system.audit import add_audit_log
from app.modules.system.model import Role, User, UserRole


def _now() -> datetime:
    """返回当前本地时间。"""

    return datetime.now()


def notify_users(
    db: Session,
    *,
    recipient_ids: Iterable[int] = (),
    role_codes: Iterable[str] = (),
    notification_type: str,
    title: str,
    content: str,
    related_type: str | None = None,
    related_id: int | None = None,
    exclude_scoped: bool = False,
) -> list[Notification]:
    """向指定用户和角色对应的启用用户写入通知，不单独提交事务。"""

    user_ids = set(recipient_ids)
    codes = set(role_codes)
    if codes:
        role_user_ids = db.scalars(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.status == "ACTIVE", Role.status == "ACTIVE", Role.role_code.in_(codes))
            .distinct()
        ).all()
        user_ids.update(role_user_ids)
    if user_ids:
        active_ids = set(db.scalars(select(User.id).where(User.id.in_(user_ids), User.status == "ACTIVE")).all())
    else:
        active_ids = set()
    if exclude_scoped and active_ids:
        from app.modules.system.model import UserDepartmentScope
        restricted = set(db.scalars(select(UserDepartmentScope.user_id).where(UserDepartmentScope.user_id.in_(active_ids))).all())
        role_sets = {}
        for user_id, role_code in db.execute(select(UserRole.user_id, Role.role_code).join(
            Role, Role.id == UserRole.role_id
        ).where(UserRole.user_id.in_(active_ids), Role.status == "ACTIVE")):
            role_sets.setdefault(user_id, set()).add(role_code)
        unrestricted = {user_id for user_id, roles in role_sets.items()
                        if "SYS_ADMIN" in roles or roles == {"SUPPLIER_PORTAL"}}
        restricted.update(active_ids - unrestricted)
        admin_ids = set(db.scalars(select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(
            UserRole.user_id.in_(restricted), Role.role_code == "SYS_ADMIN", Role.status == "ACTIVE"
        )).all()) if restricted else set()
        active_ids -= restricted - admin_ids
    notifications = [
        Notification(
            recipient_id=user_id,
            notification_type=notification_type,
            title=title,
            content=content,
            related_type=related_type,
            related_id=related_id,
            is_read=0,
        )
        for user_id in sorted(active_ids)
    ]
    db.add_all(notifications)
    return notifications


def list_notifications(db: Session, user: User, *, unread_only: bool, page: int, page_size: int):
    """分页查询当前用户的站内通知。"""

    return crud.list_page(db, recipient_id=user.id, unread_only=unread_only, page=page, page_size=page_size)


def get_notification(db: Session, user: User, notification_id: int) -> Notification:
    """查询当前用户拥有的通知。"""

    notification = crud.get_by_id(db, notification_id)
    if notification is None or notification.recipient_id != user.id:
        raise ResourceNotFoundError(f"通知 {notification_id} 不存在")
    return notification


def mark_read(db: Session, user: User, notification_id: int) -> Notification:
    """将当前用户的一条通知标记为已读。"""

    notification = get_notification(db, user, notification_id)
    if notification.is_read == 0:
        notification.is_read = 1
        notification.read_at = _now()
        add_audit_log(db, actor_id=user.id, action_type="READ", resource_type="NOTIFICATION", resource_id=notification.id, request_summary="标记通知已读", result_status="SUCCESS")
        db.commit()
        db.refresh(notification)
    return notification


def mark_all_read(db: Session, user: User) -> int:
    """将当前用户的全部未读通知标记为已读。"""

    now = _now()
    result = db.execute(
        update(Notification)
        .where(Notification.recipient_id == user.id, Notification.is_read == 0)
        .values(is_read=1, read_at=now)
    )
    updated_count = result.rowcount or 0
    if updated_count:
        add_audit_log(db, actor_id=user.id, action_type="READ_ALL", resource_type="NOTIFICATION", resource_id=None, request_summary="标记全部通知已读", result_status="SUCCESS")
        db.commit()
    return updated_count


def unread_count(db: Session, user: User) -> int:
    """统计当前用户未读通知数量。"""

    return db.scalar(select(func.count(Notification.id)).where(Notification.recipient_id == user.id, Notification.is_read == 0)) or 0
