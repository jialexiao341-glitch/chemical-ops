"""AI 助手 HTTP 接口。"""

import logging
from time import perf_counter

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_permission
from app.core.db import get_db
from app.core.errors import AuthorizationError, ResourceNotFoundError, BusinessValidationError
from app.core.observability import get_request_id, metrics, observe_duration
from app.modules.ai import briefing as briefing_service
from app.modules.ai import drafts as drafts_service
from app.modules.ai import nl_filters as nl_filters_service
from app.modules.ai import service, routing
from app.modules.ai import agent_tools
from app.modules.ai import agent_runtime
from app.modules.ai import text2sql as text2sql_service
from app.modules.ai.text2sql import Text2SQLRequest, Text2SQLResponse
from app.modules.ai.schema import (
    AIChatRequest,
    AIChatResponse,
    AIPurchaseDraftPreview,
    AIPurchaseDraftRequest,
    AIConversationPage,
    AIConversationRead,
    AIConversationUpdate,
    AIMessagePage,
    AIMessageRead,
    BriefingRequest,
    BriefingResponse,
    NLFilterRequest,
    NLFilterResult,
)
from app.modules.doc_kb.model import AiDocument, AiDocumentSection
from app.modules.system.model import User


router = APIRouter(
    prefix="/ai",
    tags=["AI 助手"],
    dependencies=[Depends(require_permission("ai.workspace.read"))],
)
LOGGER = logging.getLogger('chemicalops.ai.http')


@router.get("/agent/tools", summary="列出当前用户可用的只读 Agent 工具")
def agent_tool_catalog(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict[str, object]]:
    """返回认证用户可见的只读工具目录；无权限工具不出现在返回结果中。"""
    return agent_tools.list_tools(db, user)


@router.post("/route", summary="理解会话请求并生成受约束路由")
async def route_request(data: routing.RouteRequest, db: Session = Depends(get_db),
                        user: User = Depends(require_permission("ai.workspace.read"))) -> dict:
    """校验会话归属并理解当前请求，返回短期复用凭据；此接口不执行业务查询。"""
    context = routing.conversation_context(db, user, data.conversation_id)
    decision = await routing.understand(data.question, context)
    return {"route": decision.route, "understanding": decision.model_dump(mode="json"),
            "route_token": routing.issue_ticket(decision, user.id, data.question, data.conversation_id)}


@router.post("/agent/tools/execute", response_model=agent_tools.InventoryResult | agent_tools.QuoteResult | agent_tools.ProductSearchResult | agent_tools.RFQSearchResult,
             summary="执行白名单内的只读 Agent 工具")
def agent_tool_execute(data: agent_tools.ToolCall, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """通过统一护栏执行一个只读工具；身份来自 JWT，不接受请求指定执行人。"""
    return agent_tools.execute_tool(db, user, data)


@router.post("/agent/tasks", response_model=agent_runtime.TaskRead, summary="启动只读采购 Agent 任务")
async def agent_task_create(data: agent_runtime.TaskCreate, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    """按用户目标运行只读工具循环，返回任务 ID、状态、公开轨迹和来源。"""
    return await agent_runtime.create_task(db, user, data)


@router.get("/agent/tasks/{task_id}", response_model=agent_runtime.TaskRead, summary="查询本人 Agent 任务")
def agent_task_read(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """回看本人任务；再次检查当前权限和历史证据的资源范围。"""
    return agent_runtime.get_task(db, user, task_id)


@router.post("/agent/tasks/start", response_model=agent_runtime.TaskRead, status_code=202, summary="启动采购任务并立即返回编号")
def agent_task_start(data: agent_runtime.TaskCreate, background: BackgroundTasks,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return agent_runtime.schedule_async(db, user, background, agent_runtime.prepare_task, data)


@router.post("/agent/chat/start", response_model=agent_runtime.TaskRead, status_code=202, summary="在聊天会话中启动只读任务")
def agent_chat_start(data: agent_runtime.ChatTaskCreate, background: BackgroundTasks,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return agent_runtime.schedule_async(db, user, background, agent_runtime.prepare_chat_task, data)


@router.post("/agent/chat/{task_id}/continue", response_model=agent_runtime.TaskRead, status_code=202, summary="聊天补充并继续只读任务")
def agent_chat_continue(task_id: str, data: agent_runtime.TaskContinue, background: BackgroundTasks,
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return agent_runtime.schedule_async(db, user, background, agent_runtime.prepare_chat_continue, task_id, data)


@router.post("/agent/tasks/{task_id}/continue/start", response_model=agent_runtime.TaskRead, status_code=202,
             summary="补充采购任务并立即返回续跑状态")
def agent_task_continue_start(task_id: str, data: agent_runtime.TaskContinue, background: BackgroundTasks,
                              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return agent_runtime.schedule_async(db, user, background, agent_runtime.prepare_continue, task_id, data)


@router.post("/agent/tasks/{task_id}/continue", response_model=agent_runtime.TaskRead, summary="补充信息并继续 Agent 任务")
async def agent_task_continue(task_id: str, data: agent_runtime.TaskContinue, db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    """按版本号继续等待任务；仅接受已返回候选中的产品/询价明细选择。"""
    return await agent_runtime.continue_task(db, user, task_id, data)


@router.post("/agent/tasks/{task_id}/cancel", response_model=agent_runtime.TaskRead, summary="取消本人 Agent 任务")
def agent_task_cancel(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """取消运行或等待任务，并阻止旧运行者覆盖取消后的状态。"""
    return agent_runtime.cancel_task(db, user, task_id)


@router.post("/text2sql", response_model=Text2SQLResponse, summary="自然语言只读查询")
async def text2sql(data: Text2SQLRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Text2SQLResponse:
    """执行受白名单、权限和 SELECT-only 校验保护的自然语言查询。"""

    return await text2sql_service.run_text2sql(db, user, data)


@router.post("/briefing", response_model=BriefingResponse, summary="生成 AI 运营晨报")
async def briefing(data: BriefingRequest | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> BriefingResponse:
    """聚合 dashboard 指标生成中文晨报；push=true 时同时站内通知（默认 SYS_ADMIN 与 PROCUREMENT_MANAGER）。"""

    return await briefing_service.generate_briefing(db, user, data or BriefingRequest())


@router.post("/purchase-request-draft/preview", response_model=AIPurchaseDraftPreview, summary="生成需人工确认的采购申请草稿建议")
async def purchase_request_draft_preview(
    data: AIPurchaseDraftRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.requests.write")),
) -> AIPurchaseDraftPreview:
    """只返回候选字段；不写入申请、不提交审批。"""

    return await drafts_service.propose_purchase_request_draft(db, user, data.question)


@router.post("/parse-filters", response_model=NLFilterResult, summary="自然语言解析列表筛选条件")
async def parse_filters(data: NLFilterRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> NLFilterResult:
    """把自然语言解析成数据集白名单内的列表筛选参数；只产出条件，不执行查询。"""

    return await nl_filters_service.parse_filters(db, user, data)


@router.post("/chat", response_model=AIChatResponse, summary="调用 AI 助手")
async def chat_persisted(data: AIChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AIChatResponse:
    """调用 AI 模型并将用户消息、助手回复保存到当前用户会话。"""

    user_query = next((message.content for message in reversed(data.messages) if message.role == "user"), "")
    started = perf_counter()
    LOGGER.info("AI HTTP 请求 mode=sync request_id=%s user_id=%s conversation_id=%s attachments=%s query_length=%s", get_request_id(), user.id, data.conversation_id or "new", len(data.attachment_file_ids), len(user_query))
    with observe_duration("ai_request_duration_seconds", labels={"mode": "sync"}):
        try:
            result = await service.chat_for_user(db, user, data)
            metrics.increment("ai_requests", labels={"mode": "sync", "status": "success", "model": result.model})
            metrics.observe("ai_response_bytes", len((result.answer or result.message.content).encode("utf-8")), labels={"mode": "sync", "model": result.model})
            if result.usage and isinstance(result.usage.get("total_tokens"), int):
                metrics.increment("ai_tokens", labels={"mode": "sync", "model": result.model}, value=result.usage["total_tokens"])
        except Exception as exc:
            metrics.increment("ai_requests", labels={"mode": "sync", "status": "failure"})
            LOGGER.warning("AI HTTP 失败 mode=sync request_id=%s user_id=%s duration_ms=%.2f error_type=%s", get_request_id(), user.id, (perf_counter() - started) * 1000, exc.__class__.__name__)
            raise
    LOGGER.info("AI HTTP 回复 mode=sync request_id=%s user_id=%s conversation_id=%s model=%s duration_ms=%.2f status=success answer_length=%s", get_request_id(), user.id, result.conversation_id, result.model, (perf_counter() - started) * 1000, len(result.answer or result.message.content))
    return result


@router.post("/chat/stream", summary="流式调用 AI 助手")
async def chat_stream(data: AIChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> StreamingResponse:
    """以 SSE 增量返回模型内容，正常结束后保存完整助手消息。"""

    user_query = next((message.content for message in reversed(data.messages) if message.role == "user"), "")
    LOGGER.info("AI HTTP 请求 mode=stream user_id=%s conversation_id=%s attachments=%s query_length=%s", user.id, data.conversation_id or "new", len(user_query))
    metrics.increment("ai_requests", labels={"mode": "stream", "status": "started"})
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


@router.patch("/conversations/{conversation_id}", response_model=AIConversationRead, summary="管理 AI 会话")
def update_conversation(conversation_id: int, data: AIConversationUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AIConversationRead:
    """重命名或置顶当前用户自己的会话。"""
    updated = service.update_conversation(db, user, conversation_id, title=data.title, pinned=data.pinned)
    return AIConversationRead.model_validate(updated)


@router.get("/conversations/{conversation_id}/messages", response_model=AIMessagePage, summary="查询 AI 会话消息")
def messages(conversation_id: int, limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AIMessagePage:
    """只读取当前用户自己的 AI 会话消息。"""

    items, total = service.list_messages(db, user, conversation_id, limit=limit)
    LOGGER.info("AI HTTP 历史消息 user_id=%s conversation_id=%s count=%s", user.id, conversation_id, total)
    result = []
    for item in items:
        citations = item.citations
        agent_ref = next((c for c in (citations or []) if isinstance(c, dict) and c.get("type") == "agent_task"), None)
        content = item.content
        batch_ref = next((c for c in (citations or []) if isinstance(c, dict) and c.get("type") == "multi_intent"), None)
        if batch_ref and item.message_role == "ASSISTANT":
            from app.modules.ai.multi_intent import history_accessible
            if not history_accessible(db, user, batch_ref.get("batch")):
                content, citations = "这组查询的权限、范围或数据已变化，请重新查询。", []
        if agent_ref and item.message_role == "ASSISTANT":
            # 先重查任务权限；不从历史消息绕过证据鉴权返回旧库存/价格摘要。
            try:
                agent_runtime.get_task(db, user, agent_ref["task_id"])
            except (AuthorizationError, ResourceNotFoundError, BusinessValidationError):
                content = "任务结果当前不可访问，请核对权限或服务状态。"
        if isinstance(citations, list):
            normalized = []
            for citation in citations:
                if not isinstance(citation, dict) or citation.get("type") != "doc_kb":
                    normalized.append(citation)
                    continue
                section_id = citation.get("section_id")
                document_id = citation.get("document_id")
                current = None
                if isinstance(section_id, int) and isinstance(document_id, int):
                    current = db.execute(
                        select(AiDocument.parse_status)
                        .join(AiDocumentSection, AiDocumentSection.document_id == AiDocument.id)
                        .where(AiDocument.id == document_id, AiDocumentSection.id == section_id)
                    ).scalar_one_or_none()
                source_status = (
                    "unverified"
                    if not isinstance(section_id, int) or not isinstance(document_id, int)
                    else "available" if current == "PARSED" else "missing"
                )
                normalized.append({**citation, "source_status": source_status})
            citations = normalized
        result.append(
            AIMessageRead(
                id=item.id,
                conversation_id=item.conversation_id,
                role=item.message_role.lower(),
                content=content,
                citations=citations,
                created_at=item.created_at,
            )
        )
    return AIMessagePage(items=result, total=total)


@router.delete("/conversations/{conversation_id}", summary="删除 AI 会话")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, object]:
    """只允许删除当前用户自己的会话及消息。"""

    service.delete_conversation(db, user, conversation_id)
    return {"deleted": True, "conversation_id": conversation_id}


@router.delete("/conversations/{conversation_id}/query-context", summary="清空 AI 查询上下文")
def clear_query_context(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, object]:
    """清空当前会话的结构化 QueryPlan，保留历史消息和审计引用。"""

    service.clear_query_context(db, user, conversation_id)
    return {"cleared": True, "conversation_id": conversation_id}
