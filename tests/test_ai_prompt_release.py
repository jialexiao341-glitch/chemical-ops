"""Prompt 发布映射：角色选择、变体正文、快照恢复与回滚隔离。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.modules.ai import agent_runtime as runtime, prompt_registry, routing
from app.modules.ai.prompt_registry import PromptRelease


@pytest.fixture(autouse=True)
def _clean_release_state():
    prompt_registry.PROMPT_VARIANTS.clear()
    token = prompt_registry.bind_release(None)
    prompt_registry.reset_release(token)
    yield
    prompt_registry.PROMPT_VARIANTS.clear()
    token = prompt_registry.bind_release(None)
    prompt_registry.reset_release(token)


def _current(name: str) -> str:
    return prompt_registry.prompt_version(name)


def _release(version: str, *, audience: str = "role:BUYER") -> PromptRelease:
    return PromptRelease(audience, {
        "routing": version, "planner": _current("planner")})


def test_resolve_release_prefers_sorted_role_then_default():
    raw = json.dumps({
        "default": {"routing": _current("routing"), "planner": _current("planner")},
        "roles": {
            "SYS_ADMIN": {"routing": "routing@1-admin", "planner": "planner@1-admin"},
            "BUYER": {"routing": "routing@1-buyer", "planner": "planner@1-buyer"},
        },
    })

    release = prompt_registry.resolve_release(["SYS_ADMIN", "BUYER"], raw)

    assert release.audience == "role:BUYER"
    assert release.version("routing") == "routing@1-buyer"
    assert release.version("planner") == "planner@1-buyer"


def test_resolve_release_falls_back_to_default_and_rejects_bad_mapping():
    raw = json.dumps({
        "default": {"routing": _current("routing")},
        "roles": {"BUYER": {"routing": "routing@1-buyer"}},
    })

    release = prompt_registry.resolve_release(["SALES"], raw)

    assert release.audience == "default"
    assert release.version("routing") == _current("routing")
    assert release.version("planner") == _current("planner")

    with pytest.raises(ValueError, match="不是合法 JSON"):
        prompt_registry.resolve_release([], "{")
    with pytest.raises(ValueError, match="未登记的 prompt 名称"):
        prompt_registry.resolve_release([], json.dumps(
            {"default": {"unknown": "x"}}))


def test_registered_variant_is_used_and_versioned():
    prompt_registry.register_prompt_variant("routing", "routing@1-buyer", "BUYER ROUTING")
    token = prompt_registry.bind_release(_release("routing@1-buyer"))
    try:
        assert prompt_registry.get_prompt("routing") == "BUYER ROUTING"
        assert prompt_registry.prompt_version("routing") == "routing@1-buyer"
        assert prompt_registry.current_release().audience == "role:BUYER"
    finally:
        prompt_registry.reset_release(token)

    assert prompt_registry.get_prompt("routing") == routing.ROUTING_PROMPT


def test_unregistered_release_version_fails_closed():
    token = prompt_registry.bind_release(_release("routing@1-missing"))
    try:
        with pytest.raises(KeyError, match="未登记的提示词版本"):
            prompt_registry.get_prompt("routing")
    finally:
        prompt_registry.reset_release(token)


def test_release_snapshot_survives_config_rollback():
    prompt_registry.register_prompt_variant("routing", "routing@1-buyer", "BUYER ROUTING")
    old = prompt_registry.resolve_release(["BUYER"], json.dumps({
        "roles": {"BUYER": {"routing": "routing@1-buyer"}}}))
    token = prompt_registry.bind_release(old)
    try:
        # 回滚只切映射；已启动任务仍使用自己的快照。
        rolled_back = prompt_registry.resolve_release(["BUYER"], json.dumps({
            "default": {"routing": _current("routing")}}))
        assert rolled_back.audience == "default"
        assert prompt_registry.get_prompt("routing") == "BUYER ROUTING"

        restored = prompt_registry.release_from_meta({"prompt_release": old.as_dict()})
        assert restored == old
    finally:
        prompt_registry.reset_release(token)

    assert prompt_registry.release_from_meta({}) is None


def test_record_prompt_uses_persisted_release_without_context():
    release = _release("routing@1-buyer")
    state = SimpleNamespace(run_meta={"prompt_release": release.as_dict()})

    runtime._record_prompt(state, "routing")

    assert state.run_meta["prompt_versions"]["routing"] == "routing@1-buyer"


def test_routing_understand_uses_released_prompt(monkeypatch):
    captured = []

    async def fake_chat(_request, _settings, *, response_format, system_prompt,
                        interpret_only=False):
        captured.append(system_prompt)
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            "purpose": "query", "execution_mode": "agent",
            "tasks": ["inventory"], "dialogue_action": "new",
        })))

    prompt_registry.register_prompt_variant("routing", "routing@1-buyer", "BUYER ROUTING")
    monkeypatch.setattr(routing.llm, "chat", fake_chat)
    token = prompt_registry.bind_release(_release("routing@1-buyer"))
    try:
        result = asyncio.run(routing.understand("查乙醇库存"))
    finally:
        prompt_registry.reset_release(token)

    assert result.purpose == "query"
    assert captured == ["BUYER ROUTING"]