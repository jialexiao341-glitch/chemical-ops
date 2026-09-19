"""AI 助手 HTTP 接口。"""

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.modules.ai import service
from app.modules.ai import text2sql as text2sql_service
from app.modules.ai.text2sql import Text2SQLRequest, Text2SQLResponse
from app.modules.ai.schema import AIChatRequest, AIChatResponse, AIConversationPage, AIConversationRead, AIMessagePage, AIMessageRead
from app.modules.system.model import User


router = APIRouter(prefix="/ai", tags=["AI 助手"])
LOGGER = logging.getLogger('chemicalops.ai.http')


@router.post("/text2sql", response_model=Text2SQLResponse, summary="自然语言只读查询")
async def text2sql(data: Text2SQLRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Text2SQLResponse:
    """执行受白名单、权限和 SELECT-only 校验保护的自然语言查询。"""

    return await text2sql_service.run_text2sql(db, user, data)


@router.post("/chat", response_model=AIChatResponse, summary="调用 AI 助手")
async def chat_persisted(data: AIChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AIChatResponse:
    """调用 AI 模型并将用户消息、助手回复保存到当前用户会话。"""

    user_query = next((message.content for message in reversed(data.messages) if message.role == "user"), "")
    LOGGER.info("AI HTTP 请求 mode=sync user_id=%s conversation_id=%s attachments=%s query=%s", user.id, data.conversation_id or "new", len(data.attachment_file_ids), user_query[:300])
    result = await service.chat_for_user(db, user, data)
    LOGGER.info("AI HTTP 回复 mode=sync user_id=%s conversation_id=%s model=%s answer=%s", user.id, result.conversation_id, result.model, (result.answer or result.message.content)[:300])
    return result


@router.post("/chat/stream", summary="流式调用 AI 助手")
async def chat_stream(data: AIChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> StreamingResponse:
    """以 SSE 增量返回模型内容，正常结束后保存完整助手消息。"""

    user_query = next((message.content for message in reversed(data.messages) if message.role == "user"), "")
    LOGGER.info("AI HTTP 请求 mode=stream user_id=%s conversation_id=%s attachments=%s query=%s", user.id, data.conversation_id or "new", len(data.attachment_file_ids), user_query[:300])
    return StreamingResponse(
        service.stream_chat_for_user(db, user, data),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=AIConversationPage, summary="查询 AI 会话")
def conversations(limit: int = Query(default=50, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AIConversationPage:
    """只返回当前用户自己的 AI 会话。"""

    items, total = service.list_conversations(db, user, limit=limit)
    LOGGER.info("AI HTTP 历史会话 user_id=%s count=%s", user.id, total)
    return AIConversationPage(items=[AIConversationRead.model_validate(item) for item in items], total=total)


@router.get("/conversations/{conversation_id}/messages", response_model=AIMessagePage, summary="查询 AI 会话消息")
def messages(conversation_id: int, limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AIMessagePage:
    """只读取当前用户自己的 AI 会话消息。"""

    items, total = service.list_messages(db, user, conversation_id, limit=limit)
    LOGGER.info("AI HTTP 历史消息 user_id=%s conversation_id=%s count=%s", user.id, conversation_id, total)
    result = [AIMessageRead(id=item.id, conversation_id=item.conversation_id, role=item.message_role.lower(), content=item.content, citations=item.citations, created_at=item.created_at) for item in items]
    return AIMessagePage(items=result, total=total)


@router.delete("/conversations/{conversation_id}", summary="删除 AI 会话")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, object]:
    """只允许删除当前用户自己的会话及消息。"""

    service.delete_conversation(db, user, conversation_id)
    return {"deleted": True, "conversation_id": conversation_id}
