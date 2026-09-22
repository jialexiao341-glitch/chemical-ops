"""AI 回复质量优化：查询答案 LLM 重写、非查询意图的引导式回复。"""

import json
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.ai import agent_prompt, service
from app.modules.ai.intent import Intent
from app.modules.ai.schema import AIChatMessage, AIChatResponse


def _fake_response(content: str) -> AIChatResponse:
    return AIChatResponse(
        message=AIChatMessage(role="assistant", content=content),
        conversation_id=0,
        model="deepseek-flash",
        provider="openai_compatible",
        answer=content,
    )


def _sample_result() -> SimpleNamespace:
    return SimpleNamespace(
        question="查询本月各供应商采购金额",
        rows=[
            {"supplier": "华东化工", "metric_value": "12000.00"},
            {"supplier": "北方试剂", "metric_value": "8000.00"},
        ],
        render_columns=[
            {"key": "supplier", "label": "供应商", "format": "text"},
            {"key": "metric_value", "label": "金额", "format": "amount"},
        ],
        unit="CNY",
        unit_note=None,
        row_count=2,
        truncated=False,
        plan=SimpleNamespace(limit=20),
    )


# ---------- 查询答案重写 ----------


def test_rewrite_answer_uses_llm_json(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    captured = {}

    async def fake_chat(request, settings=None, **kwargs):
        captured["request"] = request
        captured["response_format"] = kwargs.get("response_format")
        return _fake_response('{"answer": "本月华东化工采购金额最高，为 12000.00 元（CNY）。"}')

    monkeypatch.setattr(service, "chat", fake_chat)

    answer = asyncio.run(
        service._rewrite_text2sql_answer(_sample_result(), "采购订单", settings=SimpleNamespace())
    )

    assert answer is not None
    assert "华东化工" in answer
    # 必须带 JSON 模式，且 payload 含用户原问题
    assert captured["response_format"] == {"type": "json_object"}
    user_msg = captured["request"].messages[-1].content
    assert "查询本月各供应商采购金额" in user_msg
    assert "采购订单" in user_msg


def test_rewrite_answer_returns_none_on_model_failure(monkeypatch: pytest.MonkeyPatch):
    async def fake_chat(*_args, **_kwargs):
        raise BusinessValidationError("AI 助手当前未启用")

    monkeypatch.setattr(service, "chat", fake_chat)

    import asyncio

    answer = asyncio.run(
        service._rewrite_text2sql_answer(_sample_result(), "采购订单", settings=SimpleNamespace())
    )

    assert answer is None  # 调用方将回退模板答案


def test_rewrite_answer_returns_none_on_bad_json(monkeypatch: pytest.MonkeyPatch):
    async def fake_chat(*_args, **_kwargs):
        return _fake_response("我觉得这个结果还不错")  # 没有 JSON

    monkeypatch.setattr(service, "chat", fake_chat)

    import asyncio

    answer = asyncio.run(
        service._rewrite_text2sql_answer(_sample_result(), "采购订单", settings=SimpleNamespace())
    )

    assert answer is None


def test_template_fallback_still_works():
    text = service._format_text2sql_result(_sample_result())
    assert "找到了 2 条" in text
    assert "华东化工" in text


# ---------- 非查询意图回复 ----------


def test_compose_project_reply_no_llm(monkeypatch: pytest.MonkeyPatch):
    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("PROJECT 意图不应调用模型")

    monkeypatch.setattr(service, "chat", fake_chat)

    import asyncio

    content, model = asyncio.run(
        service._compose_non_query_reply(Intent.PROJECT, "project_marker", "你有什么功能？")
    )

    assert model == "rule-based"
    assert "采购" in content


def test_compose_greeting_uses_time_variant(monkeypatch: pytest.MonkeyPatch):
    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("GREETING 意图不应调用模型")

    monkeypatch.setattr(service, "chat", fake_chat)

    import asyncio

    content, model = asyncio.run(
        service._compose_non_query_reply(Intent.GREETING, "greeting_marker", "你好")
    )

    assert model == "rule-based"
    # 按当前时段返回问候，且都点名了业务范围
    assert "化运助手" in content


def test_compose_explicit_out_of_scope_stays_fixed(monkeypatch: pytest.MonkeyPatch):
    calls = []

    async def fake_chat(*_args, **_kwargs):
        calls.append(1)
        return _fake_response("不应出现")

    monkeypatch.setattr(service, "chat", fake_chat)

    import asyncio

    content, model = asyncio.run(
        service._compose_non_query_reply(Intent.UNSUPPORTED, "unsupported_marker", "明天天气怎么样")
    )

    assert model == "rule-based"
    assert content == agent_prompt.UNSUPPORTED_REPLY
    assert calls == []  # 明确范围外不浪费模型调用


def test_compose_no_marker_question_gets_llm_guidance(monkeypatch: pytest.MonkeyPatch):
    async def fake_chat(request, *_args, **_kwargs):
        question = request.messages[-1].content
        assert "上周买的东西到货了吗" in question  # 用户原话进了提示词
        return _fake_response("收到。你可以这样问：本周到货的订单有哪些？带上时间或单号会更准确。")

    monkeypatch.setattr(service, "chat", fake_chat)

    import asyncio

    content, model = asyncio.run(
        service._compose_non_query_reply(
            Intent.UNSUPPORTED, "no_supported_marker", "上周买的东西到货了吗"
        )
    )

    assert model == "guidance"
    assert "本周到货" in content


def test_compose_guidance_failure_falls_back_to_fixed(monkeypatch: pytest.MonkeyPatch):
    async def fake_chat(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(service, "chat", fake_chat)

    import asyncio

    content, model = asyncio.run(
        service._compose_non_query_reply(Intent.UNSUPPORTED, "no_supported_marker", "最近怎么样")
    )

    assert model == "rule-based"
    assert content == agent_prompt.UNSUPPORTED_REPLY


def test_compose_empty_message_stays_fixed(monkeypatch: pytest.MonkeyPatch):
    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("空消息不应调用模型")

    monkeypatch.setattr(service, "chat", fake_chat)

    import asyncio

    content, model = asyncio.run(
        service._compose_non_query_reply(Intent.UNSUPPORTED, "empty", "")
    )

    assert model == "rule-based"
    assert content == agent_prompt.UNSUPPORTED_REPLY


# ---------- 提示词与问候 ----------


def test_greeting_reply_time_variants():
    assert "早上好" in agent_prompt.greeting_reply(hour=8)
    assert "下午好" in agent_prompt.greeting_reply(hour=14)
    assert agent_prompt.greeting_reply(hour=22) == agent_prompt.GREETING_REPLY


def test_fallback_guidance_prompt_contains_question_and_rules():
    prompt = agent_prompt.fallback_guidance_prompt("上周买的东西到货了吗")
    assert "上周买的东西到货了吗" in prompt
    assert "禁止编造" in prompt
    assert "120 字" in prompt
    # 示例问法禁止编造逼真的单号/公司名，避免误导用户
    assert "不要编造像真实数据一样" in prompt


def test_result_rewrite_prompt_requires_answering_original_question():
    prompt = agent_prompt.result_rewrite_prompt(json.dumps({"question": "查订单"}, ensure_ascii=False))
    assert "原始问题" in prompt
    assert "查订单" in prompt


def test_system_prompt_has_style_and_readonly_rules():
    assert "先给结论" in agent_prompt.SYSTEM_PROMPT
    assert "不要编造" in agent_prompt.SYSTEM_PROMPT
    assert "不能创建或修改业务数据" in agent_prompt.SYSTEM_PROMPT
