"""AI 助手调用服务。"""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import BusinessValidationError
from app.modules.ai.agent_prompt import GREETING_REPLY, SYSTEM_PROMPT as AGENT_SYSTEM_PROMPT, UNSUPPORTED_REPLY, build_project_reply
from app.modules.ai.intent import Intent, classify_intent
from app.modules.ai.model import AIConversation, AIMessage
from app.modules.ai.schema import AIChatMessage, AIChatRequest, AIChatResponse, AIQueryTrace
from app.modules.files import service as file_service
from app.modules.files import mineru
from app.modules.files.parser import parse_file_content
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


LOGGER = logging.getLogger("chemicalops.ai")
SYSTEM_PROMPT = AGENT_SYSTEM_PROMPT
STREAM_CHUNK_SIZE = 4
STREAM_CHUNK_DELAY_SECONDS = 0.03
READ_ONLY_WRITE_MARKERS = (
    "帮我创建", "帮我修改", "帮我删除", "帮我提交", "帮我审批", "帮我驳回",
    "帮我下单", "帮我入库", "帮我出库", "帮我付款", "帮我执行",
    "请创建", "请修改", "请删除", "请提交", "请审批", "请驳回",
    "请下单", "请入库", "请出库", "请付款", "请执行",
    "直接创建", "直接修改", "直接提交", "直接审批", "直接下单",
    "直接入库", "直接出库", "直接付款", "直接执行",
)


def _build_llm_payload(runtime: Settings, messages: list[dict[str, object]], *, stream: bool = False, response_format: dict[str, str] | None = None) -> dict[str, object]:
    """组装 OpenAI 兼容请求；DeepSeek Flash 默认支持思考模式，显式开启以获得完整回答。"""

    payload: dict[str, object] = {
        "model": runtime.llm_model,
        "messages": messages,
        "temperature": runtime.llm_temperature,
        "max_tokens": runtime.llm_max_tokens,
    }
    if runtime.llm_model.lower() == "deepseek-flash":
        payload["thinking"] = {"type": "enabled"}
    if stream:
        payload["stream"] = True
    if response_format is not None:
        payload["response_format"] = response_format
    return payload


async def _stream_text_chunks(content: str) -> AsyncIterator[str]:
    """把已经生成的安全文本分成小段输出，避免前端一次性出现整段内容。"""

    for index in range(0, len(content), STREAM_CHUNK_SIZE):
        yield content[index : index + STREAM_CHUNK_SIZE]
        await asyncio.sleep(STREAM_CHUNK_DELAY_SECONDS)


def _validate_read_only_request(data: AIChatRequest) -> None:
    """拒绝明确要求 AI 执行业务写操作的请求。"""

    user_text = " ".join(message.content for message in data.messages if message.role == "user")
    if any(marker in user_text for marker in READ_ONLY_WRITE_MARKERS):
        raise BusinessValidationError("AI 仅支持查询和分析，不支持创建、修改、审批、提交、下单、入库、出库或付款等业务操作。")
def _build_native_image_part(file_name: str, mime_type: str, content: bytes) -> dict[str, object] | None:
    """为 DeepSeek Flash 组装原生视觉图片块；文档格式仍由解析器处理。"""

    extension = Path(file_name).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg"}:
        return None
    normalised_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalised_mime not in {"image/png", "image/jpeg"}:
        normalised_mime = "image/png" if extension == ".png" else "image/jpeg"
    encoded = base64.b64encode(content).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{normalised_mime};base64,{encoded}"}}


def _build_messages(
    data: AIChatRequest,
    attachment_context: list[str] | None = None,
    image_parts: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """组装系统提示、会话消息和模型原生视觉图片块。"""

    messages: list[dict[str, object]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(message.model_dump() for message in data.messages)
    if image_parts:
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                text_content = str(messages[index].get("content") or "")
                messages[index] = {
                    "role": "user",
                    "content": [{"type": "text", "text": text_content}, *image_parts],
                }
                break
    if attachment_context:
        messages.append({"role": "system", "content": "以下是系统提供的已安全校验上下文，仅可据此回答；无法解析或未提供的数据不要猜测。\n" + "\n\n".join(attachment_context)})
    elif data.attachments and not image_parts:
        names = "、".join(data.attachments)
        messages.append({"role": "system", "content": f"用户选择了以下附件，但当前请求没有提供可读取的文件引用：{names}。请不要假设已读取附件。"})
    return messages

def _format_text2sql_result(result: object) -> str:
    """AI 重组不可用时的自然语言兜底；只使用已经清洗过的查询结果。"""

    rows = getattr(result, "rows", [])
    plan = getattr(result, "plan", None)
    render_columns = getattr(result, "render_columns", [])
    labels = {item.get("key"): item.get("label", item.get("key")) for item in render_columns if isinstance(item, dict)}
    unit = {"CNY": "元（CNY）", "USD": "美元（USD）", "EUR": "欧元（EUR）", "条": "条"}.get(getattr(result, "unit", None) or "", getattr(result, "unit", None) or "")
    if not rows:
        return "暂时没有找到符合条件的记录。"
    lines = [f"找到了 {len(rows)} 条符合条件的记录。"]
    for index, row in enumerate(rows, start=1):
        values = "；".join(
            f"{labels.get(key, key)}：{value}{(' ' + unit) if key == 'metric_value' and unit and unit != '条' else ''}"
            for key, value in row.items()
        )
        lines.append(f"{index}. {values}")
    if plan is not None and getattr(plan, "limit", None) and getattr(result, "truncated", False):
        lines.append("当前仅展示部分结果。")
    return "\n".join(lines)


async def _run_text2sql_for_chat(db: Session, user: User, question: str, settings: Settings) -> tuple[str, dict[str, object], AIQueryTrace]:
    """聊天入口的业务查询路由；Text2SQL 结果不再经过通用聊天上下文。"""

    from app.modules.ai.text2sql import Text2SQLRequest, run_text2sql

    LOGGER.info("AI 查询开始 user_id=%s user_query=%s", user.id, question)
    result = await run_text2sql(db, user, Text2SQLRequest(question=question), settings)
    trace = AIQueryTrace(
        query=result.question,
        slots=result.slots,
        template=result.template,
        sql=result.sql,
        parameterized_sql=result.parameterized_sql,
        columns=result.render_columns,
        rows=result.rows,
        unit=result.unit,
        unit_note=result.unit_note,
        row_count=result.row_count,
        truncated=result.truncated,
        stages=result.stages,
        render=result.render,
    )
    answer = _format_text2sql_result(result)
    trace.answer = answer
    LOGGER.info("AI 查询槽位 user_id=%s slots=%s", user.id, json.dumps(result.slots, ensure_ascii=False, default=str))
    LOGGER.info("AI 查询模板 user_id=%s template=%s", user.id, result.template)
    LOGGER.info("AI 生成 SQL user_id=%s sql=%s", user.id, " ".join(result.sql.split()))
    LOGGER.info(
        "AI 查询完成 user_id=%s row_count=%s truncated=%s unit=%s",
        user.id,
        result.row_count,
        result.truncated,
        result.unit or "未提供",
    )
    LOGGER.info("AI 回复答案 user_id=%s answer=%s", user.id, answer)
    citation = {
        "type": "text2sql",
        "source": "实时数据库只读查询",
        "row_count": result.row_count,
        "stages": result.stages,
        "query_trace": trace.model_dump(mode="json"),
    }
    return answer, citation, trace


async def chat(data: AIChatRequest, settings: Settings | None = None, attachment_context: list[str] | None = None, response_format: dict[str, str] | None = None, image_parts: list[dict[str, object]] | None = None) -> AIChatResponse:
    """调用配置的 OpenAI 兼容模型。"""

    _validate_read_only_request(data)
    runtime = settings or get_settings()
    if not runtime.agent_enabled:
        raise BusinessValidationError("AI 助手当前未启用")
    if not runtime.openai_api_key.strip():
        raise BusinessValidationError("AI API key 尚未配置，请先填写 .env")
    if runtime.llm_provider != "openai_compatible":
        raise BusinessValidationError(f"暂不支持的 AI 服务商：{runtime.llm_provider}")

    url = f"{runtime.openai_base_url.rstrip('/')}/chat/completions"
    payload = _build_llm_payload(runtime, _build_messages(data, attachment_context, image_parts), response_format=response_format)
    headers = {"Authorization": f"Bearer {runtime.openai_api_key}", "Content-Type": "application/json"}
    attempts = max(0, runtime.llm_max_retries) + 1
    response: httpx.Response | None = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=runtime.llm_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            break
        except httpx.TimeoutException as exc:
            if attempt == attempts - 1:
                LOGGER.warning("AI 服务请求超时，已重试 %s 次", attempt)
                raise BusinessValidationError("AI 服务响应超时，请稍后重试") from exc
        except httpx.RequestError as exc:
            if attempt == attempts - 1:
                LOGGER.warning("AI 服务网络请求失败：%s", exc.__class__.__name__)
                raise BusinessValidationError("AI 服务暂时不可用，请检查网络或稍后重试") from exc
        except httpx.HTTPStatusError as exc:
            LOGGER.warning("AI 服务返回 HTTP %s", exc.response.status_code)
            raise BusinessValidationError("AI 服务拒绝了请求，请检查 API key、模型和额度配置") from exc

    if response is None:
        raise BusinessValidationError("AI 服务没有返回结果")
    try:
        result = response.json()
        raw_message = result["choices"][0]["message"]
        content = str(raw_message.get("content") or "").strip()
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise BusinessValidationError("AI 服务返回了无法识别的结果") from exc
    if not content:
        raise BusinessValidationError("AI 服务返回了空答案")

    usage = result.get("usage")
    normalized_usage = usage if isinstance(usage, dict) and all(isinstance(value, int) for value in usage.values()) else None
    return AIChatResponse(
        message=AIChatMessage(role="assistant", content=content),
        conversation_id=data.conversation_id or 0,
        model=runtime.llm_model,
        provider=runtime.llm_provider,
        usage=normalized_usage,
        user_query=next((message.content for message in reversed(data.messages) if message.role == "user"), None),
        answer=content,
    )


def _get_owned_conversation(db: Session, user: User, conversation_id: int) -> AIConversation:
    """读取当前用户自己的会话，其他用户的会话按不存在处理。"""

    conversation = db.scalar(select(AIConversation).where(AIConversation.id == conversation_id, AIConversation.user_id == user.id))
    if conversation is None:
        raise BusinessValidationError("AI 会话不存在或无权访问")
    return conversation


def delete_conversation(db: Session, user: User, conversation_id: int) -> None:
    """删除当前用户自己的会话及其消息。"""
    conversation = _get_owned_conversation(db, user, conversation_id)
    db.execute(delete(AIMessage).where(AIMessage.conversation_id == conversation.id))
    db.delete(conversation)
    db.commit()

def list_conversations(db: Session, user: User, *, limit: int = 50) -> tuple[list[AIConversation], int]:
    """按最近消息时间返回当前用户会话。"""

    condition = AIConversation.user_id == user.id
    total = db.scalar(select(func.count(AIConversation.id)).where(condition)) or 0
    items = list(db.scalars(select(AIConversation).where(condition).order_by(AIConversation.last_message_at.desc(), AIConversation.id.desc()).limit(limit)).all())
    return items, total


def list_messages(db: Session, user: User, conversation_id: int, *, limit: int = 100) -> tuple[list[AIMessage], int]:
    """读取当前用户会话消息。"""

    _get_owned_conversation(db, user, conversation_id)
    condition = AIMessage.conversation_id == conversation_id
    total = db.scalar(select(func.count(AIMessage.id)).where(condition)) or 0
    items = list(db.scalars(select(AIMessage).where(condition).order_by(AIMessage.created_at.asc(), AIMessage.id.asc()).limit(limit)).all())
    return items, total


def _ensure_conversation(db: Session, user: User, data: AIChatRequest) -> AIConversation:
    """获取或创建会话，并保存权限快照。"""

    if data.conversation_id:
        return _get_owned_conversation(db, user, data.conversation_id)
    first_user = next((message.content.strip() for message in data.messages if message.role == "user" and message.content.strip()), "新建对话")
    conversation = AIConversation(
        user_id=user.id,
        title=first_user[:80],
        business_scene="GENERAL",
        permission_snapshot={"roles": get_user_role_codes(db, user.id), "permissions": get_user_permission_codes(db, user.id)},
        status="ACTIVE",
        last_message_at=datetime.now(),
    )
    db.add(conversation)
    db.flush()
    return conversation


async def chat_for_user(db: Session, user: User, data: AIChatRequest) -> AIChatResponse:
    """持久化用户消息并调用模型，再持久化助手回复。"""

    _validate_read_only_request(data)

    conversation = _ensure_conversation(db, user, data)
    user_message = next((message for message in reversed(data.messages) if message.role == "user"), None)
    if user_message is None:
        raise BusinessValidationError("至少需要一条用户消息")
    LOGGER.info("AI 请求进入 mode=sync user_id=%s user_query=%s", user.id, user_message.content)
    intent_result = classify_intent(user_message.content)
    LOGGER.info("AI 意图识别 mode=sync user_id=%s intent=%s reason=%s", user.id, intent_result.intent, intent_result.reason)
    if intent_result.intent is Intent.QUERY and not data.attachment_file_ids:
        runtime = get_settings()
        content, citation, query_trace = await _run_text2sql_for_chat(db, user, user_message.content, runtime)
        citations = [citation]
        db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=citations))
        db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=content, citations=citations))
        conversation.last_message_at = datetime.now()
        db.commit()
        return AIChatResponse(
            message=AIChatMessage(role="assistant", content=content),
            conversation_id=conversation.id,
            model="text2sql",
            provider="chemicalops",
            citations=citations,
            query_trace=query_trace,
            query_slots=query_trace.slots,
            user_query=user_message.content,
            answer=content,
        )
    if intent_result.intent != Intent.QUERY and not data.attachment_file_ids:
        fixed_content = build_project_reply(user_message.content) if intent_result.intent is Intent.PROJECT else {Intent.GREETING: GREETING_REPLY, Intent.UNSUPPORTED: UNSUPPORTED_REPLY}[intent_result.intent]
        LOGGER.info("AI 固定回复 user_id=%s intent=%s user_query=%s answer=%s", user.id, intent_result.intent, user_message.content, fixed_content)
        db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content))
        db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=fixed_content))
        conversation.last_message_at = datetime.now()
        db.commit()
        return AIChatResponse(message=AIChatMessage(role="assistant", content=fixed_content), conversation_id=conversation.id, model="rule-based", provider="chemicalops", citations=None, user_query=user_message.content, answer=fixed_content)

    attachment_context: list[str] = []
    native_image_parts: list[dict[str, object]] = []
    attachment_citations: list[dict[str, object]] = []
    runtime = get_settings()
    for file_id in dict.fromkeys(data.attachment_file_ids):
        value = file_service.get_file(db, user, file_id)
        if value.uploader_id != user.id and "SYS_ADMIN" not in get_user_role_codes(db, user.id):
            raise BusinessValidationError("只能将自己上传的文件提交给 AI 分析")
        if len(attachment_context) >= 20:
            break
        try:
            _, content = file_service.read_file(db, user, file_id)
            extension = Path(value.file_name).suffix.lower()
            native_image = _build_native_image_part(value.file_name, value.mime_type, content) if runtime.llm_model.lower() == 'deepseek-flash' else None
            if native_image is not None:
                native_image_parts.append(native_image)
                value.parse_status = 'SUCCEEDED'
                value.parse_error = None
                attachment_citations.append({'file_id': value.id, 'file_name': value.file_name, 'source': '用户上传附件', 'parse_status': 'SUCCEEDED', 'parser': 'native-vision', 'references': []})
                continue
            if runtime.mineru_enabled and extension in mineru.SUPPORTED_REMOTE_EXTENSIONS:
                value.parse_status = "PROCESSING"
                value.parse_error = None
                db.commit()
                try:
                    parsed = await asyncio.to_thread(mineru.parse_bytes, value.file_name, content, runtime)
                except mineru.MinerUParseError:
                    LOGGER.warning("MinerU 附件解析失败，回退本地解析 file_id=%s", file_id)
                    parsed = parse_file_content(value.file_name, value.mime_type, content)
            else:
                parsed = parse_file_content(value.file_name, value.mime_type, content)
            value.parse_status = parsed.status
            value.parse_error = parsed.error
            attachment_citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": parsed.status, "parser": parsed.parser, "references": parsed.references})
            if parsed.text:
                attachment_context.append(f"附件：{value.file_name}\n{parsed.text[:12_000]}")
                try:
                    result_key = file_service.store_parse_result(value.id, parsed.text)
                    if result_key:
                        attachment_citations.append({"type": "parsed_result", "file_id": value.id, "object_key": result_key, "source": "解析结果 Markdown"})
                except Exception as exc:
                    LOGGER.warning("解析结果保存失败 file_id=%s error=%s", value.id, exc.__class__.__name__)
            else:
                attachment_context.append(f"附件：{value.file_name}\n{parsed.error or '文件没有可解析正文，请不要猜测其内容。'}")
        except Exception as exc:
            LOGGER.warning("AI 附件读取失败 file_id=%s error=%s", file_id, exc.__class__.__name__)
            value.parse_status = "FAILED"
            value.parse_error = "文件解析失败，请检查文件格式或重新上传"
            attachment_context.append(f"附件：{value.file_name}\n文件读取失败，请不要基于该附件推断业务结论。")
            attachment_citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": "FAILED", "parser": "none", "references": []})
    combined_context = attachment_context
    combined_citations = attachment_citations
    db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=combined_citations or None))
    conversation.last_message_at = datetime.now()
    db.commit()
    try:
        result = await chat(data, runtime, attachment_context=combined_context or None, image_parts=native_image_parts or None)
    except Exception:
        raise
    assistant_message = AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=result.message.content, citations=combined_citations or None)
    db.add(assistant_message)
    conversation.last_message_at = datetime.now()
    db.commit()
    result.conversation_id = conversation.id
    result.citations = combined_citations or None
    result.user_query = user_message.content
    result.answer = result.message.content
    return result


async def stream_chat_for_user(db: Session, user: User, data: AIChatRequest) -> AsyncIterator[str]:
    """通过 SSE 转发 OpenAI 兼容接口的增量内容，并在结束时持久化。"""

    _validate_read_only_request(data)

    conversation = _ensure_conversation(db, user, data)
    user_message = next((message for message in reversed(data.messages) if message.role == "user"), None)
    if user_message is None:
        yield f"event: error\ndata: {json.dumps({'message': '至少需要一条用户消息'}, ensure_ascii=False)}\n\n"
        return
    LOGGER.info("AI 请求进入 mode=stream user_id=%s user_query=%s", user.id, user_message.content)
    stream_intent_result = classify_intent(user_message.content)
    LOGGER.info("AI 意图识别 mode=stream user_id=%s intent=%s reason=%s", user.id, stream_intent_result.intent, stream_intent_result.reason)
    if stream_intent_result.intent is Intent.QUERY and not data.attachment_file_ids:
        runtime = get_settings()
        try:
            content, citation, query_trace = await _run_text2sql_for_chat(db, user, user_message.content, runtime)
        except BusinessValidationError as exc:
            LOGGER.warning("AI 流式查询业务失败 user_id=%s user_query=%s error=%s", user.id, user_message.content, exc)
            yield f"event: error\ndata: {json.dumps({'message': str(exc)}, ensure_ascii=False)}\n\n"
            return
        except Exception:
            LOGGER.exception("AI 流式查询异常 user_id=%s user_query=%s", user.id, user_message.content)
            yield f"event: error\ndata: {json.dumps({'message': f'查询暂时失败，请稍后重试'}, ensure_ascii=False)}\n\n"
            return
        citations = [citation]
        db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=citations))
        db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=content, citations=citations))
        conversation.last_message_at = datetime.now()
        db.commit()
        chunk_count = 0
        async for chunk in _stream_text_chunks(content):
            chunk_count += 1
            yield f"event: delta\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
        LOGGER.info("AI 流式回复完成 user_id=%s mode=query chunks=%s", user.id, chunk_count)
        trace_payload = query_trace.model_dump(mode="json")
        yield f"event: done\ndata: {json.dumps({'conversation_id': conversation.id, 'model': 'text2sql', 'provider': 'chemicalops', 'citations': citations, 'query_trace': trace_payload, 'query_slots': trace_payload['slots'], 'user_query': user_message.content, 'answer': content}, ensure_ascii=False)}\n\n"
        return
    if stream_intent_result.intent != Intent.QUERY and not data.attachment_file_ids:
        fixed_content = build_project_reply(user_message.content) if stream_intent_result.intent is Intent.PROJECT else {Intent.GREETING: GREETING_REPLY, Intent.UNSUPPORTED: UNSUPPORTED_REPLY}[stream_intent_result.intent]
        LOGGER.info("AI 流式固定回复开始 user_id=%s intent=%s user_query=%s", user.id, stream_intent_result.intent, user_message.content)
        db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content))
        db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=fixed_content))
        conversation.last_message_at = datetime.now()
        db.commit()
        chunk_count = 0
        async for chunk in _stream_text_chunks(fixed_content):
            chunk_count += 1
            yield "event: delta\ndata: " + json.dumps({"content": chunk}, ensure_ascii=False) + "\n\n"
        LOGGER.info("AI 流式回复完成 user_id=%s mode=rule_based chunks=%s answer=%s", user.id, chunk_count, fixed_content)
        yield "event: done\ndata: " + json.dumps({"conversation_id": conversation.id, "model": "rule-based", "provider": "chemicalops", "citations": None, "user_query": user_message.content, "answer": fixed_content}, ensure_ascii=False) + "\n\n"
        return

    runtime = get_settings()
    attachment_context: list[str] = []
    native_image_parts: list[dict[str, object]] = []
    citations: list[dict[str, object]] = []
    for file_id in dict.fromkeys(data.attachment_file_ids):
        value = file_service.get_file(db, user, file_id)
        if value.uploader_id != user.id and "SYS_ADMIN" not in get_user_role_codes(db, user.id):
            yield f"event: error\ndata: {json.dumps({'message': '只能将自己上传的文件提交给 AI 分析'}, ensure_ascii=False)}\n\n"
            return
        try:
            _, content = file_service.read_file(db, user, file_id)
            extension = Path(value.file_name).suffix.lower()
            native_image = _build_native_image_part(value.file_name, value.mime_type, content) if runtime.llm_model.lower() == 'deepseek-flash' else None
            if native_image is not None:
                native_image_parts.append(native_image)
                value.parse_status = 'SUCCEEDED'
                value.parse_error = None
                citations.append({'file_id': value.id, 'file_name': value.file_name, 'source': '用户上传附件', 'parse_status': 'SUCCEEDED', 'parser': 'native-vision', 'references': []})
                continue
            if runtime.mineru_enabled and extension in mineru.SUPPORTED_REMOTE_EXTENSIONS:
                value.parse_status = "PROCESSING"
                value.parse_error = None
                db.commit()
                try:
                    parsed = await asyncio.to_thread(mineru.parse_bytes, value.file_name, content, runtime)
                except mineru.MinerUParseError:
                    parsed = parse_file_content(value.file_name, value.mime_type, content)
            else:
                parsed = parse_file_content(value.file_name, value.mime_type, content)
            value.parse_status = parsed.status
            value.parse_error = parsed.error
            citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": parsed.status, "parser": parsed.parser, "references": parsed.references})
            attachment_context.append(f"附件：{value.file_name}\n{(parsed.text or parsed.error or '文件没有可解析正文，请不要猜测其内容。')[:12_000]}")
            if parsed.text:
                try:
                    result_key = file_service.store_parse_result(value.id, parsed.text)
                    if result_key:
                        citations.append({"type": "parsed_result", "file_id": value.id, "object_key": result_key, "source": "解析结果 Markdown"})
                except Exception as exc:
                    LOGGER.warning("流式解析结果保存失败 file_id=%s error=%s", value.id, exc.__class__.__name__)
        except Exception as exc:
            LOGGER.warning("AI 流式附件读取失败 file_id=%s error=%s", file_id, exc.__class__.__name__)
            attachment_context.append(f"附件：{value.file_name}\n文件读取失败，请不要基于该附件推断业务结论。")
            citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": "FAILED", "parser": "none", "references": []})
    combined_context = attachment_context
    db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=citations or None))
    conversation.last_message_at = datetime.now()
    db.commit()

    if not runtime.agent_enabled or not runtime.openai_api_key.strip() or runtime.llm_provider != "openai_compatible":
        yield f"event: error\ndata: {json.dumps({'message': 'AI 服务配置不可用，请检查服务开关、API key 和服务商配置'}, ensure_ascii=False)}\n\n"
        return
    url = f"{runtime.openai_base_url.rstrip('/')}/chat/completions"
    payload = _build_llm_payload(runtime, _build_messages(data, combined_context or None, native_image_parts or None), stream=True)
    headers = {"Authorization": f"Bearer {runtime.openai_api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    full_content = ""
    try:
        async with httpx.AsyncClient(timeout=runtime.llm_timeout_seconds) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                    except (ValueError, TypeError, IndexError, KeyError):
                        continue
                    if delta:
                        full_content += delta
                        yield f"event: delta\ndata: {json.dumps({'content': delta}, ensure_ascii=False)}\n\n"
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        LOGGER.warning("AI SSE 请求失败 error=%s", exc.__class__.__name__)
        yield f"event: error\ndata: {json.dumps({'message': 'AI 服务暂时不可用，请稍后重试'}, ensure_ascii=False)}\n\n"
        return
    if not full_content.strip():
        yield f"event: error\ndata: {json.dumps({'message': 'AI 服务返回了空答案'}, ensure_ascii=False)}\n\n"
        return
    db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=full_content.strip(), citations=citations or None))
    conversation.last_message_at = datetime.now()
    db.commit()
    LOGGER.info("AI 流式回复完成 user_id=%s mode=llm chunks=streamed user_query=%s answer=%s", user.id, user_message.content, full_content.strip())
    done = {"conversation_id": conversation.id, "model": runtime.llm_model, "provider": runtime.llm_provider, "citations": citations or None, "user_query": user_message.content, "answer": full_content.strip()}
    yield f"event: done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"