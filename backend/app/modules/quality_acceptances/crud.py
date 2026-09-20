"""质量验收模块的数据访问操作。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.deliveries.model import Delivery
from app.modules.quality_acceptances.model import QualityAcceptance


def get_by_id(db: Session, acceptance_id: int, *, for_update: bool = False) -> QualityAcceptance | None:
    """按主键查询验收记录。"""

    statement = select(QualityAcceptance).where(QualityAcceptance.id == acceptance_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_page(
    db: Session,
    *,
    delivery_ids: set[int] | None,
    result: str | None,
    page: int,
    page_size: int,
) -> tuple[list[QualityAcceptance], int]:
    """按数据范围和结果分页查询验收记录。"""

    conditions = []
    if delivery_ids is not None:
        if not delivery_ids:
            return [], 0
        conditions.append(QualityAcceptance.delivery_id.in_(delivery_ids))
    if result:
        conditions.append(QualityAcceptance.result == result)
    total = db.scalar(select(func.count(QualityAcceptance.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(QualityAcceptance)
            .where(*conditions)
            .order_by(QualityAcceptance.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_delivery(db: Session, delivery_id: int, *, for_update: bool = False) -> Delivery | None:
    """查询到货单。"""

    statement = select(Delivery).where(Delivery.id == delivery_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def get_by_delivery(db: Session, delivery_id: int) -> QualityAcceptance | None:
    """查询到货单已有的验收记录。"""

    return db.scalar(select(QualityAcceptance).where(QualityAcceptance.delivery_id == delivery_id))
