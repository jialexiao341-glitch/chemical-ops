"""文件模块请求和响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FileRead(BaseModel):
    """文件元数据响应。"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    file_name: str
    object_key: str
    mime_type: str
    file_size_bytes: int
    sha256_hash: str
    file_category: str
    access_level: str
    uploader_id: int
    parse_status: str
    parse_error: str | None
    uploaded_at: datetime
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FileAttachmentCreate(BaseModel):
    """创建业务附件关联时提交的字段。"""
    resource_type: str = Field(pattern="^(PURCHASE_ORDER|DELIVERY|QUALITY_ACCEPTANCE|OPERATION_EXCEPTION|FINANCE_INVOICE|INVENTORY_RETURN|REPLENISHMENT)$")
    resource_id: int = Field(gt=0)


class FileAttachmentRead(BaseModel):
    """业务附件关联响应。"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    file_id: int
    resource_type: str
    resource_id: int
    created_by: int
    created_at: datetime


class FileAttachmentPage(BaseModel):
    """业务附件分页响应。"""
    items: list[FileAttachmentRead]
    total: int
    page: int
    page_size: int
