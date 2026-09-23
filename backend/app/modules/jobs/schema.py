"""后台任务运行历史的响应模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class SchedulerJobRunRead(BaseModel):
    """单次后台任务运行记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: str
    task_name: str
    status: str
    attempt_count: int
    started_at: datetime
    finished_at: datetime | None
    result_json: dict[str, Any] | None
    error_type: str | None
