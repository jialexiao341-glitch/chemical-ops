"""流式模型客户端的重试和部分输出边界，不访问真实模型。"""

import asyncio

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
