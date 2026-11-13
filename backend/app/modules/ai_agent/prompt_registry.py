"""提示词名称、版本、内容哈希与发布映射的统一登记。"""

from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
from importlib import import_module
import json


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

# 只登记显式发布的变体；未登记版本不能静默回退到当前提示词。
PROMPT_VARIANTS: dict[str, dict[str, str]] = {}


@dataclass(frozen=True)
class PromptRelease:
    """一次任务使用的发布快照；任务启动时写入 run_meta，续答只读该快照。"""

    audience: str
    versions: dict[str, str]

    def version(self, name: str) -> str | None:
        return self.versions.get(name)

    def as_dict(self) -> dict:
        return {"audience": self.audience, "versions": dict(self.versions)}


_current_release: ContextVar[PromptRelease | None] = ContextVar(
    "agent_prompt_release", default=None)


def _spec(name: str) -> PromptSpec:
    for spec in PROMPT_SPECS:
        if spec.name == name:
            return spec
    raise KeyError(name)


def _current_text(name: str) -> str:
    spec = _spec(name)
    return getattr(import_module(f"app.modules.ai_agent.{spec.module}"), spec.attribute)


def _current_version(name: str) -> str:
    spec = _spec(name)
    digest = hashlib.sha256(_current_text(name).encode("utf-8")).hexdigest()
    return f"{name}@{spec.version}-{digest[:8]}"


def register_prompt_variant(name: str, version: str, text: str) -> None:
    """登记一个已审阅的可发布提示词变体；生产映射只能引用已登记版本。"""
    _spec(name)
    if not isinstance(version, str) or not version.strip():
        raise ValueError("提示词版本必须是非空字符串")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("提示词正文必须是非空字符串")
    PROMPT_VARIANTS.setdefault(name, {})[version] = text


def bind_release(release: PromptRelease | None):
    return _current_release.set(release)


def reset_release(token) -> None:
    _current_release.reset(token)


def current_release() -> PromptRelease | None:
    return _current_release.get()


def _selected_version(name: str) -> str | None:
    release = _current_release.get()
    return release.version(name) if release is not None else None


def get_prompt(name: str, version: str | None = None) -> str:
    """返回当前发布版本或显式版本的提示词正文；未登记版本直接失败。"""
    current = _current_text(name)
    selected = version or _selected_version(name)
    if not selected or selected == _current_version(name):
        return current
    variant = PROMPT_VARIANTS.get(name, {}).get(selected)
    if variant is None:
        raise KeyError(f"未登记的提示词版本：{selected}")
    return variant


def prompt_version(name: str, version: str | None = None) -> str:
    """返回显式版本、任务发布版本或当前代码版本的完整标识。"""
    return version or _selected_version(name) or _current_version(name)


def release_from_meta(meta: dict | None) -> PromptRelease | None:
    """从任务 run_meta 恢复发布快照；缺失时返回 None，保持旧任务默认行为。"""
    data = (meta or {}).get("prompt_release")
    if not isinstance(data, dict):
        return None
    versions = data.get("versions")
    cleaned: dict[str, str] = {}
    if isinstance(versions, dict):
        for name in ("routing", "planner"):
            value = versions.get(name)
            if isinstance(value, str) and value:
                cleaned[name] = value
    for name in ("routing", "planner"):
        cleaned.setdefault(name, _current_version(name))
    return PromptRelease(str(data.get("audience") or "default"), cleaned)


def resolve_release(role_codes, raw_json: str | None = None) -> PromptRelease:
    """按角色解析发布映射；未配置时使用当前版本。

    映射格式：``{"default": {"routing": "...", "planner": "..."},
    "roles": {"BUYER": {...}}}``。角色按字母序取第一个命中的映射，避免结果依赖角色列表顺序。
    """
    from app.core.config import get_settings

    raw = get_settings().agent_prompt_release_json if raw_json is None else raw_json
    roles = sorted({str(role) for role in (role_codes or []) if role})
    versions = {name: _current_version(name) for name in ("routing", "planner")}
    if not isinstance(raw, str) or not raw.strip():
        return PromptRelease("default", versions)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("AGENT_PROMPT_RELEASE_JSON 不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("AGENT_PROMPT_RELEASE_JSON 必须是 JSON 对象")
    roles_map = data.get("roles") or {}
    if not isinstance(roles_map, dict):
        raise ValueError("prompt 发布映射的 roles 必须是对象")
    selected = None
    audience = "default"
    for role in roles:
        candidate = roles_map.get(role)
        if candidate is None:
            continue
        if not isinstance(candidate, dict):
            raise ValueError(f"角色 {role} 的 prompt 映射必须是对象")
        selected = candidate
        audience = f"role:{role}"
        break
    if selected is None:
        candidate = data.get("default")
        if candidate is not None:
            if not isinstance(candidate, dict):
                raise ValueError("prompt 发布映射的 default 必须是对象")
            selected = candidate
    if selected:
        unknown = set(selected) - {"routing", "planner"}
        if unknown:
            raise ValueError("未登记的 prompt 名称：" + "、".join(sorted(unknown)))
        for name in ("routing", "planner"):
            value = selected.get(name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 的发布版本必须是非空字符串")
            versions[name] = value
    return PromptRelease(audience, versions)