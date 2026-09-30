"""Persist analysis snapshots and review inventory batch locations."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.insights.model import BatchCheckEvent, BatchCheckItem, InsightSnapshot
from app.modules.inventory import service as inventory_service
from app.modules.inventory.model import InventoryBalance, InventoryBatch, InventoryTransaction
from app.modules.system.audit import add_audit_log
from app.modules.system.model import User
from app.modules.system import crud as system_crud


class SnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    object_id: int
    result_json: dict
    created_by: int
    created_at: datetime


class CheckItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    batch_id: int
    balance_id: int | None
    transaction_id: int | None
    target_label: str
    snapshot_id: int
    assignee_id: int | None
    status: str
    finding: str | None
    checked_by: int | None
    checked_at: datetime | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CheckItemUpdate(BaseModel):
    assignee_id: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, pattern="^(OPEN|CHECKED|NEEDS_ACTION|VERIFIED)$")
    finding: str | None = Field(default=None, max_length=2000)


class CheckEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    check_id: int
    actor_id: int
    status: str
    assignee_id: int | None
    finding: str | None
    created_at: datetime


def save_snapshot(db: Session, user: User, kind: str, object_id: int, result: dict) -> InsightSnapshot:
    snapshot = InsightSnapshot(kind=kind, object_id=object_id, result_json=result, created_by=user.id)
    db.add(snapshot)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="INSIGHT_SNAPSHOT", resource_id=snapshot.id, request_summary=f"保存 {kind} 分析快照", result_status="SUCCESS")
    db.commit()
    db.refresh(snapshot)
    return snapshot


def list_snapshots(db: Session, user: User, kind: str, object_id: int) -> list[InsightSnapshot]:
    # A snapshot may include facts from other warehouses visible to its creator.
    return list(db.scalars(select(InsightSnapshot).where(InsightSnapshot.kind == kind, InsightSnapshot.object_id == object_id, InsightSnapshot.created_by == user.id).order_by(InsightSnapshot.id.desc()).limit(20)).all())


def _batch_for_balance(db: Session, user: User, balance_id: int) -> InventoryBatch:
    balance = inventory_service._require_balance_for_user(db, user, balance_id)
    batch = db.get(InventoryBatch, balance.batch_id)
    if batch is None:
        raise ResourceNotFoundError("库存批次不存在")
    return batch


def list_batch_checks(db: Session, user: User, balance_id: int) -> list[BatchCheckItem]:
    batch = _batch_for_balance(db, user, balance_id)
    scope = inventory_service.accessible_warehouse_ids(db, user)
    rows = db.scalars(select(BatchCheckItem).where(BatchCheckItem.batch_id == batch.id).order_by(BatchCheckItem.id)).all()
    return [row for row in rows if scope is None or item_warehouse_id(db, row) in scope]


def item_warehouse_id(db: Session, item: BatchCheckItem) -> int:
    if item.balance_id is not None:
        balance = db.get(InventoryBalance, item.balance_id)
        if balance is not None and balance.batch_id == item.batch_id:
            return balance.warehouse_id
    if item.transaction_id is not None:
        transaction = db.get(InventoryTransaction, item.transaction_id)
        if transaction is not None and transaction.batch_id == item.batch_id:
            return transaction.warehouse_id
    raise ResourceNotFoundError("批次核查来源不存在")


def list_check_events(db: Session, user: User, balance_id: int, check_id: int) -> list[BatchCheckEvent]:
    allowed = {item.id for item in list_batch_checks(db, user, balance_id)}
    if check_id not in allowed:
        raise ResourceNotFoundError("批次核查项不存在")
    return list(db.scalars(select(BatchCheckEvent).where(BatchCheckEvent.check_id == check_id).order_by(BatchCheckEvent.id)).all())


def create_batch_checks(db: Session, user: User, balance_id: int, snapshot_id: int) -> list[BatchCheckItem]:
    batch = _batch_for_balance(db, user, balance_id)
    snapshot = db.get(InsightSnapshot, snapshot_id)
    if snapshot is None or snapshot.created_by != user.id or snapshot.kind != "batch-impact" or snapshot.object_id != balance_id:
        raise BusinessValidationError("请先保存当前批次影响分析")
    scope = inventory_service.accessible_warehouse_ids(db, user)
    balances = db.scalars(select(InventoryBalance).where(InventoryBalance.batch_id == batch.id)).all()
    for balance in balances:
        if scope is not None and balance.warehouse_id not in scope:
            continue
        existing = db.scalar(select(BatchCheckItem.id).where(BatchCheckItem.batch_id == batch.id, BatchCheckItem.balance_id == balance.id))
        if existing is None:
            db.add(BatchCheckItem(batch_id=batch.id, balance_id=balance.id, snapshot_id=snapshot.id, target_label=f"库存余额 #{balance.id} · 库位 #{balance.location_id}"))
    outbound = db.scalars(select(InventoryTransaction).where(InventoryTransaction.batch_id == batch.id, or_(InventoryTransaction.transaction_type == "OUTBOUND", and_(InventoryTransaction.transaction_type == "INBOUND", InventoryTransaction.source_type == "INVENTORY_TRANSFER"))).order_by(InventoryTransaction.id)).all()
    for transaction in outbound:
        if scope is not None and transaction.warehouse_id not in scope:
            continue
        existing = db.scalar(select(BatchCheckItem.id).where(BatchCheckItem.batch_id == batch.id, BatchCheckItem.transaction_id == transaction.id))
        if existing is None:
            source = f"{transaction.source_type or '未知来源'} #{transaction.source_id or '未记录'}"
            direction = "出库" if transaction.transaction_type == "OUTBOUND" else "调拨入库"
            db.add(BatchCheckItem(batch_id=batch.id, transaction_id=transaction.id, snapshot_id=snapshot.id, target_label=f"{direction} {transaction.transaction_no} · {source}"))
    try:
        db.flush()
        add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="BATCH_CHECK", resource_id=batch.id, request_summary="建立批次库位核查清单", result_status="SUCCESS")
        db.commit()
    except IntegrityError:
        db.rollback()
        # Concurrent creation is idempotent because each batch/location pair is unique.
    return list_batch_checks(db, user, balance_id)


def update_batch_check(db: Session, user: User, balance_id: int, check_id: int, data: CheckItemUpdate) -> BatchCheckItem:
    batch = _batch_for_balance(db, user, balance_id)
    item = db.scalar(select(BatchCheckItem).where(BatchCheckItem.id == check_id, BatchCheckItem.batch_id == batch.id).with_for_update())
    if item is None:
        raise ResourceNotFoundError("批次核查项不存在")
    warehouse_id = item_warehouse_id(db, item)
    inventory_service._require_warehouse_scope(db, user, warehouse_id)
    values = data.model_dump(exclude_unset=True)
    if not values:
        raise BusinessValidationError("没有需要更新的核查内容")
    if "assignee_id" in values:
        assignee = db.get(User, data.assignee_id) if data.assignee_id is not None else None
        if data.assignee_id is not None and (assignee is None or assignee.status != "ACTIVE"):
            raise BusinessValidationError("核查负责人不存在或已停用")
        if assignee is not None:
            inventory_service._require_warehouse_scope(db, assignee, warehouse_id)
            if "SYS_ADMIN" not in system_crud.get_user_role_codes(db, assignee.id) and "warehouse.inventory.write" not in system_crud.get_user_permission_codes(db, assignee.id):
                raise BusinessValidationError("核查负责人没有库存操作权限")
        item.assignee_id = data.assignee_id
    if data.status is not None:
        allowed = {"OPEN": {"CHECKED", "NEEDS_ACTION"}, "CHECKED": {"VERIFIED", "NEEDS_ACTION", "OPEN"}, "NEEDS_ACTION": {"CHECKED", "OPEN"}, "VERIFIED": {"OPEN"}}
        if data.status not in allowed.get(item.status, set()):
            raise BusinessValidationError("核查项状态不能这样变更")
        if data.status != "OPEN" and not (data.finding or item.finding):
            raise BusinessValidationError("提交核查结果前请填写说明")
        if data.status in {"CHECKED", "NEEDS_ACTION"} and item.assignee_id not in {None, user.id}:
            raise BusinessValidationError("仅指派人员可提交核查结果")
        if data.status == "VERIFIED" and (item.status != "CHECKED" or item.checked_by == user.id):
            raise BusinessValidationError("复核人须与核查人不同，且核查项已提交")
        item.status = data.status
        if data.status == "VERIFIED":
            item.reviewed_by = user.id
            item.reviewed_at = datetime.now()
        elif data.status in {"CHECKED", "NEEDS_ACTION"}:
            item.checked_by = user.id
            item.checked_at = datetime.now()
            item.reviewed_by = None
            item.reviewed_at = None
        else:
            item.checked_by = None
            item.checked_at = None
            item.reviewed_by = None
            item.reviewed_at = None
    if "finding" in values:
        item.finding = data.finding
    db.add(BatchCheckEvent(check_id=item.id, actor_id=user.id, status=item.status, assignee_id=item.assignee_id, finding=item.finding))
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="BATCH_CHECK", resource_id=item.id, request_summary=f"批次核查项状态 {item.status}", result_status="SUCCESS")
    db.commit()
    db.refresh(item)
    return item
