"""只读工具单任务调用配额：第 N 次放行、第 N + 1 次拒绝，计数按工具隔离。"""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.modules.ai_agent.agent_execution import agent_tools as tools
from app.modules.ai_agent.schema import ToolCall, ToolSchema


class FakeInput(ToolSchema):
    value: int = 1


class FakeOutput(ToolSchema):
    ok: bool = True


def _spec(name: str) -> tools.ToolSpec:
    return tools.ToolSpec(
        name=name, description="测试只读工具", permission="fake.read",
        input_schema=FakeInput, output_schema=FakeOutput,
        handler=lambda _db, _user, _arguments: FakeOutput(ok=True),
        version="1.0", risk="READ_ONLY", retry_policy="MANUAL_ONLY",
        idempotent=True, cost_class="DATABASE_READ",
        quota_class=tools.TOOL_QUOTA_PER_TASK_CALLS,
    )


@pytest.fixture
def fake_db():
    return SimpleNamespace(no_autoflush=nullcontext())


def _execute(fake_db, tool: str, *, value: int = 1):
    return tools.execute_tool(fake_db, SimpleNamespace(id=1),
                              ToolCall(tool=tool, arguments={"value": value}))


def test_nth_plus_one_tool_call_is_rejected(monkeypatch, fake_db):
    spec = _spec("fake.read")
    monkeypatch.setattr(tools, "TOOLS", {spec.name: spec})
    monkeypatch.setattr(tools, "_permissions", lambda *_args: (True, set()))
    quota = tools.ToolCallQuota(limit=2, counts={})
    token = tools.bind_tool_call_quota(quota)
    try:
        assert _execute(fake_db, "fake.read").ok is True
        assert _execute(fake_db, "fake.read").ok is True
        with pytest.raises(tools.ToolQuotaExceeded) as exc:
            _execute(fake_db, "fake.read")
    finally:
        tools.reset_tool_call_quota(token)

    assert exc.value.tool == "fake.read"
    assert exc.value.limit == 2
    assert quota.counts == {"fake.read": 2}


def test_quota_is_counted_per_tool(monkeypatch, fake_db):
    specs = {name: _spec(name) for name in ("fake.a", "fake.b")}
    monkeypatch.setattr(tools, "TOOLS", specs)
    monkeypatch.setattr(tools, "_permissions", lambda *_args: (True, set()))
    quota = tools.ToolCallQuota(limit=1, counts={})
    token = tools.bind_tool_call_quota(quota)
    try:
        _execute(fake_db, "fake.a")
        with pytest.raises(tools.ToolQuotaExceeded):
            _execute(fake_db, "fake.a")
        assert _execute(fake_db, "fake.b").ok is True
    finally:
        tools.reset_tool_call_quota(token)


def test_existing_counts_continue_across_turns(monkeypatch, fake_db):
    spec = _spec("fake.read")
    monkeypatch.setattr(tools, "TOOLS", {spec.name: spec})
    monkeypatch.setattr(tools, "_permissions", lambda *_args: (True, set()))
    counts = {"fake.read": 1}
    quota = tools.ToolCallQuota(limit=2, counts=counts)
    token = tools.bind_tool_call_quota(quota)
    try:
        _execute(fake_db, "fake.read")
        with pytest.raises(tools.ToolQuotaExceeded):
            _execute(fake_db, "fake.read")
    finally:
        tools.reset_tool_call_quota(token)

    assert counts == {"fake.read": 2}


def test_no_bound_quota_keeps_original_behavior(monkeypatch, fake_db):
    spec = _spec("fake.read")
    monkeypatch.setattr(tools, "TOOLS", {spec.name: spec})
    monkeypatch.setattr(tools, "_permissions", lambda *_args: (True, set()))

    assert tools.current_tool_call_quota() is None
    assert _execute(fake_db, "fake.read").ok is True
    assert _execute(fake_db, "fake.read").ok is True


def test_unmetered_tool_is_not_counted(monkeypatch, fake_db):
    spec = _spec("fake.read")
    object.__setattr__(spec, "quota_class", "UNMETERED")
    monkeypatch.setattr(tools, "TOOLS", {spec.name: spec})
    monkeypatch.setattr(tools, "_permissions", lambda *_args: (True, set()))
    quota = tools.ToolCallQuota(limit=1, counts={})
    token = tools.bind_tool_call_quota(quota)
    try:
        assert _execute(fake_db, "fake.read").ok is True
        assert _execute(fake_db, "fake.read").ok is True
    finally:
        tools.reset_tool_call_quota(token)

    assert quota.counts == {}