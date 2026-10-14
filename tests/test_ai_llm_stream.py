"""流式模型客户端的重试和部分输出边界，不访问真实模型。"""

import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import BusinessValidationError
from app.modules.ai import llm
from app.modules.ai.schema import AIChatMessage, AIChatRequest


REQUEST = AIChatRequest(messages=[AIChatMessage(role="user", content="分析附件")])


@pytest.mark.parametrize("raw", [
    '{"items": [{"name": "乙醇"}]}',
    '结果如下：\n```json\n{"items": [{"name": "乙醇"}]}\n```',
    '前文含无效 {内容}，实际结果：{"items": [{"name": "乙醇"}]} 后文',
])
def test_extract_json_object_handles_model_output(raw):
    assert llm.extract_json_object(raw) == {"items": [{"name": "乙醇"}]}


@pytest.mark.parametrize("raw", ["", "没有结构化结果", "```json\n{invalid}\n```"])
def test_extract_json_object_rejects_invalid_output(raw):
    with pytest.raises(BusinessValidationError):
        llm.extract_json_object(raw)


@pytest.mark.parametrize("failure", ["before_token", "after_token", "empty"])
def test_stream_retries_only_before_output(monkeypatch, failure):
    attempts = 0
    received = []

    class InterruptedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            raise httpx.ReadError("connection lost")

    def respond(request):
        nonlocal attempts
        attempts += 1
        if failure == "before_token" and attempts == 1:
            raise httpx.ConnectError("temporary", request=request)
        if failure == "after_token":
            return httpx.Response(200, stream=InterruptedStream())
        if failure == "empty":
            return httpx.Response(200, text="data: [DONE]\n\n")
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"complete"}}]}\n\ndata: [DONE]\n\n')

    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(llm, "_retry_wait", lambda _: asyncio.sleep(0))
    settings = Settings(_env_file=None, openai_api_key="test-key", llm_max_retries=2)

    async def collect():
        async for chunk in llm.stream_chat(REQUEST, settings):
            received.append(chunk)

    if failure == "before_token":
        asyncio.run(collect())
        assert received == ["complete"]
        assert attempts == 2
    else:
        with pytest.raises(BusinessValidationError, match="空答案" if failure == "empty" else "暂时不可用"):
            asyncio.run(collect())
        assert received == (["partial"] if failure == "after_token" else [])
        assert attempts == 1


def test_stream_usage_is_opt_in_and_counted_when_provider_returns_it(monkeypatch):
    payloads = []
    usages = []

    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"答案"}}]}\n\n'
                'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":4,"total_tokens":16}}\n\n'
                'data: [DONE]\n\n'
            ),
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(llm, "_record_usage", lambda usage, **kwargs: usages.append((usage, kwargs)))
    settings = Settings(_env_file=None, openai_api_key="test-key", llm_max_retries=0, llm_stream_usage=True)

    async def collect():
        return [chunk async for chunk in llm.stream_chat(REQUEST, settings)]

    assert asyncio.run(collect()) == ["答案"]
    assert payloads[0]["stream_options"] == {"include_usage": True}
    assert usages[0][0] == {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}


def test_stream_fails_over_before_first_token_when_profile_declares_backup(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request.url.host)
        if request.url.host == "primary.example":
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"备用流"}}]}\n\ndata: [DONE]\n\n',
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(llm, "_retry_wait", lambda _: asyncio.sleep(0))
    settings = Settings(
        _env_file=None,
        openai_api_key="base-key",
        llm_max_retries=0,
        llm_model_profiles_json=json.dumps({
            "primary": {
                "model": "primary-model",
                "base_url": "https://primary.example/v1",
                "fallback_profile": "backup",
            },
            "backup": {
                "model": "backup-model",
                "base_url": "https://backup.example/v1",
            },
        }),
    )

    async def collect():
        return [chunk async for chunk in llm.stream_chat(REQUEST, settings, model_name="primary")]

    assert asyncio.run(collect()) == ["备用流"]
    assert requests == ["primary.example", "backup.example"]


def test_stream_does_not_fail_over_after_first_token(monkeypatch):
    requests = []

    class InterruptedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield 'data: {"choices":[{"delta":{"content":"部分"}}]}\n\n'.encode("utf-8")
            raise httpx.ReadError("response stream interrupted")

    def respond(request):
        requests.append(request.url.host)
        if request.url.host == "primary.example":
            return httpx.Response(200, stream=InterruptedStream())
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"备用"}}]}\n\ndata: [DONE]\n\n')

    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
    settings = Settings(
        _env_file=None,
        openai_api_key="base-key",
        llm_max_retries=0,
        llm_model_profiles_json=json.dumps({
            "primary": {
                "model": "primary-model",
                "base_url": "https://primary.example/v1",
                "fallback_profile": "backup",
            },
            "backup": {
                "model": "backup-model",
                "base_url": "https://backup.example/v1",
            },
        }),
    )

    async def collect():
        return [chunk async for chunk in llm.stream_chat(REQUEST, settings, model_name="primary")]

    with pytest.raises(BusinessValidationError, match="暂时不可用"):
        asyncio.run(collect())
    assert requests == ["primary.example"]
