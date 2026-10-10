"""Turn a reviewed exception suggestion into one existing operation task."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.insights.model import ExceptionActionDecision, ExceptionActionEvent, InsightSnapshot
from app.modules.operation_exceptions import service as exception_service
from app.modules.operation_exceptions.model import OperationTask
from app.modules.system.audit import add_audit_log
from app.modules.system.model import User


class DecisionInput(BaseModel):
    decision: str = Field(pattern="^(ADOPTED|REJECTED)$")
    reason: str = Field(min_length=1, max_length=2000)


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exception_id: int
    snapshot_id: int
    decision: str
    reason: str
    task_id: int | None
    actor_id: int


class DecisionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    decision_id: int
    snapshot_id: int
    decision: str
    reason: str
    task_id: int | None
    actor_id: int
    created_at: datetime


ACTION_TITLES = {
    "INVENTORY_EXPIRY": "核查临期批次影响与处置方案",
    "LOW_STOCK": "核查可用库存、在途量与缺口",
    "OVERDUE": "核实供应商交期与受影响订单",
    "QUALITY_PENDING": "核实待验收报告与处理时限",
    "QUALITY": "核实质量差异与受影响批次",
    "SHORT_DELIVERY": "核实短交数量与补交安排",
    "DOCUMENT": "核实缺失资料与补齐责任人",
}


def proposed_title(exception_type: str) -> str:
    return ACTION_TITLES.get(exception_type, "核实异常来源、影响及处理办法")


def get_decision(db: Session, user: User, exception_id: int) -> ExceptionActionDecision | None:
    exception_service.get_exception(db, user, exception_id)
    return db.scalar(select(ExceptionActionDecision).where(ExceptionActionDecision.exception_id == exception_id))


def list_events(db: Session, user: User, exception_id: int) -> list[ExceptionActionEvent]:
    decision = get_decision(db, user, exception_id)
    if decision is None:
        return []
    return list(db.scalars(select(ExceptionActionEvent).where(ExceptionActionEvent.decision_id == decision.id).order_by(ExceptionActionEvent.id)).all())


def decide(db: Session, user: User, exception_id: int, data: DecisionInput, result: dict) -> ExceptionActionDecision:
    if not data.reason.strip():
        raise BusinessValidationError("请填写采纳或驳回原因")
    exception = exception_service.get_exception(db, user, exception_id, for_update=True)
    if exception.owner_id != user.id and not exception_service._has_source_exception_scope(db, user, exception):
        raise ResourceNotFoundError(f"异常 {exception_id} 不存在")
    if exception.status in {"CLOSED", "CANCELLED"}:
        raise BusinessValidationError("已关闭或已取消的异常不能处理建议")
    decision = db.scalar(select(ExceptionActionDecision).where(ExceptionActionDecision.exception_id == exception.id).with_for_update())
    if decision is not None and decision.decision == data.decision:
        return decision
    if decision is not None and decision.decision == "ADOPTED":
        task = db.get(OperationTask, decision.task_id)
        if task is not None and task.status != "CANCELLED":
            raise BusinessValidationError("建议已关联处理任务，请先完成或取消该任务")
    if data.decision == "ADOPTED":
        if exception.owner_id is None:
            raise BusinessValidationError("请先在异常详情指定负责人")
        exception_service._validate_assignee(db, user, exception.owner_id)
    snapshot = InsightSnapshot(kind="exception-action", object_id=exception.id, result_json=result, created_by=user.id)
    db.add(snapshot)
    db.flush()
    task_id = None
    if data.decision == "ADOPTED":
        priority = "URGENT" if exception.severity == "CRITICAL" else "HIGH" if exception.severity == "HIGH" else "NORMAL"
        task = OperationTask(exception_id=exception.id, title=proposed_title(exception.exception_type), assignee_id=exception.owner_id, priority=priority, due_at=exception.due_at)
        db.add(task)
        db.flush()
        task_id = task.id
        if exception.status in {"OPEN", "RESOLVED"}:
            exception.status = "PROCESSING"
        add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="OPERATION_TASK", resource_id=task.id, request_summary="采纳处置建议并建立处理任务", result_status="SUCCESS")
    if decision is None:
        decision = ExceptionActionDecision(exception_id=exception.id, snapshot_id=snapshot.id, decision=data.decision, reason=data.reason.strip(), task_id=task_id, actor_id=user.id)
        db.add(decision)
        db.flush()
    else:
        decision.snapshot_id = snapshot.id
        decision.decision = data.decision
        decision.reason = data.reason.strip()
        decision.task_id = task_id
        decision.actor_id = user.id
    db.add(ExceptionActionEvent(decision_id=decision.id, snapshot_id=snapshot.id, decision=data.decision, reason=data.reason.strip(), task_id=task_id, actor_id=user.id))
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="EXCEPTION_ACTION", resource_id=decision.id, request_summary=f"处置建议 {data.decision}", result_status="SUCCESS")
    db.commit()
    db.refresh(decision)
    return decision
