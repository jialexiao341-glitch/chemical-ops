"""催办接口只接受提案引用或供应商回复，不接收业务快照。"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FollowupSend(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation_id: str = Field(min_length=32, max_length=32, pattern=r'^[a-fA-F0-9]{32}$')
    preview_version: int = Field(gt=0, strict=True)
    confirm: bool = Field(strict=True)

    @field_validator('confirm')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('发送需要明确确认')
        return value


class FollowupReply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    message: str = Field(min_length=1, max_length=1000)
    expected_date: date | None = None

    @field_validator('message')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('请填写回复说明')
        return value.strip()


class FollowupRead(BaseModel):
    id: int
    order_id: int
    po_no: str
    message: str
    status: str
    sent_at: datetime
    replied_at: datetime | None
    reply_message: str | None
    reply_expected_date: date | None
    can_reply: bool


class FollowupPage(BaseModel):
    items: list[FollowupRead]
    total: int
    page: int
    page_size: int
