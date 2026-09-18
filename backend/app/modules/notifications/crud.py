"""站内通知的数据访问操作。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.notifications.model import Notification


def list_page(db: Session, *, recipient_id: int, unread_only: bool, page: int, page_size: int) -> tuple[list[Notification], int]:
    """按接收人分页查询通知。"""

    conditions = [Notification.recipient_id == recipient_id]
    if unread_only:
        conditions.append(Notification.is_read == 0)
    total = db.scalar(select(func.count(Notification.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(Notification)
            .where(*conditions)
            .order_by(Notification.is_read.asc(), Notification.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_by_id(db: Session, notification_id: int) -> Notification | None:
    """按主键查询通知。"""

    return db.get(Notification, notification_id)
