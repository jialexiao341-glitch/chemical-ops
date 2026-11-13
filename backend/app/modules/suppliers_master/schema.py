"""供应商接口的 Pydantic 请求和响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SupplierCreate(BaseModel):
    """创建供应商主数据时允许提交的字段。"""

    supplier_code: str = Field(min_length=1, max_length=64)
    supplier_name: str = Field(min_length=1, max_length=255)
    unified_credit_code: str | None = Field(default=None, max_length=64)
    country_code: str = Field(default="CN", min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=128)
    address: str | None = Field(default=None, max_length=500)
    business_scope: str | None = None
    cooperation_level: str | None = Field(default=None, max_length=20)
    payment_terms: str | None = Field(default=None, max_length=255)
    default_lead_days: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=1000)


class SupplierUpdate(BaseModel):
    """部分更新接口允许提交的可选字段。"""

    supplier_name: str | None = Field(default=None, min_length=1, max_length=255)
    unified_credit_code: str | None = Field(default=None, max_length=64)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=128)
    address: str | None = Field(default=None, max_length=500)
    business_scope: str | None = None
    cooperation_level: str | None = Field(default=None, max_length=20)
    payment_terms: str | None = Field(default=None, max_length=255)
    default_lead_days: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern="^(ACTIVE|SUSPENDED|INACTIVE)$")
    note: str | None = Field(default=None, max_length=1000)


class SupplierRead(SupplierCreate):
    """包含系统生成字段的供应商响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_at: datetime
    updated_at: datetime


class SupplierPage(BaseModel):
    """分页供应商列表响应。"""

    items: list[SupplierRead]
    total: int
    page: int
    page_size: int
