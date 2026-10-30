"""批次质量隔离及库存履约共用的锁顺序。"""

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError
from app.modules.inventory.model import InventoryBatch


def batch_quality_hold_exists_clause():
    """Return an EXISTS clause matching batches whose source delivery is under quality hold."""

    from app.modules.quality_acceptances.model import QualityAcceptance

    return exists(
        select(QualityAcceptance.id).where(
            InventoryBatch.source_delivery_id.is_not(None),
            QualityAcceptance.delivery_id == InventoryBatch.source_delivery_id,
            QualityAcceptance.result.in_(("REINSPECTION", "FAILED", "PARTIAL")),
        )
    )


def is_batch_quality_held(db: Session, batch: InventoryBatch) -> bool:
    """Check whether a single batch is under quality hold."""

    if batch.status != "ACTIVE":
        return True
    if batch.source_delivery_id is None:
        return False
    from app.modules.quality_acceptances.model import QualityAcceptance

    return (
        db.scalar(
            select(QualityAcceptance.id)
            .where(
                QualityAcceptance.delivery_id == batch.source_delivery_id,
                QualityAcceptance.result.in_(("REINSPECTION", "FAILED", "PARTIAL")),
            )
            .limit(1)
        )
        is not None
    )


def lock_available_batches(db: Session, batch_ids) -> None:
    """先按批次 ID 加锁，再锁库存余额，避免复检和库存履约交错。"""
    ids = sorted(set(batch_ids))
    if not ids:
        return
    batches = list(db.scalars(select(InventoryBatch).where(InventoryBatch.id.in_(ids))
        .order_by(InventoryBatch.id).with_for_update().execution_options(populate_existing=True)).all())
    if len(batches) != len(ids):
        raise BusinessValidationError("库存批次不存在")
    if any(batch.status != 'ACTIVE' for batch in batches):
        raise BusinessValidationError("库存批次处于质量隔离或不可用状态")
    # 兼容上线前已提交复检或不合格结果的历史批次，无需猜测或改写人工状态。
    from app.modules.quality_acceptances.model import QualityAcceptance
    delivery_ids = {batch.source_delivery_id for batch in batches if batch.source_delivery_id is not None}
    if delivery_ids and db.scalar(select(QualityAcceptance.id).where(
        QualityAcceptance.delivery_id.in_(delivery_ids),
        QualityAcceptance.result.in_(("REINSPECTION", "FAILED", "PARTIAL")),
    ).limit(1)) is not None:
        raise BusinessValidationError("库存批次处于质量隔离或不可用状态")
