"""字段、实体和单位不可因为数字集合相同而被交换。"""
import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.modules.ai import service, briefing
from app.modules.ai.numeric_fidelity import faithful_numbers
from app.modules.ai.schema import BriefingRequest


def test_swapped_metric_values_fall_back(monkeypatch):
    async def chat(*_, **__):
        return SimpleNamespace(answer='{"answer":"金额：3 CNY；数量：1200"}')
    monkeypatch.setattr(service, "chat", chat)
    result = SimpleNamespace(rows=[{"amount": "1200", "quantity": 3}], unit="CNY",
                             render_columns=[{"key": "amount", "label": "金额"},
                                             {"key": "quantity", "label": "数量"}])
    assert asyncio.run(service._rewrite_text2sql_answer(result, "订单", get_settings())) is None


@pytest.mark.parametrize("answer", ["甲公司 金额：300 USD；乙公司 金额：1200 CNY",
                                   "甲公司 金额：1200 USD；乙公司 金额：300 CNY"])
def test_unauthorized_units_fall_back(answer):
    evidence = {"rows": [{"supplier": "甲公司", "amount": 1200, "currency": "CNY"},
                         {"supplier": "乙公司", "amount": 300, "currency": "USD"}],
                "render_columns": [{"key": "amount", "label": "金额"}]}
    assert not faithful_numbers(answer, evidence)


def test_briefing_swapped_values_fall_back(monkeypatch):
    from app.modules.system import data_scope
    monkeypatch.setattr(data_scope, "is_department_restricted", lambda *_: False)
    monkeypatch.setattr(briefing, "build_snapshot", lambda *_, **__: {"overview": {"purchase_orders_total": 12, "open_exceptions": 3}})
    monkeypatch.setattr(briefing, "get_user_role_codes", lambda *_: ["SYS_ADMIN"])
    async def chat(*_, **__):
        return SimpleNamespace(answer="采购订单总数：3；未关闭异常：12", model="fake", provider="fake")
    monkeypatch.setattr(briefing, "chat", chat)
    result = asyncio.run(briefing.generate_briefing(object(), SimpleNamespace(id=1), BriefingRequest(push=False)))
    assert "采购订单总数：12" in result.content
    assert "未关闭异常：3" in result.content


def test_explicit_metric_and_row_associations_are_preserved():
    evidence = {"rows": [{"supplier": "甲公司", "amount": 1200, "currency": "CNY"},
                         {"supplier": "乙公司", "amount": 300, "currency": "USD"}],
                "render_columns": [{"key": "amount", "label": "金额"}]}
    assert faithful_numbers("甲公司 金额：1,200.00 CNY；乙公司 金额：300 USD", evidence)


def test_result_metadata_is_not_a_business_numeric_fact():
    assert not faithful_numbers("金额：2 CNY", {"rows": [{"amount": 1200}], "row_count": 2,
                                             "render_columns": [{"key": "amount", "label": "金额"}], "unit": "CNY"})
