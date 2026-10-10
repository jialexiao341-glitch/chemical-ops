"""OpenAI 兼容模型通信：消息组装、只读护栏、重试与响应解析。

不依赖会话持久化、业务查询或 Agent 执行模块。
"""

import asyncio
import logging
import json
from collections.abc import AsyncIterator
from time import perf_counter
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import BusinessValidationError
from app.core.observability import metrics
from app.modules.ai.schema import (
    AIChatMessage,
    AIChatRequest,
    AIChatResponse,
)
from app.modules.ai.agent_prompt import SYSTEM_PROMPT

LOGGER = logging.getLogger("chemicalops.ai")


READ_ONLY_WRITE_MARKERS = (
    "帮我创建", "帮我修改", "帮我删除", "帮我提交", "帮我审批", "帮我驳回",
    "帮我下单", "帮我入库", "帮我出库", "帮我付款", "帮我执行",
    "请创建", "请修改", "请删除", "请提交", "请审批", "请驳回",
    "请下单", "请入库", "请出库", "请付款", "请执行",
    "直接创建", "直接修改", "直接提交", "直接审批", "直接下单",
    "直接入库", "直接出库", "直接付款", "直接执行",
)


def _build_llm_payload(runtime: Settings, messages: list[dict[str, object]], *, stream: bool = False, response_format: dict[str, object] | None = None) -> dict[str, object]:
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


def _validate_read_only_request(data: AIChatRequest) -> None:
    """拒绝明确要求 AI 执行业务写操作的请求。"""

    user_text = " ".join(message.content for message in data.messages if message.role == "user")
    if any(marker in user_text for marker in READ_ONLY_WRITE_MARKERS):
        raise BusinessValidationError("AI 仅支持查询和分析，不支持创建、修改、审批、提交、下单、入库、出库或付款等业务操作。")


def _retryable_status(status_code: int) -> bool:
    return status_code in {408, 425, 429} or status_code >= 500


async def _retry_wait(attempt: int) -> None:
    await asyncio.sleep(min(2.0, 0.25 * (2**attempt)))


def _build_messages(
    data: AIChatRequest,
    attachment_context: list[str] | None = None,
    image_parts: list[dict[str, object]] | None = None,
    system_prompt: str | None = None,
) -> list[dict[str, object]]:
    """组装系统提示、会话消息和模型原生视觉图片块。"""

    messages: list[dict[str, object]] = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]
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


async def chat(data: AIChatRequest, settings: Settings | None = None, attachment_context: list[str] | None = None, response_format: dict[str, object] | None = None, image_parts: list[dict[str, object]] | None = None, system_prompt: str | None = None, interpret_only: bool = False) -> AIChatResponse:
    """调用配置的 OpenAI 兼容模型。"""

    if not interpret_only:
        _validate_read_only_request(data)
    runtime = settings or get_settings()
    if not runtime.agent_enabled:
        raise BusinessValidationError("AI 助手当前未启用")
    if not runtime.openai_api_key.strip():
        raise BusinessValidationError("AI API key 尚未配置，请先填写 .env")
    if runtime.llm_provider != "openai_compatible":
        raise BusinessValidationError(f"暂不支持的 AI 服务商：{runtime.llm_provider}")

    url = f"{runtime.openai_base_url.rstrip('/')}/chat/completions"
    payload = _build_llm_payload(runtime, _build_messages(data, attachment_context, image_parts, system_prompt), response_format=response_format)
    # DeepSeek Chat Completions 只接受 json_object；严格字段约束使用其 Responses 接口。
    responses_api = (urlsplit(runtime.openai_base_url).hostname == "api.deepseek.com"
                     and response_format is not None and response_format.get("type") == "json_schema")
    if responses_api:
        url = f"{runtime.openai_base_url.rstrip('/')}/responses"
        payload = {"model": runtime.llm_model, "input": payload["messages"],
                   "temperature": runtime.llm_temperature,
                   "max_output_tokens": runtime.llm_max_tokens, "store": False,
                   "text": {"format": {"type": "json_schema", **response_format["json_schema"]}}}
    headers = {"Authorization": f"Bearer {runtime.openai_api_key}", "Content-Type": "application/json"}
    attempts = max(0, runtime.llm_max_retries) + 1
    response: httpx.Response | None = None
    started = perf_counter()
    metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "started"})
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=runtime.llm_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "success"})
            break
        except httpx.TimeoutException as exc:
            if attempt == attempts - 1:
                metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "timeout"})
                LOGGER.warning("AI 服务请求超时 retries=%s", attempt)
                raise BusinessValidationError("AI 服务响应超时，请稍后重试") from exc
            metrics.increment("ai_external_retries", labels={"mode": "sync", "reason": "timeout"})
            await _retry_wait(attempt)
        except httpx.RequestError as exc:
            if attempt == attempts - 1:
                metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "network_error"})
                LOGGER.warning("AI 服务网络请求失败 error_type=%s retries=%s", exc.__class__.__name__, attempt)
                raise BusinessValidationError("AI 服务暂时不可用，请检查网络或稍后重试") from exc
            metrics.increment("ai_external_retries", labels={"mode": "sync", "reason": "network_error"})
            await _retry_wait(attempt)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if _retryable_status(status_code) and attempt < attempts - 1:
                metrics.increment("ai_external_retries", labels={"mode": "sync", "reason": f"http_{status_code}"})
                await _retry_wait(attempt)
                continue
            metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": f"http_{status_code}"})
            LOGGER.warning("AI 服务返回 HTTP status=%s retries=%s", status_code, attempt)
            if _retryable_status(status_code):
                raise BusinessValidationError("AI 服务暂时不可用，请稍后重试") from exc
            raise BusinessValidationError("AI 服务拒绝了请求，请检查 API key、模型和额度配置") from exc

    if response is None:
        metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "empty"})
        raise BusinessValidationError("AI 服务没有返回结果")
    try:
        result = response.json()
        if responses_api:
            content = "".join(part["text"] for item in result["output"] if item.get("type") == "message"
                              for part in item.get("content", []) if part.get("type") == "output_text").strip()
            if result.get("status") != "completed":
                raise ValueError("incomplete structured output")
        else:
            choice = result["choices"][0]
            if response_format and response_format.get("type") == "json_schema" and choice.get("finish_reason") != "stop":
                raise ValueError("incomplete structured output")
            raw_message = choice["message"]
            content = str(raw_message.get("content") or "").strip()
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "invalid_response"})
        raise BusinessValidationError("AI 服务返回了无法识别的结果") from exc
    if not content:
        metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "empty_answer"})
        raise BusinessValidationError("AI 服务返回了空答案")

    metrics.observe("ai_external_duration_seconds", perf_counter() - started, labels={"mode": "sync", "provider": runtime.llm_provider})

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


async def stream_chat(data: AIChatRequest, runtime: Settings, *, attachment_context: list[str] | None = None, image_parts: list[dict[str, object]] | None = None) -> AsyncIterator[str]:
    """只输出模型文本增量；HTTP/SSE 展示与持久化由调用方负责。"""
    if not runtime.agent_enabled or not runtime.openai_api_key.strip() or runtime.llm_provider != "openai_compatible":
        raise BusinessValidationError("AI 服务配置不可用，请检查服务开关、API key 和服务商配置")
    url = f"{runtime.openai_base_url.rstrip('/')}/chat/completions"
    payload = _build_llm_payload(runtime, _build_messages(data, attachment_context, image_parts), stream=True)
    headers = {"Authorization": f"Bearer {runtime.openai_api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    full_content = ""
    first_token_at: float | None = None
    stream_error: Exception | None = None
    started = perf_counter()
    attempts = max(0, runtime.llm_max_retries) + 1
    metrics.increment("ai_external_requests", labels={"mode": "stream", "provider": runtime.llm_provider, "status": "started"})
    for attempt in range(attempts):
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
                            if first_token_at is None:
                                first_token_at = perf_counter()
                                metrics.observe("ai_first_token_seconds", first_token_at - started, labels={"mode": "stream", "provider": runtime.llm_provider})
                            full_content += delta
                            yield delta
            stream_error = None
            metrics.increment("ai_external_requests", labels={"mode": "stream", "provider": runtime.llm_provider, "status": "success"})
            break
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            stream_error = exc
            # 已经向客户端发送过内容时不能重试，否则会重复输出；同时绝不保存半截答案。
            retryable = not isinstance(exc, httpx.HTTPStatusError) or _retryable_status(exc.response.status_code if exc.response is not None else 0)
            if full_content or attempt == attempts - 1 or not retryable:
                break
            metrics.increment("ai_external_retries", labels={"mode": "stream", "reason": exc.__class__.__name__})
            await _retry_wait(attempt)
    metrics.observe("ai_external_duration_seconds", perf_counter() - started, labels={"mode": "stream", "provider": runtime.llm_provider})
    if stream_error is not None:
        metrics.increment("ai_external_requests", labels={"mode": "stream", "provider": runtime.llm_provider, "status": "failure"})
        LOGGER.warning("AI SSE 请求失败 error_type=%s retries=%s partial=%s", stream_error.__class__.__name__, attempt, bool(full_content))
        raise BusinessValidationError("AI 服务暂时不可用，请稍后重试") from stream_error
    if not full_content.strip():
        raise BusinessValidationError("AI 服务返回了空答案")
