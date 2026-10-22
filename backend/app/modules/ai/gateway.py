"""模型配置解析、并发配额和进程内熔断状态。"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass
import inspect
import json
import math
from threading import Lock
from time import monotonic
from typing import AsyncIterator, Callable
from contextlib import asynccontextmanager
from weakref import WeakKeyDictionary

from app.core.config import Settings


_user_id_context: ContextVar[int | None] = ContextVar("llm_user_id", default=None)
_task_token_budget_context: ContextVar["TaskTokenBudget | None"] = ContextVar("llm_task_token_budget", default=None)


class TaskTokenBudgetExceeded(RuntimeError):
    """The current Agent task cannot reserve enough tokens for another model call."""


@dataclass(frozen=True)
class TokenReservation:
    input_estimate: int
    output_limit: int

    @property
    def amount(self) -> int:
        return self.input_estimate + self.output_limit


class TaskTokenBudget:
    """Cumulative token ledger shared by all LLM calls in one Agent task."""

    def __init__(self, limit: int, *, used_tokens: int = 0, estimated_tokens: int = 0,
                 calls: int = 0, on_settle: Callable[[dict[str, int]], object] | None = None) -> None:
        self.limit = limit
        self.used_tokens = max(0, used_tokens)
        self.estimated_tokens = max(0, estimated_tokens)
        self.calls = max(0, calls)
        self._reserved_tokens = 0
        self._lock = Lock()
        self._on_settle = on_settle

    @staticmethod
    def estimate_input_tokens(text: str) -> int:
        # CJK characters are commonly one token; use a conservative 3:1 estimate for other text.
        cjk = sum(1 for char in text if ord(char) >= 0x2E80)
        other = len(text) - cjk
        return cjk + (other + 2) // 3

    def reserve(self, input_text: str, output_limit: int) -> TokenReservation:
        reservation = TokenReservation(self.estimate_input_tokens(input_text), max(1, output_limit))
        with self._lock:
            if self.used_tokens + self._reserved_tokens + reservation.amount > self.limit:
                raise TaskTokenBudgetExceeded("TOKEN_BUDGET_EXCEEDED")
            self._reserved_tokens += reservation.amount
        return reservation

    def _record_settlement(self, reservation: TokenReservation, usage: object) -> tuple[dict[str, int], bool]:
        actual_input = actual_output = actual_total = None
        if isinstance(usage, dict):
            def valid(*names: str) -> int | None:
                for name in names:
                    value = usage.get(name)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        return value
                return None
            actual_input = valid("prompt_tokens", "input_tokens")
            actual_output = valid("completion_tokens", "output_tokens")
            actual_total = valid("total_tokens")
        if actual_input is not None and actual_output is not None:
            charge = max(reservation.input_estimate, actual_input) + actual_output
            estimated = max(0, reservation.input_estimate - actual_input)
        elif actual_total is not None:
            charge = max(reservation.input_estimate, actual_total)
            estimated = max(0, reservation.input_estimate - (actual_input or 0))
        else:
            charge = reservation.amount
            estimated = charge
        with self._lock:
            self._reserved_tokens = max(0, self._reserved_tokens - reservation.amount)
            self.used_tokens += charge
            self.estimated_tokens += estimated
            self.calls += 1
            snapshot = {"limit": self.limit, "used_tokens": self.used_tokens,
                        "estimated_tokens": self.estimated_tokens, "calls": self.calls}
            over_budget = self.used_tokens + self._reserved_tokens > self.limit
        return snapshot, over_budget

    def settle(self, reservation: TokenReservation, usage: object = None) -> None:
        """Keep synchronous callers compatible; async callbacks use settle_async."""
        snapshot, over_budget = self._record_settlement(reservation, usage)
        if self._on_settle:
            callback_result = self._on_settle(snapshot)
            if inspect.isawaitable(callback_result):
                close = getattr(callback_result, "close", None)
                if close:
                    close()
                raise RuntimeError("异步预算回调必须通过 settle_async 等待")
        if over_budget:
            raise TaskTokenBudgetExceeded("TOKEN_BUDGET_EXCEEDED")

    async def settle_async(self, reservation: TokenReservation, usage: object = None) -> None:
        """Settle usage and await persistence callbacks without blocking the event loop."""
        snapshot, over_budget = self._record_settlement(reservation, usage)
        if self._on_settle:
            callback_result = self._on_settle(snapshot)
            if inspect.isawaitable(callback_result):
                await callback_result
        if over_budget:
            raise TaskTokenBudgetExceeded("TOKEN_BUDGET_EXCEEDED")

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"limit": self.limit, "used_tokens": self.used_tokens,
                    "estimated_tokens": self.estimated_tokens, "calls": self.calls}


def bind_task_token_budget(budget: TaskTokenBudget) -> Token[TaskTokenBudget | None]:
    return _task_token_budget_context.set(budget)


def reset_task_token_budget(token: Token[TaskTokenBudget | None]) -> None:
    _task_token_budget_context.reset(token)


def current_task_token_budget() -> TaskTokenBudget | None:
    return _task_token_budget_context.get()


@dataclass(frozen=True)
class ModelProfileConfig:
    """一个可被内部用例选择的 OpenAI-compatible 模型配置。"""

    provider: str
    model: str
    fallback_profile: str | None
    base_url: str | None
    api_key: str | None
    timeout_seconds: float | None
    max_retries: int | None
    max_concurrency: int | None
    temperature: float | None
    max_tokens: int | None
    stream_usage: bool

    @classmethod
    def from_mapping(cls, value: object) -> "ModelProfileConfig":
        if not isinstance(value, dict):
            raise ValueError("模型 profile 必须是 JSON 对象")
        allowed = {
            "provider", "model", "fallback_profile", "base_url", "api_key", "timeout_seconds",
            "max_retries", "max_concurrency", "temperature", "max_tokens", "stream_usage",
        }
        if set(value) - allowed:
            raise ValueError("模型 profile 包含未知字段")
        provider = value.get("provider", "openai_compatible")
        model = value.get("model")
        fallback = value.get("fallback_profile")
        base_url = value.get("base_url")
        api_key = value.get("api_key")
        timeout = value.get("timeout_seconds")
        retries = value.get("max_retries")
        concurrency = value.get("max_concurrency")
        temperature = value.get("temperature")
        max_tokens = value.get("max_tokens")
        stream_usage = value.get("stream_usage", False)
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider 必须是非空字符串")
        if not isinstance(model, str) or not model.strip() or len(model) > 128:
            raise ValueError("model 必须是 1 到 128 个字符")
        if fallback is not None and (not isinstance(fallback, str) or not fallback.strip()):
            raise ValueError("fallback_profile 必须是非空 profile 名称")
        if base_url is not None and (not isinstance(base_url, str) or not base_url.strip()):
            raise ValueError("base_url 必须是非空字符串")
        if api_key is not None and not isinstance(api_key, str):
            raise ValueError("api_key 必须是字符串")
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0 or timeout > 600
        ):
            raise ValueError("timeout_seconds 必须在 (0, 600] 范围内")
        if retries is not None and (isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 5):
            raise ValueError("max_retries 必须在 0 到 5 范围内")
        if concurrency is not None and (
            isinstance(concurrency, bool) or not isinstance(concurrency, int) or not 1 <= concurrency <= 256
        ):
            raise ValueError("max_concurrency 必须在 1 到 256 范围内")
        if temperature is not None and (
            isinstance(temperature, bool) or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature) or not 0 <= temperature <= 2
        ):
            raise ValueError("temperature 必须在 0 到 2 范围内")
        if max_tokens is not None and (
            isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 1_000_000
        ):
            raise ValueError("max_tokens 必须在 1 到 1000000 范围内")
        if not isinstance(stream_usage, bool):
            raise ValueError("stream_usage 必须是布尔值")
        return cls(provider, model, fallback, base_url, api_key, timeout, retries, concurrency, temperature, max_tokens, stream_usage)


@dataclass(frozen=True)
class ModelProfile:
    name: str
    provider: str
    model: str
    fallback_profile: str | None
    base_url: str
    api_key: str
    timeout_seconds: float
    max_retries: int
    max_concurrency: int
    temperature: float
    max_tokens: int
    stream_usage: bool

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.base_url.rstrip('/')}:{self.model}"


def _configured_profiles(raw: str) -> dict[str, ModelProfileConfig]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("LLM_MODEL_PROFILES_JSON 必须是非空 JSON 对象")
        if any(not isinstance(name, str) or not name.strip() for name in parsed):
            raise ValueError("模型 profile 名称不能为空")
        return {name: ModelProfileConfig.from_mapping(value) for name, value in parsed.items()}
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("LLM_MODEL_PROFILES_JSON 配置无效") from exc


def resolve_model_profile(settings: Settings, model_name: str | None = None) -> ModelProfile:
    """解析命名模型；未配置目录时回退到既有单模型环境变量。"""

    profiles = _configured_profiles(settings.llm_model_profiles_json)
    requested = model_name or settings.llm_default_profile or settings.llm_model
    configured = profiles.get(requested)
    profile_name = requested
    if configured is None:
        match = next(((name, profile) for name, profile in profiles.items() if profile.model == requested), None)
        if match is not None:
            profile_name, configured = match
    if (model_name or settings.llm_default_profile) and configured is None:
        raise ValueError(f"LLM 模型未配置：{model_name or settings.llm_default_profile}")

    provider = configured.provider if configured else settings.llm_provider
    if provider != "openai_compatible":
        raise ValueError(f"暂不支持的 AI 服务商：{provider}")
    fallback_name = configured.fallback_profile if configured else None
    if fallback_name:
        fallback_config = profiles.get(fallback_name)
        if fallback_config is None or fallback_name == profile_name:
            raise ValueError(f"备用模型 profile 未配置或指向自身：{fallback_name}")
        if fallback_config.provider != "openai_compatible":
            raise ValueError(f"暂不支持的备用 AI 服务商：{fallback_config.provider}")
        current_model = configured.model if configured else settings.llm_model
        current_base_url = (configured.base_url if configured and configured.base_url else settings.openai_base_url).rstrip("/")
        fallback_model = fallback_config.model
        fallback_base_url = (fallback_config.base_url if fallback_config.base_url else settings.openai_base_url).rstrip("/")
        if fallback_config.provider == provider and fallback_model == current_model and fallback_base_url == current_base_url:
            raise ValueError("备用模型必须指向不同的 provider、base URL 或 model")
    return ModelProfile(
        name=profile_name,
        provider=provider,
        model=configured.model if configured else settings.llm_model,
        fallback_profile=fallback_name,
        base_url=(configured.base_url if configured and configured.base_url else settings.openai_base_url).rstrip("/"),
        api_key=(configured.api_key if configured and configured.api_key is not None else settings.openai_api_key),
        timeout_seconds=configured.timeout_seconds if configured and configured.timeout_seconds else settings.llm_timeout_seconds,
        max_retries=configured.max_retries if configured and configured.max_retries is not None else settings.llm_max_retries,
        max_concurrency=configured.max_concurrency if configured and configured.max_concurrency else settings.llm_max_concurrency,
        temperature=configured.temperature if configured and configured.temperature is not None else settings.llm_temperature,
        max_tokens=configured.max_tokens if configured and configured.max_tokens is not None else settings.llm_max_tokens,
        stream_usage=configured.stream_usage if configured else settings.llm_stream_usage,
    )


def bind_user(user_id: int) -> Token[int | None]:
    """将当前请求的身份放入异步上下文，供所有嵌套模型调用共享。"""

    return _user_id_context.set(user_id)


def reset_user(token: Token[int | None]) -> None:
    _user_id_context.reset(token)


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None
    probe_in_flight: bool = False


class CircuitOpenError(RuntimeError):
    """模型熔断期间拒绝新请求。"""


class CircuitBreakerRegistry:
    """进程内按模型隔离的闭合、开启、半开熔断器。"""

    def __init__(self) -> None:
        self._states: dict[str, _CircuitState] = {}
        self._lock = Lock()

    def before_request(self, key: str, *, threshold: int, reset_seconds: int) -> None:
        now = monotonic()
        with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            if state.opened_at is None:
                return
            if now - state.opened_at < reset_seconds or state.probe_in_flight:
                raise CircuitOpenError("模型服务熔断中")
            state.probe_in_flight = True

    def success(self, key: str) -> None:
        with self._lock:
            self._states[key] = _CircuitState()

    def abandon_probe(self, key: str) -> None:
        """取消半开探测时释放探测锁，保持熔断状态等待下一次请求。"""

        with self._lock:
            state = self._states.get(key)
            if state is not None:
                state.probe_in_flight = False

    def failure(self, key: str, *, threshold: int) -> bool:
        with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            state.failures += 1
            if state.failures >= threshold:
                state.opened_at = monotonic()
                state.probe_in_flight = False
                return True
            return False

    def snapshot(self, key: str) -> tuple[int, float | None, bool]:
        with self._lock:
            state = self._states.get(key, _CircuitState())
            return state.failures, state.opened_at, state.probe_in_flight


_loop_slots: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[str, str], asyncio.Semaphore]] = WeakKeyDictionary()
_slots_lock = Lock()


def _get_semaphore(key: tuple[str, str], limit: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    with _slots_lock:
        slots = _loop_slots.setdefault(loop, {})
        semaphore = slots.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(limit)
            slots[key] = semaphore
        return semaphore


@asynccontextmanager
async def request_slots(profile: ModelProfile, settings: Settings) -> AsyncIterator[None]:
    """施加每用户与每模型并发上限；请求取消时由 async with 自动归还许可。"""

    user_id = _user_id_context.get()
    user_limit = _get_semaphore((profile.key, f"user:{user_id}"), settings.llm_user_max_concurrency) if user_id else None
    model_limit = _get_semaphore((profile.key, "model"), profile.max_concurrency)
    if user_limit is None:
        async with model_limit:
            yield
        return
    async with user_limit:
        async with model_limit:
            yield


circuit_breakers = CircuitBreakerRegistry()
