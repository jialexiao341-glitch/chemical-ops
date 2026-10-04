"""后台任务运行历史的响应模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class TechnicalDocumentPipelineCreate(BaseModel):
    cas_no: str = Field(pattern=r"^\d{2,7}-\d{2}-\d$")
    doc_types: list[str] = Field(min_length=1, max_length=2)

    @field_validator("doc_types")
    @classmethod
    def validate_doc_types(cls, value: list[str]) -> list[str]:
        if not value or len(set(value)) != len(value) or any(item not in {"msds", "tds"} for item in value):
            raise ValueError("资料类型仅支持 MSDS 或 TDS")
        return value


class TechnicalDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cas_no: str
    doc_type: str
    title: str | None
    name_zh: str | None
    source_bucket: str
    object_key: str
    source_url: str | None
    parse_status: str
    reject_reason: str | None
    section_count: int
    char_count: int
    sha256: str | None
    updated_at: datetime


class TechnicalDocumentSourceRead(BaseModel):
    cas_no: str
    char_count: int
    doc_id: int | None
    doc_type: str
    extension: str
    file_size: int
    ingestible: bool
    name_zh: str | None
    object_key: str
    parse_status: str
    reject_reason: str | None
    section_count: int
    source_bucket: str
    title: str | None
    updated_at: datetime | None


class TechnicalDocumentSectionPreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    section_no: int | None
    section_key: str
    title: str | None
    content: str
    char_count: int


class TechnicalDocumentPreviewRead(TechnicalDocumentRead):
    meta_json: dict[str, Any] | None
    sections: list[TechnicalDocumentSectionPreview]
