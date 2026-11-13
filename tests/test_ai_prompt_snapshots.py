"""提示词版本与快照回归。"""

import hashlib
import json
from pathlib import Path

import pytest

from app.modules.ai_agent.model_access import prompt_registry


HASHES = json.loads((Path(__file__).parent / "fixtures/prompt_hashes.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(HASHES))
def test_prompt_matches_reviewed_snapshot(name):
    text = prompt_registry.get_prompt(name)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert digest == HASHES[name], "提示词已变更，请审阅并更新快照，同时跑评测对比。"
    assert prompt_registry.prompt_version(name) == f"{name}@1-{digest[:8]}"


def test_registry_contains_all_expected_prompts():
    assert {spec.name for spec in prompt_registry.PROMPT_SPECS} == set(HASHES)


def test_version_tracks_prompt_changes(monkeypatch):
    from app.modules.ai_agent.conversation_context import context_stream

    original = prompt_registry.prompt_version("context_stream")
    assert prompt_registry.prompt_version("context_stream") == original
    monkeypatch.setattr(context_stream, "PROMPT", context_stream.PROMPT + "变更")
    assert prompt_registry.prompt_version("context_stream") != original


def test_unknown_prompt_is_rejected():
    with pytest.raises(KeyError):
        prompt_registry.get_prompt("unknown")
