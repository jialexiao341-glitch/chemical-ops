"""评测脚本共用的模型目录激活、超时配置与基础设施错误归因辅助函数。"""

from __future__ import annotations

import subprocess
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import BusinessValidationError
from app.modules.ai_agent.model_access import model_catalog
from app.modules.ai_agent.model_access.gateway import ModelProfile, resolve_model_profile
from app.modules.ai_agent.model_access.llm import SafeFailoverError
from app.modules.ai_agent.shared_utils.error_policy import classify
from app.modules.task_queue.errors import transient


def eval_llm_settings(
    base: Settings,
    *,
    min_timeout_seconds: int = 120,
    updates: dict[str, Any] | None = None,
) -> Settings:
    """构造评测用 LLM 配置，保证不低于指定单次超时且保留现有重试策略。"""
    payload: dict[str, Any] = {
        "llm_max_retries": base.llm_max_retries,
        "llm_timeout_seconds": max(base.llm_timeout_seconds, min_timeout_seconds),
    }
    if updates:
        payload.update(updates)
    return base.model_copy(update=payload)


def activate_eval_profile(
    *,
    min_timeout_seconds: int = 120,
    updates: dict[str, Any] | None = None,
) -> tuple[Settings, ModelProfile]:
    """激活数据库模型目录（不可达时回退 .env/环境变量）并解析评测生效的模型配置。"""
    model_catalog.activate()
    settings = eval_llm_settings(
        get_settings(),
        min_timeout_seconds=min_timeout_seconds,
        updates=updates,
    )
    return settings, resolve_model_profile(settings)


def is_infra_or_timeout_exception(exc: Exception | None) -> bool:
    """判断异常链是否属于网络断流、限流、上游 5xx 或响应阶段超时。

    显式排除 HTTP 400 / 认证额度拒绝等请求/配置错误，防止配置问题伪装成基础设施抖动。
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, Exception) and transient(current):
            return True
        if isinstance(
            current,
            (
                SafeFailoverError,
                httpx.TimeoutException,
                httpx.RequestError,
                TimeoutError,
                subprocess.TimeoutExpired,
            ),
        ):
            return True
        if isinstance(current, BusinessValidationError) and (
            "响应超时" in str(current) or "暂时不可用" in str(current)
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def exception_run_meta(
    exc: Exception,
    *,
    default_infra_code: str | None = "MODEL_SERVICE_ERROR",
) -> dict[str, Any]:
    """把评测期捕获的异常映射为标准 `run_meta.error` 结构，供 harness 与稳定性统计归因。"""
    code = getattr(exc, "code", None)
    if code:
        category, _, _ = classify(str(code), exc)
        return {"error": {"class": category.value, "code": str(code)}}
    if default_infra_code and is_infra_or_timeout_exception(exc):
        target_exc: Exception = exc
        if isinstance(exc, subprocess.TimeoutExpired):
            wrapped = RuntimeError("AI 服务响应超时（子进程超时）")
            wrapped.__cause__ = exc
            target_exc = wrapped
        category, _, _ = classify(default_infra_code, target_exc)
        return {"error": {"class": category.value, "code": default_infra_code}}
    return {}
