"""产品接口的 Pydantic 请求和响应模型。"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UnitRead(BaseModel):
    """前端展示和表单选择使用的计量单位。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    unit_code: str
    unit_name: str
    dimension: str
    status: str


class ProductCreate(BaseModel):
    """创建产品规格时允许提交的字段。"""

    product_code: str = Field(min_length=1, max_length=64)
    product_name: str = Field(min_length=1, max_length=255)
    chemical_id: int = Field(gt=0)
    category_id: int | None = Field(default=None, gt=0)
    model: str | None = Field(default=None, max_length=128)
    purity_value: Decimal | None = Field(default=None, ge=0, le=100)
    purity_unit: str | None = Field(default="%", max_length=20)
    packaging_spec: str | None = Field(default=None, max_length=255)
    unit_id: int = Field(gt=0)
    parameter_json: dict[str, Any] | None = None


class ProductUpdate(BaseModel):
    """部分更新接口允许提交的可选字段。"""

    product_name: str | None = Field(default=None, min_length=1, max_length=255)
    chemical_id: int | None = Field(default=None, gt=0)
    category_id: int | None = Field(default=None, gt=0)
    model: str | None = Field(default=None, max_length=128)
    purity_value: Decimal | None = Field(default=None, ge=0, le=100)
    purity_unit: str | None = Field(default=None, max_length=20)
    packaging_spec: str | None = Field(default=None, max_length=255)
    unit_id: int | None = Field(default=None, gt=0)
    parameter_json: dict[str, Any] | None = None
    status: str | None = Field(default=None, pattern="^(ACTIVE|INACTIVE|PENDING_CONFIRMATION)$")


class ProductRead(ProductCreate):
    """包含系统生成字段的产品响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    version_no: int
    status: str
    created_at: datetime
    updated_at: datetime


class ProductPage(BaseModel):
    """分页产品列表响应。"""

    items: list[ProductRead]
    total: int
    page: int
    page_size: int
