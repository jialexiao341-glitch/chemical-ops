"""AI 助手请求与响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AIChatMessage(BaseModel):
    """一条 OpenAI 兼容格式的对话消息。"""

    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=20_000)


class AIChatRequest(BaseModel):
    """AI 对话请求；附件通过文件 ID 关联到当前用户已上传的文件。"""

    messages: list[AIChatMessage] = Field(min_length=1, max_length=50)
    attachments: list[str] = Field(default_factory=list, max_length=20)
    attachment_file_ids: list[int] = Field(default_factory=list, max_length=20)
    conversation_id: int | None = Field(default=None, gt=0)


class AIChatResponse(BaseModel):
    """AI 对话响应。"""

    message: AIChatMessage
    conversation_id: int
    model: str
    provider: str
    usage: dict[str, int] | None = None
    citations: list | None = None


class AIConversationRead(BaseModel):
    """会话列表摘要。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    business_scene: str
    status: str
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AIConversationPage(BaseModel):
    """当前用户可访问的会话列表。"""

    items: list[AIConversationRead]
    total: int


class AIMessageRead(BaseModel):
    """会话消息。"""

    id: int
    conversation_id: int
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    citations: list | None
    created_at: datetime


class AIMessagePage(BaseModel):
    """会话消息分页结果。"""

    items: list[AIMessageRead]
    total: int
