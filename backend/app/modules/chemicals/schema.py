"""化学品接口的 Pydantic 请求和响应模型。"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ChemicalCreate(BaseModel):
    """创建化学品主数据时允许提交的字段。"""

    chemical_name: str = Field(min_length=1, max_length=255)
    english_name: str | None = Field(default=None, max_length=255)
    alias_text: str | None = None
    cas_no: str | None = Field(default=None, max_length=32)
    chemical_formula: str | None = Field(default=None, max_length=128)
    molecular_weight: Decimal | None = Field(default=None, ge=0)
    hazard_class: str | None = Field(default=None, max_length=128)
    source_text: str | None = Field(default=None, max_length=500)


class ChemicalUpdate(BaseModel):
    """部分更新接口允许提交的可选字段。"""

    chemical_name: str | None = Field(default=None, min_length=1, max_length=255)
    english_name: str | None = Field(default=None, max_length=255)
    alias_text: str | None = None
    cas_no: str | None = Field(default=None, max_length=32)
    chemical_formula: str | None = Field(default=None, max_length=128)
    molecular_weight: Decimal | None = Field(default=None, ge=0)
    hazard_class: str | None = Field(default=None, max_length=128)
    source_text: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern="^(ACTIVE|INACTIVE)$")


class ChemicalRead(ChemicalCreate):
    """包含系统生成字段的化学品响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_at: datetime
    updated_at: datetime


class ChemicalPage(BaseModel):
    """分页化学品列表响应。"""

    items: list[ChemicalRead]
    total: int
    page: int
    page_size: int
