"""OpenAI 兼容模型通信：消息组装、只读护栏、重试与响应解析。

不依赖会话持久化、业务查询或 Agent 执行模块。
"""

import asyncio
import logging
import json
import re
from collections.abc import AsyncIterator
from typing import Any
from time import perf_counter
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import BusinessValidationError
from app.core.observability import metrics
from app.modules.ai.gateway import (
    CircuitOpenError,
    circuit_breakers,
    request_slots,
    resolve_model_profile,
    TaskTokenBudgetExceeded,
    current_task_token_budget,
)
from app.modules.ai.schema import (
    AIChatMessage,
    AIChatRequest,
    AIChatResponse,
)
from app.modules.ai.agent_prompt import SYSTEM_PROMPT

LOGGER = logging.getLogger("chemicalops.ai")
USAGE_TOKEN_FIELDS = {
    "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens",
    "cached_tokens", "reasoning_tokens",
}


class SafeFailoverError(BusinessValidationError):
    """模型拒绝请求或连接建立前失败，可安全切换到显式备用模型。"""


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
    """只重试明确表示配额拒绝的响应，避免重放已被上游接收的生成请求。"""

    return status_code == 429


def _safe_connection_retry(exc: Exception) -> bool:
    """仅连接尚未建立时重试；读超时/断流可能发生在模型已完成计费之后。"""

    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))


def _effective_settings(settings: Settings, profile) -> Settings:
    """将已解析的命名模型配置映射到旧客户端配置，维持既有调用契约。"""

    return settings.model_copy(update={
        "llm_provider": profile.provider,
        "llm_model": profile.model,
        "openai_base_url": profile.base_url,
        "openai_api_key": profile.api_key,
        "llm_timeout_seconds": profile.timeout_seconds,
        "llm_max_retries": profile.max_retries,
        "llm_temperature": profile.temperature,
        "llm_max_tokens": profile.max_tokens,
        "llm_stream_usage": profile.stream_usage,
    })


def _record_usage(usage: object, *, provider: str, model: str, mode: str) -> None:
    if not isinstance(usage, dict):
        return
    for token_type, value in usage.items():
        if token_type in USAGE_TOKEN_FIELDS and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            metrics.increment(
                "llm_tokens",
                value=value,
                labels={"provider": provider, "model": model, "mode": mode, "token_type": token_type},
            )


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


async def _chat_impl(data: AIChatRequest, settings: Settings | None = None, attachment_context: list[str] | None = None, response_format: dict[str, object] | None = None, image_parts: list[dict[str, object]] | None = None, system_prompt: str | None = None, interpret_only: bool = False) -> AIChatResponse:
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
            if not _safe_connection_retry(exc):
                metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "ambiguous_timeout"})
                LOGGER.warning("AI 服务响应阶段超时，不自动重放生成请求")
                raise BusinessValidationError("AI 服务响应超时，请稍后重试") from exc
            if attempt == attempts - 1:
                metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "timeout"})
                LOGGER.warning("AI 服务请求超时 retries=%s", attempt)
                raise SafeFailoverError("AI 服务连接超时，请稍后重试") from exc
            metrics.increment("ai_external_retries", labels={"mode": "sync", "reason": "timeout"})
            await _retry_wait(attempt)
        except httpx.RequestError as exc:
            if not _safe_connection_retry(exc):
                metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "ambiguous_network_error"})
                LOGGER.warning("AI 服务请求状态不明确，不自动重放 error_type=%s", exc.__class__.__name__)
                raise BusinessValidationError("AI 服务暂时不可用，请稍后重试") from exc
            if attempt == attempts - 1:
                metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "network_error"})
                LOGGER.warning("AI 服务网络请求失败 error_type=%s retries=%s", exc.__class__.__name__, attempt)
                raise SafeFailoverError("AI 服务连接失败，请检查网络或稍后重试") from exc
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
                raise SafeFailoverError("AI 服务暂时不可用，请稍后重试") from exc
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
    normalized_usage = (
        {
            key: value for key, value in usage.items()
            if key in USAGE_TOKEN_FIELDS and isinstance(value, int) and not isinstance(value, bool) and value >= 0
        }
        if isinstance(usage, dict)
        else None
    )
    if not normalized_usage:
        normalized_usage = None
    _record_usage(normalized_usage, provider=runtime.llm_provider, model=runtime.llm_model, mode="sync")
    return AIChatResponse(
        message=AIChatMessage(role="assistant", content=content),
        conversation_id=data.conversation_id or 0,
        model=runtime.llm_model,
        provider=runtime.llm_provider,
        usage=normalized_usage,
        user_query=next((message.content for message in reversed(data.messages) if message.role == "user"), None),
        answer=content,
    )


async def chat(
    data: AIChatRequest,
    settings: Settings | None = None,
    attachment_context: list[str] | None = None,
    response_format: dict[str, object] | None = None,
    image_parts: list[dict[str, object]] | None = None,
    system_prompt: str | None = None,
    interpret_only: bool = False,
    *,
    model_name: str | None = None,
    _allow_fallback: bool = True,
) -> AIChatResponse:
    """经统一模型目录、并发配额和熔断策略发起非流式模型调用。"""

    runtime = settings or get_settings()
    try:
        profile = resolve_model_profile(runtime, model_name)
    except ValueError as exc:
        raise BusinessValidationError(str(exc)) from exc
    task_budget = current_task_token_budget()
    reservation = None
    if task_budget is not None:
        budget_input = json.dumps({
            "messages": _build_messages(data, attachment_context, image_parts, system_prompt),
            "response_format": response_format,
        }, ensure_ascii=False, default=str)
        try:
            reservation = task_budget.reserve(budget_input, min(profile.max_tokens, runtime.llm_max_tokens))
        except TaskTokenBudgetExceeded as exc:
            raise BusinessValidationError(str(exc)) from exc
    result = None
    try:
        settled = False
        probe_claimed = False
        started = perf_counter()
        async with request_slots(profile, runtime):
            metrics.observe("llm_concurrency_wait_seconds", perf_counter() - started, labels={"provider": profile.provider, "model": profile.model})
            try:
                circuit_breakers.before_request(
                    profile.key,
                    threshold=runtime.llm_circuit_failure_threshold,
                    reset_seconds=runtime.llm_circuit_reset_seconds,
                )
                probe_claimed = True
            except CircuitOpenError as exc:
                metrics.increment("llm_circuit_rejections", labels={"provider": profile.provider, "model": profile.model})
                raise SafeFailoverError("AI 服务暂时熔断，请稍后重试") from exc
            try:
                from app.core.telemetry import trace_span
                with trace_span("llm.chat", {"gen_ai.request.model": profile.model,
                                              "gen_ai.system": profile.provider}):
                    effective = _effective_settings(runtime, profile)
                    if task_budget is not None:
                        effective = effective.model_copy(update={
                            "llm_max_tokens": min(profile.max_tokens, runtime.llm_max_tokens),
                        })
                    result = await _chat_impl(
                        data,
                        effective,
                        attachment_context,
                        response_format,
                        image_parts,
                        system_prompt,
                        interpret_only,
                    )
            except BusinessValidationError as exc:
                settled = True
                if isinstance(exc, SafeFailoverError) or "暂时不可用" in str(exc) or "超时" in str(exc):
                    opened = circuit_breakers.failure(profile.key, threshold=runtime.llm_circuit_failure_threshold)
                    if opened:
                        metrics.increment("llm_circuit_opened", labels={"provider": profile.provider, "model": profile.model})
                else:
                    circuit_breakers.success(profile.key)
                raise
            except Exception:
                settled = True
                circuit_breakers.success(profile.key)
                raise
            settled = True
            circuit_breakers.success(profile.key)
            return result
    except SafeFailoverError:
        if _allow_fallback and profile.fallback_profile:
            metrics.increment("llm_model_failovers", labels={"provider": profile.provider, "model": profile.model})
            return await chat(
                data,
                runtime,
                attachment_context,
                response_format,
                image_parts,
                system_prompt,
                interpret_only,
                model_name=profile.fallback_profile,
                _allow_fallback=False,
            )
        raise
    except asyncio.CancelledError:
        metrics.increment("llm_requests_cancelled", labels={"provider": profile.provider, "model": profile.model, "mode": "sync"})
        raise
    finally:
        if task_budget is not None and reservation is not None:
            try:
                await task_budget.settle_async(reservation, result.usage if result is not None else None)
            except Exception as exc:
                if isinstance(exc, TaskTokenBudgetExceeded):
                    raise BusinessValidationError(str(exc)) from exc
                raise
        metrics.observe("llm_gateway_duration_seconds", perf_counter() - started, labels={"provider": profile.provider, "model": profile.model, "mode": "sync"})
        if probe_claimed and not settled:
            circuit_breakers.abandon_probe(profile.key)


async def _stream_chat_impl(data: AIChatRequest, runtime: Settings, *, attachment_context: list[str] | None = None, image_parts: list[dict[str, object]] | None = None) -> AsyncIterator[str]:
    """只输出模型文本增量；HTTP/SSE 展示与持久化由调用方负责。"""
    if not runtime.agent_enabled or not runtime.openai_api_key.strip() or runtime.llm_provider != "openai_compatible":
        raise BusinessValidationError("AI 服务配置不可用，请检查服务开关、API key 和服务商配置")
    url = f"{runtime.openai_base_url.rstrip('/')}/chat/completions"
    payload = _build_llm_payload(runtime, _build_messages(data, attachment_context, image_parts), stream=True)
    if runtime.llm_stream_usage:
        payload["stream_options"] = {"include_usage": True}
    headers = {"Authorization": f"Bearer {runtime.openai_api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    full_content = ""
    first_token_at: float | None = None
    stream_error: Exception | None = None
    started = perf_counter()
    attempts = max(0, runtime.llm_max_retries) + 1
    stream_usage: object = None
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
                            if isinstance(chunk.get("usage"), dict):
                                stream_usage = chunk["usage"]
                            choices = chunk.get("choices") or []
                            delta = choices[0].get("delta", {}).get("content") or "" if choices else ""
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
            retryable = (
                _safe_connection_retry(exc)
                or (isinstance(exc, httpx.HTTPStatusError) and _retryable_status(exc.response.status_code if exc.response is not None else 0))
            )
            if full_content or attempt == attempts - 1 or not retryable:
                break
            metrics.increment("ai_external_retries", labels={"mode": "stream", "reason": exc.__class__.__name__})
            await _retry_wait(attempt)
    metrics.observe("ai_external_duration_seconds", perf_counter() - started, labels={"mode": "stream", "provider": runtime.llm_provider})
    if stream_error is not None:
        metrics.increment("ai_external_requests", labels={"mode": "stream", "provider": runtime.llm_provider, "status": "failure"})
        LOGGER.warning("AI SSE 请求失败 error_type=%s retries=%s partial=%s", stream_error.__class__.__name__, attempt, bool(full_content))
        if not full_content and (
            _safe_connection_retry(stream_error)
            or (isinstance(stream_error, httpx.HTTPStatusError) and _retryable_status(stream_error.response.status_code if stream_error.response is not None else 0))
        ):
            raise SafeFailoverError("AI 服务暂时不可用（连接失败），请稍后重试") from stream_error
        raise BusinessValidationError("AI 服务暂时不可用，请稍后重试") from stream_error
    _record_usage(stream_usage, provider=runtime.llm_provider, model=runtime.llm_model, mode="stream")
    if not full_content.strip():
        raise BusinessValidationError("AI 服务返回了空答案")


async def stream_chat(
    data: AIChatRequest,
    runtime: Settings,
    *,
    attachment_context: list[str] | None = None,
    image_parts: list[dict[str, object]] | None = None,
    model_name: str | None = None,
    _allow_fallback: bool = True,
) -> AsyncIterator[str]:
    """经统一模型目录、并发配额和熔断策略输出文本增量。"""

    try:
        profile = resolve_model_profile(runtime, model_name)
    except ValueError as exc:
        raise BusinessValidationError(str(exc)) from exc
    started = perf_counter()
    settled = False
    probe_claimed = False
    yielded_content = False
    try:
        async with request_slots(profile, runtime):
            metrics.observe("llm_concurrency_wait_seconds", perf_counter() - started, labels={"provider": profile.provider, "model": profile.model})
            try:
                circuit_breakers.before_request(
                    profile.key,
                    threshold=runtime.llm_circuit_failure_threshold,
                    reset_seconds=runtime.llm_circuit_reset_seconds,
                )
                probe_claimed = True
            except CircuitOpenError as exc:
                metrics.increment("llm_circuit_rejections", labels={"provider": profile.provider, "model": profile.model})
                raise SafeFailoverError("AI 服务暂时熔断，请稍后重试") from exc
            try:
                from app.core.telemetry import trace_span
                with trace_span("llm.stream", {"gen_ai.request.model": profile.model,
                                                "gen_ai.system": profile.provider}):
                    stream = _stream_chat_impl(
                        data,
                        _effective_settings(runtime, profile),
                        attachment_context=attachment_context,
                        image_parts=image_parts,
                    )
                    try:
                        async for delta in stream:
                            yielded_content = True
                            yield delta
                    finally:
                        await stream.aclose()
            except BusinessValidationError as exc:
                settled = True
                if isinstance(exc, SafeFailoverError) or "暂时不可用" in str(exc) or "超时" in str(exc):
                    opened = circuit_breakers.failure(profile.key, threshold=runtime.llm_circuit_failure_threshold)
                    if opened:
                        metrics.increment("llm_circuit_opened", labels={"provider": profile.provider, "model": profile.model})
                else:
                    circuit_breakers.success(profile.key)
                raise
            else:
                settled = True
                circuit_breakers.success(profile.key)
    except SafeFailoverError:
        if _allow_fallback and not yielded_content and profile.fallback_profile:
            metrics.increment("llm_model_failovers", labels={"provider": profile.provider, "model": profile.model})
            async for delta in stream_chat(
                data,
                runtime,
                attachment_context=attachment_context,
                image_parts=image_parts,
                model_name=profile.fallback_profile,
                _allow_fallback=False,
            ):
                yield delta
            return
        raise
    except asyncio.CancelledError:
        metrics.increment("llm_requests_cancelled", labels={"provider": profile.provider, "model": profile.model, "mode": "stream"})
        raise
    finally:
        metrics.observe("llm_gateway_duration_seconds", perf_counter() - started, labels={"provider": profile.provider, "model": profile.model, "mode": "stream"})
        if probe_claimed and not settled:
            circuit_breakers.abandon_probe(profile.key)


def extract_json_object(raw: str) -> dict[str, Any]:
    """从模型输出中提取第一个合法 JSON 对象，兼容代码块和前置说明。"""

    cleaned = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).replace("```", "")
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            payload, _ = decoder.raw_decode(cleaned, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise BusinessValidationError("AI 未返回有效的查询计划")
