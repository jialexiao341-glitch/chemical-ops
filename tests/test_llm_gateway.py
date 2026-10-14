"""统一 LLM Gateway 的配置、熔断及并发治理单元测试。"""

import asyncio
import json

import pytest
import httpx

from app.core.config import Settings
from app.modules.ai import gateway
from app.modules.ai import llm
from app.modules.ai.schema import AIChatRequest


def test_model_registry_supports_legacy_and_named_profiles() -> None:
    legacy = Settings(_env_file=None, openai_api_key="legacy-key", llm_model="legacy-model")
    default = gateway.resolve_model_profile(legacy)
    assert default.model == "legacy-model"
    assert default.api_key == "legacy-key"

    configured = Settings(
        _env_file=None,
        openai_api_key="legacy-key",
        llm_model_profiles_json=json.dumps({
            "fast": {
                "model": "model-fast",
                "fallback_profile": "backup",
                "base_url": "https://fast.example/v1/",
                "api_key": "fast-key",
                "timeout_seconds": 9,
                "max_retries": 1,
                "max_concurrency": 3,
                "temperature": 0.5,
                "max_tokens": 2048,
                "stream_usage": True,
            },
            "backup": {
                "model": "model-backup",
                "base_url": "https://backup.example/v1",
                "api_key": "backup-key",
            }
        }),
    )
    profile = gateway.resolve_model_profile(configured, "fast")
    assert (profile.model, profile.base_url, profile.api_key) == (
        "model-fast", "https://fast.example/v1", "fast-key"
    )
    assert (profile.timeout_seconds, profile.max_retries, profile.max_concurrency) == (9, 1, 3)
    assert (profile.temperature, profile.max_tokens, profile.stream_usage) == (0.5, 2048, True)
    assert profile.fallback_profile == "backup"
    assert gateway.resolve_model_profile(configured, "model-fast") == profile


def test_model_registry_rejects_invalid_or_unknown_profiles() -> None:
    with pytest.raises(ValueError, match="合法 JSON"):
        Settings(_env_file=None, llm_model_profiles_json="not-json")
    with pytest.raises(ValueError, match="未配置"):
        gateway.resolve_model_profile(Settings(_env_file=None), "missing-model")
    with pytest.raises(ValueError, match="必须引用"):
        Settings(
            _env_file=None,
            llm_default_profile="missing",
            llm_model_profiles_json=json.dumps({"available": {"model": "model-a"}}),
        )


def test_circuit_breaker_opens_rejects_parallel_probe_and_recovers(monkeypatch) -> None:
    clock = [10.0]
    monkeypatch.setattr(gateway, "monotonic", lambda: clock[0])
    breaker = gateway.CircuitBreakerRegistry()
    breaker.failure("model", threshold=2)
    assert breaker.failure("model", threshold=2)
    with pytest.raises(gateway.CircuitOpenError):
        breaker.before_request("model", threshold=2, reset_seconds=5)

    clock[0] += 6
    breaker.before_request("model", threshold=2, reset_seconds=5)
    with pytest.raises(gateway.CircuitOpenError):
        breaker.before_request("model", threshold=2, reset_seconds=5)
    breaker.success("model")
    assert breaker.snapshot("model") == (0, None, False)


def test_request_slots_enforce_user_and_model_concurrency_and_release_on_cancel() -> None:
    settings = Settings(_env_file=None, llm_max_concurrency=2, llm_user_max_concurrency=1)
    profile = gateway.resolve_model_profile(settings)

    async def run():
        active_by_user: dict[int, int] = {}
        maximum_by_user: dict[int, int] = {}
        active_total = 0
        maximum_total = 0

        async def worker(user_id: int):
            nonlocal active_total, maximum_total
            token = gateway.bind_user(user_id)
            try:
                async with gateway.request_slots(profile, settings):
                    active_by_user[user_id] = active_by_user.get(user_id, 0) + 1
                    active_total += 1
                    maximum_by_user[user_id] = max(maximum_by_user.get(user_id, 0), active_by_user[user_id])
                    maximum_total = max(maximum_total, active_total)
                    await asyncio.sleep(0.01)
                    active_by_user[user_id] -= 1
                    active_total -= 1
            finally:
                gateway.reset_user(token)

        await asyncio.gather(*(worker(user_id) for user_id in [1, 1, 2, 2]))
        assert maximum_by_user == {1: 1, 2: 1}
        assert maximum_total <= 2

        token = gateway.bind_user(3)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_worker():
            async with gateway.request_slots(profile, settings):
                entered.set()
                await release.wait()

        task = asyncio.create_task(blocked_worker())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with gateway.request_slots(profile, settings):
            pass
        gateway.reset_user(token)

    asyncio.run(run())


def test_chat_uses_explicit_fallback_only_after_connect_failure(monkeypatch) -> None:
    requests = []

    def respond(request):
        requests.append(request.url.host)
        if request.url.host == "primary.example":
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "备用模型回答"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        })

    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(llm, "_retry_wait", lambda _attempt: asyncio.sleep(0))
    settings = Settings(
        _env_file=None,
        openai_api_key="base-key",
        llm_max_retries=0,
        llm_model_profiles_json=json.dumps({
            "primary": {
                "model": "primary-model",
                "base_url": "https://primary.example/v1",
                "api_key": "primary-key",
                "fallback_profile": "backup",
            },
            "backup": {
                "model": "backup-model",
                "base_url": "https://backup.example/v1",
                "api_key": "backup-key",
            },
        }),
    )
    request = AIChatRequest(messages=[{"role": "user", "content": "只读模型网关测试"}])

    response = asyncio.run(llm.chat(request, settings, interpret_only=True, model_name="primary"))

    assert response.message.content == "备用模型回答"
    assert response.model == "backup-model"
    assert requests == ["primary.example", "backup.example"]
