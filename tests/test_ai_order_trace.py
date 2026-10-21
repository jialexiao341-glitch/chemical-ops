"""AI 订单追溯路由与权限结果测试。"""

import asyncio
from types import SimpleNamespace

from app.core.config import Settings
from app.modules.ai.schema import Intent
from app.modules.ai.evaluation import classify_intent
from app.modules.ai.order_trace import _can_read, _stage, extract_order_trace_no


def test_order_trace_requires_order_number_and_trace_question() -> None:
    question = "订单 PO-26001 为什么还没有结算？"

    assert classify_intent(question).intent is Intent.QUERY
    assert extract_order_trace_no(question) == "PO-26001"
    assert extract_order_trace_no("查询订单 PO-26001") is None
    assert extract_order_trace_no("为什么订单还没有结算") is None


def test_order_trace_accepts_production_order_number_without_rewriting_it() -> None:
    assert extract_order_trace_no("采购订单 PO20261021000001 为什么还没有结算？") == "PO20261021000001"
    assert extract_order_trace_no("采购订单 po_26001 为什么还没有结算？") == "PO_26001"
    assert extract_order_trace_no("为什么 POST 请求失败") is None
    assert extract_order_trace_no("为什么 POBOX 还没有结算") is None


def test_denied_stage_does_not_expose_records_or_counts() -> None:
    denied = _stage("发票", False, [{"number": "INV-SECRET", "amount": "1000"}], summary="找到 1 条记录")

    assert denied == {
        "stage": "发票",
        "status": "NO_PERMISSION",
        "summary": "当前账号没有该环节的读取权限",
        "records": [],
    }
    assert not _can_read("发票", set(), set())
    assert _can_read("发票", {"finance.invoices.read"}, set())
    assert _can_read("发票", set(), {"SYS_ADMIN"})


def test_order_trace_route_returns_deterministic_citation_without_text2sql(monkeypatch) -> None:
    from app.modules.ai import order_trace, service

    expected = {
        "po_no": "PO-26001",
        "supplier": "示例供应商",
        "order_status": "OPEN",
        "order_updated_at": None,
        "stages": [
            {"stage": "采购订单", "status": "AVAILABLE", "summary": "找到 1 条记录", "records": [{"number": "PO-26001", "status": "OPEN"}]}
        ],
        "conclusion": ["尚未建立财务对账记录"],
        "unavailable_stages": ["发票"],
        "source_records": [{"dataset": "purchase_orders", "label": "采购订单 PO-26001", "record_id": 1}],
        "answer": "订单 PO-26001 跨模块追溯\n基于可见数据。",
    }
    monkeypatch.setattr(order_trace, "trace_purchase_order", lambda *_args: expected)

    async def unexpected_text2sql(*_args, **_kwargs):
        raise AssertionError("订单追溯不应调用模型生成查询计划")

    monkeypatch.setattr("app.modules.ai.text2sql.run_text2sql", unexpected_text2sql)

    answer, citation, trace = asyncio.run(
        service._run_text2sql_for_chat(
            SimpleNamespace(),
            SimpleNamespace(id=7),
            "订单 PO-26001 为什么还没有结算？",
            Settings(),
        )
    )

    assert answer == expected["answer"]
    assert citation["type"] == "order_trace"
    assert citation["source_records"] == expected["source_records"]
    assert citation["order_trace"] == expected
    assert trace.dataset == "purchase_order_trace"
    assert trace.rows[0]["stage"] == "采购订单"
    assert trace.rows[0]["records"][0]["number"] == "PO-26001"

