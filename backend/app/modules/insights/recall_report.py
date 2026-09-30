"""Immutable, permission-scoped inventory recall drill reports."""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.insights import checks
from app.modules.insights.source_matching import match_sources, transfer_pairs
from app.modules.insights.model import BatchCheckItem, InsightSnapshot, RecallReportEvent, RecallReportWorkflow
from app.modules.inventory import service as inventory_service
from app.modules.inventory.model import (
    InventoryBalance,
    InventoryTransaction,
)
from app.modules.system.model import User
from app.modules.system import crud as system_crud
from app.modules.system.audit import add_audit_log


class WorkflowInput(BaseModel):
    action: str = Field(pattern="^(ASSIGN|SUBMIT|RETURN|COMPLETE)$")
    owner_id: int | None = Field(default=None, gt=0)
    conclusion: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)


class ReportEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: int
    actor_name: str
    action: str
    status: str
    owner_id: int | None
    conclusion: str | None
    review_reason: str | None
    created_at: datetime


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    owner_id: int | None = None
    owner_name: str | None = None
    status: str = "DRAFT"
    conclusion: str | None = None
    submitted_by: int | None = None
    submitted_by_name: str | None = None
    submitted_at: datetime | None = None
    review_reason: str | None = None
    reviewed_by: int | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    completed_at: datetime | None = None
    events: list[ReportEventRead] = Field(default_factory=list)


class ReportRead(checks.SnapshotRead):
    workflow: WorkflowRead


def build_report(db: Session, user: User, balance_id: int) -> dict:
    selected = inventory_service._require_balance_for_user(db, user, balance_id)
    batch = checks._batch_for_balance(db, user, balance_id)
    scope = inventory_service.accessible_warehouse_ids(db, user)
    all_balances = db.scalars(select(InventoryBalance).where(InventoryBalance.batch_id == batch.id).order_by(InventoryBalance.id)).all()
    all_transactions = db.scalars(select(InventoryTransaction).where(InventoryTransaction.batch_id == batch.id).order_by(InventoryTransaction.id)).all()
    visible_balances = [row for row in all_balances if scope is None or row.warehouse_id in scope]
    visible_transactions = [row for row in all_transactions if scope is None or row.warehouse_id in scope]
    hidden = len(visible_balances) != len(all_balances) or len(visible_transactions) != len(all_transactions)
    current_checks = checks.list_batch_checks(db, user, balance_id)
    by_balance = {row.balance_id: row for row in current_checks if row.balance_id is not None}
    by_transaction = {row.transaction_id: row for row in current_checks if row.transaction_id is not None}
    matches = match_sources(db, visible_transactions)
    pairs = transfer_pairs(db, batch.id, scope, visible_transactions, matches)
    for pair in pairs:
        ids = pair["outbound_ids"] + pair["inbound_ids"]
        pair["review_status"] = "VERIFIED" if pair["status"] == "MATCHED" and all(tx_id in by_transaction and by_transaction[tx_id].status == "VERIFIED" for tx_id in ids) else "PENDING"

    slot_movements: dict[tuple[int, int, int], Decimal] = defaultdict(Decimal)
    unknown_slots: set[tuple[int, int, int]] = set()
    transfers: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    missing_sources = sum(row["status"] == "MISSING" for row in matches.values())
    conflict_sources = sum(row["status"] not in {"MATCHED", "MISSING"} for row in matches.values())
    for tx in visible_transactions:
        key = (tx.warehouse_id, tx.location_id, tx.unit_id)
        if tx.transaction_type == "INBOUND":
            signed = tx.quantity
        elif tx.transaction_type == "OUTBOUND":
            signed = -tx.quantity
        else:
            matched = matches[tx.id]
            signed = Decimal(matched["signed_quantity"]) if matched["status"] == "MATCHED" else None
        if signed is None:
            unknown_slots.add(key)
        else:
            slot_movements[key] += signed
            if tx.source_type == "INVENTORY_TRANSFER" and tx.source_id:
                transfers[(tx.source_id, tx.unit_id)] += signed

    slots = []
    for row in visible_balances:
        key = (row.warehouse_id, row.location_id, row.unit_id)
        calculated = slot_movements.pop(key, Decimal(0))
        status = "UNKNOWN" if key in unknown_slots else "MATCHED" if calculated == row.quantity else "DIFFERENCE"
        unknown_slots.discard(key)
        slots.append({
            "balance_id": row.id, "warehouse_id": row.warehouse_id, "location_id": row.location_id,
            "unit_id": row.unit_id, "quantity": str(row.quantity), "locked_quantity": str(row.locked_quantity),
            "movement_net": str(calculated), "difference": None if status == "UNKNOWN" else str(row.quantity - calculated),
            "status": status, "check_status": by_balance[row.id].status if row.id in by_balance else "NOT_CREATED",
        })
    for warehouse_id, location_id, unit_id in sorted(slot_movements.keys() | unknown_slots):
        key = (warehouse_id, location_id, unit_id)
        slots.append({
            "balance_id": None, "warehouse_id": warehouse_id, "location_id": location_id,
            "unit_id": unit_id, "quantity": None, "locked_quantity": None,
            "movement_net": str(slot_movements.get(key, Decimal(0))), "difference": None,
            "status": "MISSING_BALANCE", "check_status": "NOT_CREATED",
        })

    outflows = []
    for tx in visible_transactions:
        if tx.transaction_type != "OUTBOUND":
            continue
        matched = matches[tx.id]
        check = by_transaction.get(tx.id)
        outflows.append({
            "transaction_id": tx.id, "transaction_no": tx.transaction_no, "warehouse_id": tx.warehouse_id,
            "location_id": tx.location_id, "unit_id": tx.unit_id, "quantity": str(tx.quantity),
            "source_type": tx.source_type, "source_id": tx.source_id, "source_found": matched["status"] != "MISSING",
            "source_status": matched["status"], "source_item_id": matched["item_id"], "source_reason": matched["reason"],
            "check_status": check.status if check else "NOT_CREATED", "finding": check.finding if check else None,
        })

    transfer_differences = [
        {"request_id": request_id, "unit_id": unit_id, "net": str(net)}
        for (request_id, unit_id), net in sorted(transfers.items()) if net != 0
    ]
    open_checks = sum(item.status != "VERIFIED" for item in current_checks)
    missing_checks = sum(row["check_status"] == "NOT_CREATED" for row in slots + outflows)
    missing_checks += sum(tx.transaction_type == "INBOUND" and tx.source_type == "INVENTORY_TRANSFER" and tx.id not in by_transaction for tx in visible_transactions)
    issues = []
    if hidden:
        issues.append("当前权限无法覆盖此批次的全部仓库记录，不能判定全批次数量守恒。")
    if missing_sources:
        issues.append(f"{missing_sources} 条可见流水缺少可识别的来源单据。")
    if conflict_sources:
        issues.append(f"{conflict_sources} 条可见流水的来源明细冲突、重复或无法唯一匹配。")
    if any(pair["status"] != "MATCHED" or pair["review_status"] != "VERIFIED" for pair in pairs):
        issues.append("调拨两端仍有未匹配或未复核的明细。")
    if transfer_differences:
        issues.append("部分调拨在可见范围内的出入库数量不一致；跨权限仓库调拨需由有权限的人员核查。")
    if any(row["status"] != "MATCHED" for row in slots):
        issues.append("部分库位数量不一致、流水方向不明或缺少余额记录。")
    if open_checks or missing_checks:
        issues.append("核查清单仍有未创建或未经双人复核的对象。")
    issues.append("系统外使用和客户去向不在本报告的数据范围内；演练报告不代表已执行召回。")
    return {
        "version": 2,
        "kind": "batch-recall-report", "balance_id": selected.id, "batch_id": batch.id, "batch_no": batch.batch_no,
        "warehouse_ids": sorted({row.warehouse_id for row in visible_balances + visible_transactions}),
        "visible_transaction_count": len(visible_transactions), "missing_source_count": missing_sources,
        "conflict_source_count": conflict_sources, "source_matches": list(matches.values()), "transfer_pairs": pairs,
        "open_check_count": open_checks, "missing_check_count": missing_checks,
        "status": "READY_FOR_REVIEW" if len(issues) == 1 else "INCOMPLETE",
        "slots": slots, "outflows": outflows, "transfer_differences": transfer_differences, "limitations": issues,
        "checks": [{"id": item.id, "balance_id": item.balance_id, "transaction_id": item.transaction_id,
                    "assignee_id": item.assignee_id, "status": item.status, "finding": item.finding,
                    "checked_by": item.checked_by, "reviewed_by": item.reviewed_by,
                    "checked_at": item.checked_at.isoformat() if item.checked_at else None,
                    "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None}
                   for item in current_checks],
    }


def save_report(db: Session, user: User, balance_id: int) -> InsightSnapshot:
    result = build_report(db, user, balance_id)
    report = InsightSnapshot(kind="batch-recall-report", object_id=balance_id, result_json=result, created_by=user.id)
    db.add(report)
    db.flush()
    db.add(RecallReportWorkflow(snapshot_id=report.id, owner_id=user.id if _can_handle(db, user, report) else None))
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="RECALL_REPORT", resource_id=report.id, request_summary="保存召回演练报告", result_status="SUCCESS")
    db.commit()
    db.refresh(report)
    return report


def _can_handle(db: Session, user: User, report: InsightSnapshot) -> bool:
    if user.status != "ACTIVE":
        return False
    if "SYS_ADMIN" not in system_crud.get_user_role_codes(db, user.id) and not {"warehouse.inventory.read", "warehouse.inventory.write"} <= set(system_crud.get_user_permission_codes(db, user.id)):
        return False
    scope = inventory_service.accessible_warehouse_ids(db, user)
    return scope is None or set(report.result_json.get("warehouse_ids", [])) <= scope


def _visible(db: Session, user: User, report: InsightSnapshot) -> bool:
    scope = inventory_service.accessible_warehouse_ids(db, user)
    if scope is not None and not set(report.result_json.get("warehouse_ids", [])) <= scope:
        return False
    workflow = db.get(RecallReportWorkflow, report.id)
    return report.created_by == user.id or (workflow is not None and (
        user.id in {workflow.owner_id, workflow.reviewed_by}
        or workflow.status == "SUBMITTED" and _can_handle(db, user, report)
    ))


def list_reports(db: Session, user: User, balance_id: int) -> list[InsightSnapshot]:
    checks._batch_for_balance(db, user, balance_id)
    reports = db.scalars(select(InsightSnapshot).where(InsightSnapshot.kind == "batch-recall-report", InsightSnapshot.object_id == balance_id).order_by(InsightSnapshot.id.desc())).all()
    return [row for row in reports if _visible(db, user, row)][:20]


def get_report(db: Session, user: User, balance_id: int, report_id: int) -> InsightSnapshot:
    checks._batch_for_balance(db, user, balance_id)
    report = db.get(InsightSnapshot, report_id)
    if report is None or report.kind != "batch-recall-report" or report.object_id != balance_id or not _visible(db, user, report):
        raise ResourceNotFoundError("召回演练报告不存在")
    return report


def read_report(db: Session, report: InsightSnapshot) -> ReportRead:
    def name(user_id: int | None) -> str | None:
        person = db.get(User, user_id) if user_id else None
        return person.display_name if person else None
    workflow = db.get(RecallReportWorkflow, report.id)
    data = WorkflowRead.model_validate(workflow) if workflow else WorkflowRead()
    data.owner_name = name(data.owner_id)
    data.submitted_by_name = name(data.submitted_by)
    data.reviewed_by_name = name(data.reviewed_by)
    data.events = [ReportEventRead(**{**{key: getattr(event, key) for key in ReportEventRead.model_fields if key != "actor_name"}, "actor_name": name(event.actor_id) or f"用户 #{event.actor_id}"})
                   for event in db.scalars(select(RecallReportEvent).where(RecallReportEvent.snapshot_id == report.id).order_by(RecallReportEvent.id)).all()]
    return ReportRead(**checks.SnapshotRead.model_validate(report).model_dump(), workflow=data)


def list_owners(db: Session, user: User, balance_id: int, report_id: int) -> list[dict]:
    report = get_report(db, user, balance_id, report_id)
    return [{"id": person.id, "name": person.display_name} for person in db.scalars(select(User).where(User.status == "ACTIVE").order_by(User.display_name)).all() if _can_handle(db, person, report)]


def _require_ready(db: Session, user: User, report: InsightSnapshot) -> None:
    if report.result_json.get("version") != 2 or report.result_json.get("status") != "READY_FOR_REVIEW":
        raise BusinessValidationError("报告仍有未处理差异或未完成核查，请完成处理后重新生成报告")
    batch_id = report.result_json["batch_id"]
    # Serialize signing with writes to this batch's balances, movements and checks.
    for model in (InventoryBalance, InventoryTransaction, BatchCheckItem):
        db.scalars(select(model).where(model.batch_id == batch_id).with_for_update().execution_options(populate_existing=True)).all()
    def normalized(value):
        # MySQL may return 0.000000 for a value originally represented as 0.
        quantities = {"quantity", "locked_quantity", "movement_net", "difference", "net", "expected_quantity", "signed_quantity", "outbound_quantity", "inbound_quantity"}
        if isinstance(value, dict):
            return {key: Decimal(item) if key in quantities and item is not None else normalized(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalized(item) for item in value]
        return value
    if normalized(build_report(db, user, report.object_id)) != normalized(report.result_json):
        raise BusinessValidationError("业务记录或核查状态已变化，请重新生成报告再提交或确认")


def update_workflow(db: Session, user: User, balance_id: int, report_id: int, data: WorkflowInput) -> InsightSnapshot:
    report = get_report(db, user, balance_id, report_id)
    db.scalar(select(InsightSnapshot).where(InsightSnapshot.id == report.id).with_for_update())
    workflow = db.scalar(select(RecallReportWorkflow).where(RecallReportWorkflow.snapshot_id == report.id).with_for_update().execution_options(populate_existing=True))
    if workflow is None:
        workflow = RecallReportWorkflow(snapshot_id=report.id, status="DRAFT")
        db.add(workflow)
    if not _can_handle(db, user, report):
        raise BusinessValidationError("没有覆盖报告全部仓库的库存处理权限")
    if workflow.status == "COMPLETED":
        raise BusinessValidationError("已完成的报告不能修改确认记录")
    if data.action == "ASSIGN":
        if workflow.status not in {"DRAFT", "RETURNED"} or user.id not in {report.created_by, workflow.owner_id}:
            raise BusinessValidationError("仅创建者或负责人可在提交前指派负责人")
        person = db.get(User, data.owner_id) if data.owner_id else None
        if person is None or not _can_handle(db, person, report):
            raise BusinessValidationError("负责人须拥有报告全部仓库的库存处理权限")
        workflow.owner_id = person.id
    elif data.action == "SUBMIT":
        if workflow.status not in {"DRAFT", "RETURNED"} or workflow.owner_id != user.id:
            raise BusinessValidationError("仅负责人可提交待确认的报告")
        if not data.conclusion or not data.conclusion.strip():
            raise BusinessValidationError("请填写最终核查结论")
        _require_ready(db, user, report)
        workflow.status = "SUBMITTED"
        workflow.conclusion = data.conclusion.strip()
        workflow.submitted_by = user.id
        workflow.submitted_at = datetime.now()
        workflow.reviewed_by = None
        workflow.reviewed_at = None
        workflow.review_reason = None
    else:
        if workflow.status != "SUBMITTED" or user.id in {workflow.owner_id, workflow.submitted_by}:
            raise BusinessValidationError("须由另一名有权限的人员复核已提交报告")
        if not data.reason or not data.reason.strip():
            raise BusinessValidationError("请填写复核意见")
        if data.action == "COMPLETE":
            _require_ready(db, user, report)
        workflow.status = "COMPLETED" if data.action == "COMPLETE" else "RETURNED"
        workflow.review_reason = data.reason.strip()
        workflow.reviewed_by = user.id
        workflow.reviewed_at = datetime.now()
        workflow.completed_at = workflow.reviewed_at if data.action == "COMPLETE" else None
    db.add(RecallReportEvent(snapshot_id=report.id, actor_id=user.id, action=data.action, status=workflow.status, owner_id=workflow.owner_id, conclusion=workflow.conclusion, review_reason=workflow.review_reason))
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="RECALL_REPORT", resource_id=report.id, request_summary=f"召回演练报告 {data.action}", result_status="SUCCESS")
    db.commit()
    return report
