"""Business outcome updates share the execution transaction."""

from sqlalchemy import select, update

from app.modules.task_queue import service
from app.modules.task_queue.model import TaskExecution


def apply_business_status(db, execution: TaskExecution):
    if execution.task_type.startswith("documents."):
        from app.modules.jobs.model import SchedulerJobRun
        row = db.scalar(select(SchedulerJobRun).where(SchedulerJobRun.run_id == execution.business_id))
        if row:
            row.status = execution.status if execution.status != "WAITING_INPUT" else "SUCCEEDED"
            row.attempt_count = execution.attempt_count
            row.error_type = execution.error_code
            row.finished_at = service.now() if execution.status in service.TERMINAL else None
    else:
        from app.modules.ai.model import AIAgentTask
        status = "RUNNING" if execution.status in {"RETRYING", "QUEUED", "RECOVERING"} else execution.status
        db.execute(update(AIAgentTask).where(AIAgentTask.id == execution.business_id,
            AIAgentTask.user_id == execution.actor_id, AIAgentTask.status == "RUNNING",
            AIAgentTask.revision == execution.business_revision).values(
                status=status, error_code=execution.error_code,
                reply="任务执行失败，请检查服务状态后重新发起。" if status == "FAILED" else "正在查询业务数据…"))


def finish(db, execution_id, token, **outcome):
    execution = service.finish(db, execution_id, token, **outcome)
    apply_business_status(db, execution)
    db.commit()
    return execution
