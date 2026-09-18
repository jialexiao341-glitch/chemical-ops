"""AI 助手 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.modules.ai import service
from app.modules.ai.schema import AIChatRequest, AIChatResponse, AIConversationPage, AIConversationRead, AIMessagePage, AIMessageRead
from app.modules.system.model import User


router = APIRouter(prefix="/ai", tags=["AI 助手"])


@router.post("/chat", response_model=AIChatResponse, summary="调用 AI 助手")
async def chat_persisted(data: AIChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AIChatResponse:
    """调用 AI 模型并将用户消息、助手回复保存到当前用户会话。"""

    return await service.chat_for_user(db, user, data)


@router.post("/chat/stream", summary="流式调用 AI 助手")
async def chat_stream(data: AIChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> StreamingResponse:
    """以 SSE 增量返回模型内容，正常结束后保存完整助手消息。"""

    return StreamingResponse(
        service.stream_chat_for_user(db, user, data),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=AIConversationPage, summary="查询 AI 会话")
def conversations(limit: int = Query(default=50, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AIConversationPage:
    """只返回当前用户自己的 AI 会话。"""

    items, total = service.list_conversations(db, user, limit=limit)
    return AIConversationPage(items=[AIConversationRead.model_validate(item) for item in items], total=total)


@router.get("/conversations/{conversation_id}/messages", response_model=AIMessagePage, summary="查询 AI 会话消息")
def messages(conversation_id: int, limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AIMessagePage:
    """只读取当前用户自己的 AI 会话消息。"""

    items, total = service.list_messages(db, user, conversation_id, limit=limit)
    result = [AIMessageRead(id=item.id, conversation_id=item.conversation_id, role=item.message_role.lower(), content=item.content, citations=item.citations, created_at=item.created_at) for item in items]
    return AIMessagePage(items=result, total=total)
