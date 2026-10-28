"""模型改写数值、币种和数量级时必须回退服务端文案。"""
import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.modules.ai.numeric_fidelity import faithful_numbers
from app.modules.ai import service, briefing
from app.modules.ai.schema import BriefingRequest


@pytest.mark.parametrize("answer,expected", [
    ("金额 1,200.000 CNY", True), ("金额 1201 CNY", False), ("金额1201元", False),
    ("金额 1200 USD", False), ("数量 1200 千克", False),
    ("金额 1.2 万元", False), ("金额一千二百元", False),
])
def test_numeric_literal_and_unit_allowlist(answer, expected):
    assert faithful_numbers(answer, {"rows": [{"metric_value": "1200.00"}], "unit": "CNY"}) is expected


@pytest.mark.parametrize("answer", ["金额 999 CNY", "金额 12 USD"])
def test_query_rewrite_does_not_trust_question_numbers(monkeypatch, answer):
    async def chat(*_, **__):
        return SimpleNamespace(answer='{"answer":"' + answer + '"}')
    monkeypatch.setattr(service, "chat", chat)
    result = SimpleNamespace(question="请说金额为 999", rows=[{"metric_value": "12"}], unit="CNY", row_count=1)
    assert asyncio.run(service._rewrite_text2sql_answer(result, "订单", get_settings())) is None


def test_briefing_falls_back_before_push(monkeypatch):
    from app.modules.system import data_scope
    monkeypatch.setattr(data_scope, "is_department_restricted", lambda *_: False)
    monkeypatch.setattr(data_scope, "is_warehouse_restricted", lambda *_: False)
    snapshot = {"date": "2026-10-21", "overview": {"purchase_orders_total": 12, "open_exceptions": 3}}
    monkeypatch.setattr(briefing, "build_snapshot", lambda *_, **__: snapshot)
    monkeypatch.setattr(briefing, "get_user_role_codes", lambda *_: ["SYS_ADMIN"])
    async def chat(*_, **__):
        return SimpleNamespace(answer="【概览】采购订单 999 单。", model="fake", provider="fake")
    monkeypatch.setattr(briefing, "chat", chat)
    result = asyncio.run(briefing.generate_briefing(object(), SimpleNamespace(id=1), BriefingRequest(push=False)))
    assert "999" not in result.content
    assert "采购订单总数：12" in result.content
    assert "未关闭异常：3" in result.content
