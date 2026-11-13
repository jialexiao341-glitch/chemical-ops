"""任务队列运行进展的管理员视图。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.errors import AuthorizationError
from app.modules.system_management import crud
from app.modules.system_management.model import User
from app.modules.task_queue.progress import scan_progress


router = APIRouter(prefix="/system/task-queue", tags=["任务队列"])


class TaskProgressItem(BaseModel):
    execution_id: str
    task_type: str
    business_id: str
    status: str
    verdict: str
    recommendation: str
    reasons: list[str]
    queued_seconds: int | None = None
    running_seconds: int | None = None
    heartbeat_age_seconds: int | None = None
    last_progress_seconds: int | None = None
    decisions: int | None = None
    failures: int | None = None
    attempt_count: int = 0
    token_used: int | None = None
    token_limit: int | None = None
    llm_seconds: float | None = None
    tool_seconds: float | None = None


class TaskProgressOverview(BaseModel):
    checked_at: datetime
    total: int
    attention: int
    items: list[TaskProgressItem]


@router.get("/progress", response_model=TaskProgressOverview, summary="查看活动任务进展诊断")
def get_task_progress(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskProgressOverview:
    """只返回确定性诊断；不触发取消、恢复或业务写入。"""

    if "SYS_ADMIN" not in crud.get_user_role_codes(db, user.id):
        raise AuthorizationError("仅系统管理员可以查看任务进展")
    diagnoses = scan_progress(db)
    items = []
    for diagnosis in diagnoses:
        payload = diagnosis.as_dict()
        payload["reasons"] = list(diagnosis.reasons)
        items.append(TaskProgressItem(**payload))
    return TaskProgressOverview(
        checked_at=datetime.now(timezone.utc),
        total=len(items),
        attention=sum(item.verdict != "OK" for item in items),
        items=items,
    )