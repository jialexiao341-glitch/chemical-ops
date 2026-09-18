"""质量验收接口的请求与响应模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QualityAcceptanceCreate(BaseModel):
    """创建质量验收记录时提交的字段。"""

    delivery_id: int = Field(gt=0)


class QualityAcceptanceResult(BaseModel):
    """提交质量检测结果时的字段。"""

    result: str = Field(pattern="^(PASSED|PARTIAL|FAILED|REINSPECTION)$")
    test_result: dict[str, Any] | list[Any] | None = None
    certificate_complete: bool = False
    report_file_id: int | None = Field(default=None, gt=0)
    conclusion: str | None = Field(default=None, max_length=2000)


class QualityAcceptanceRead(BaseModel):
    """质量验收响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    acceptance_no: str
    delivery_id: int
    inspector_id: int
    result: str
    inspection_time: datetime | None
    test_result: dict | list | None
    certificate_complete: int
    report_file_id: int | None
    conclusion: str | None
    created_at: datetime
    updated_at: datetime


class QualityAcceptancePage(BaseModel):
    """质量验收分页响应。"""

    items: list[QualityAcceptanceRead]
    total: int
    page: int
    page_size: int
