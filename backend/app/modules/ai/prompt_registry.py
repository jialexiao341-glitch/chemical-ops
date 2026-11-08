"""提示词名称、版本和内容哈希的统一登记。"""

from dataclasses import dataclass
import hashlib
from importlib import import_module


@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: int
    module: str
    attribute: str


PROMPT_SPECS = (
    PromptSpec("routing", 1, "routing", "ROUTING_PROMPT"),
    PromptSpec("planner", 1, "agent_runtime", "PLANNER_PROMPT"),
    PromptSpec("system", 1, "agent_prompt", "SYSTEM_PROMPT"),
    PromptSpec("text2sql_plan", 1, "agent_prompt", "TEXT2SQL_PLAN_PROMPT"),
    PromptSpec("result_rewrite", 1, "agent_prompt", "RESULT_REWRITE_PROMPT"),
    PromptSpec("fallback_guidance", 1, "agent_prompt", "FALLBACK_GUIDANCE_PROMPT"),
    PromptSpec("context_stream", 1, "context_stream", "PROMPT"),
    PromptSpec("guidance", 1, "agent_prompt", "GUIDANCE_PROMPT"),
)


def _spec(name: str) -> PromptSpec:
    for spec in PROMPT_SPECS:
        if spec.name == name:
            return spec
    raise KeyError(name)


def get_prompt(name: str) -> str:
    """延迟读取原始提示词，避免模块间循环导入。"""
    spec = _spec(name)
    return getattr(import_module(f"app.modules.ai.{spec.module}"), spec.attribute)


def prompt_version(name: str) -> str:
    """返回登记版本及当前提示词内容的短哈希。"""
    spec = _spec(name)
    digest = hashlib.sha256(get_prompt(name).encode("utf-8")).hexdigest()
    return f"{name}@{spec.version}-{digest[:8]}"
