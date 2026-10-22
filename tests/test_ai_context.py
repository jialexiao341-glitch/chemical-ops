"""页面上下文协议的契约与鉴权测试；页面只传对象引用，服务端重新取证。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.core.errors import BusinessValidationError
from app.core.errors import ResourceNotFoundError
from app.modules.ai import context
from app.modules.ai.schema import AIContextAskRequest
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_requests.model import PurchaseRequest

from .conftest import login


def _order() -> SimpleNamespace:
    """构造与 get_order 返回值同形的订单对象，避免单测依赖数据库。"""
    return SimpleNamespace(
        id=11,
        po_no="PO-26001",
        status="APPROVING",
        order_amount=Decimal("1200.00"),
        currency_code="CNY",
        expected_arrival_date=date(2026, 11, 3),
    )


def _trace() -> dict:
    return {
        "po_no": "PO-26001",
        "supplier": "示例供应商",
        "order_status": "APPROVING",
        "stages": [
            {"stage": "采购订单", "status": "AVAILABLE", "summary": "找到 1 条记录", "records": [{"number": "PO-26001", "status": "APPROVING"}]},
        ],
        "conclusion": ["尚未建立财务对账记录"],
        "unavailable_stages": ["发票"],
        "source_records": [{"dataset": "purchase_orders", "label": "采购订单 PO-26001", "record_id": 11}],
        "answer": "订单 PO-26001 跨模块追溯\n可见数据中的未完成原因：尚未建立财务对账记录。",
    }


def test_purchase_order_context_uses_server_side_trace(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_get_order(_db, _user, order_id):
        seen["order_id"] = order_id
        return _order()

    def fake_trace(_db, _user, po_no):
        seen["po_no"] = po_no
        return _trace()

    monkeypatch.setattr(context, "get_order", fake_get_order)
    monkeypatch.setattr(context, "trace_purchase_order", fake_trace)

    response = context.ask_context(
        SimpleNamespace(),
        SimpleNamespace(id=7),
        AIContextAskRequest(question="这单为什么还没结算？", context={"object_type": "purchase_order", "object_id": 11}),
    )

    # 页面提交的只有对象 ID；订单号来自服务端读取结果，不接受客户端业务字段。
    assert seen == {"order_id": 11, "po_no": "PO-26001"}
    assert response.model == "order-trace"
    assert response.answer == _trace()["answer"]
    assert response.context.object_type == "purchase_order"
    assert response.context.object_id == 11
    assert response.context.title == "采购订单 PO-26001"
    assert response.context.reference_no == "PO-26001"
    assert response.context.status == "APPROVING"
    assert "供应商：示例供应商" in response.context.summary
    assert "订单金额：1200.00 CNY" in response.context.summary
    assert "预计到货日期：2026-11-03" in response.context.summary
    assert response.context.suggested_questions
    assert response.citations[0]["type"] == "order_trace"
    assert response.citations[0]["po_no"] == "PO-26001"
    assert response.citations[0]["order_trace"] == _trace()


def test_purchase_request_context_reads_authorized_request_and_returns_lines(monkeypatch) -> None:
    seen: dict[str, object] = {}
    request = SimpleNamespace(
        id=21, request_no="PR20261022000021", status="PENDING_APPROVAL", purpose="实验室补充溶剂",
        priority="HIGH", budget_amount=Decimal("2500.00"), currency_code="CNY",
        approvals=[],
        expected_date=date(2026, 11, 10), items=[SimpleNamespace(
            id=31, line_no=1, requested_name="乙醇", quantity=Decimal("50.000000"), unit_id=2,
            budget_price=Decimal("50.00"), status="OPEN",
        )],
    )

    def fake_get_request(_db, _user, request_id):
        seen["request_id"] = request_id
        return request

    monkeypatch.setattr(context, "get_purchase_request", fake_get_request)
    monkeypatch.setattr(context, "_purchase_request_trace", lambda *_args: ([], []))

    response = context.ask_context(
        SimpleNamespace(), SimpleNamespace(id=7),
        AIContextAskRequest(question="采购用途和明细是什么？", context={"object_type": "purchase_request", "object_id": 21}),
    )

    assert seen == {"request_id": 21}
    assert response.model == "purchase-request-trace"
    assert response.context.title == "采购申请 PR20261022000021"
    assert response.context.status == "PENDING_APPROVAL"
    assert "实验室补充溶剂" in response.answer
    assert "乙醇" in response.answer
    assert "50.000000" in response.answer
    assert "#2" in response.answer
    assert response.citations[0]["type"] == "purchase-request-trace"
    assert response.context.source_records == [
        {"dataset": "purchase_requests", "record_id": 21, "label": "采购申请 PR20261022000021"},
        {"dataset": "purchase_request_items", "record_id": 31, "label": "采购明细 1：乙醇"},
    ]


def test_purchase_request_context_answers_the_asked_field_and_only_suggests_supported_questions(monkeypatch) -> None:
    request = SimpleNamespace(
        id=21, request_no="PR20261022000021", status="PENDING_APPROVAL", purpose="实验室补充溶剂",
        budget_amount=Decimal("2500.00"), currency_code="CNY", expected_date=date(2026, 11, 10), approvals=[],
        items=[SimpleNamespace(id=31, line_no=1, requested_name="乙醇", quantity=Decimal("50"), unit_id=2, status="OPEN")],
    )
    monkeypatch.setattr(context, "get_purchase_request", lambda *_args: request)
    monkeypatch.setattr(context, "_purchase_request_trace", lambda *_args: ([], []))

    response = context.ask_context(
        SimpleNamespace(), SimpleNamespace(id=7),
        AIContextAskRequest(question="当前审批状态是什么？", context={"object_type": "purchase_request", "object_id": 21}),
    )

    assert response.answer == "采购申请 PR20261022000021 当前状态：PENDING_APPROVAL。当前读取的是申请状态字段，不包含审批节点或审批意见。"
    assert response.context.suggested_questions == [
        "关联询价与报价进展如何？", "采购订单到货和验收进展如何？", "当前流程卡在哪个环节？",
    ]


def test_purchase_request_context_reports_downstream_procurement_trace(monkeypatch) -> None:
    request = SimpleNamespace(
        id=21, request_no="PR20261022000021", status="APPROVED", purpose="实验室补充溶剂",
        budget_amount=None, currency_code="CNY", expected_date=None, approvals=[],
        items=[SimpleNamespace(id=31, line_no=1, requested_name="乙醇", quantity=Decimal("50"), unit_id=2, status="OPEN")],
    )
    stages = [
        {"stage": "询价与报价", "status": "AVAILABLE", "summary": "关联询价单  RFQ-1；报价 2 条", "records": [{"number": "RFQ-1", "status": "SENT"}]},
        {"stage": "采购订单", "status": "NO_DATA", "summary": "没有查到关联记录", "records": []},
    ]
    sources = [{"dataset": "rfqs", "record_id": 41, "label": "询价单 RFQ-1"}]
    monkeypatch.setattr(context, "get_purchase_request", lambda *_args: request)
    monkeypatch.setattr(context, "_purchase_request_trace", lambda *_args: (stages, sources))

    response = context.ask_context(
        SimpleNamespace(), SimpleNamespace(id=7),
        AIContextAskRequest(question="这份申请后续采购流程走到哪了？", context={"object_type": "purchase_request", "object_id": 21}),
    )

    assert "RFQ-1" in response.answer
    assert "采购订单：没有查到关联记录" in response.answer
    assert response.citations[0]["type"] == "purchase-request-trace"
    assert all(source in response.citations[0]["source_records"] for source in sources)


def test_context_question_cannot_supply_business_snapshot() -> None:
    """客户端附带业务字段必须被拒绝，否则可伪造订单状态影响回答。"""
    with pytest.raises(ValidationError):
        AIContextAskRequest.model_validate({
            "question": "为什么还没结算",
            "context": {"object_type": "purchase_order", "object_id": 11, "status": "CLOSED"},
        })

    with pytest.raises(ValidationError):
        AIContextAskRequest.model_validate({
            "question": "为什么还没结算",
            "context": {"object_type": "purchase_order", "object_id": True},
        })

    with pytest.raises(ValidationError):
        AIContextAskRequest.model_validate({"question": "为什么还没结算"})


def test_unsupported_page_object_is_rejected_explicitly() -> None:
    with pytest.raises(BusinessValidationError, match="暂不支持"):
        context.resolve_context(
            SimpleNamespace(),
            SimpleNamespace(id=7),
            AIContextAskRequest(question="这单卡在哪", context={"object_type": "rfq", "object_id": 3}),
        )


def test_context_ask_requires_login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ai/context/ask",
        json={"question": "这单为什么还没结算", "context": {"object_type": "purchase_order", "object_id": 1}},
    )

    assert response.status_code == 401


def test_context_ask_returns_trace_for_existing_order(client: TestClient, db_session, demo_password) -> None:
    order_id = db_session.scalar(select(PurchaseOrder.id).order_by(PurchaseOrder.id))
    if order_id is None:
        pytest.skip("当前测试库没有采购订单样本")

    headers = login(client, "system_admin", demo_password)
    response = client.post(
        "/api/v1/ai/context/ask",
        headers=headers,
        json={"question": "这单为什么还没结算？", "context": {"object_type": "purchase_order", "object_id": order_id}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"] == "order-trace"
    assert body["context"]["object_id"] == order_id
    assert body["context"]["reference_no"]
    assert body["context"]["reference_no"] in body["answer"]
    assert body["citations"][0]["type"] == "order_trace"
    assert body["citations"][0]["source_records"] == body["context"]["source_records"]


def test_context_ask_traces_downstream_records_for_existing_request(client: TestClient, db_session, demo_password) -> None:
    request_id = db_session.scalar(select(PurchaseRequest.id).order_by(PurchaseRequest.id))
    if request_id is None:
        pytest.skip("当前测试库没有采购申请样本")

    headers = login(client, "system_admin", demo_password)
    response = client.post(
        "/api/v1/ai/context/ask",
        headers=headers,
        json={"question": "这份申请后续采购流程走到哪里了？", "context": {"object_type": "purchase_request", "object_id": request_id}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"] == "purchase-request-trace"
    assert "询价与报价" in body["answer"]
    assert "采购订单" in body["answer"]
    assert body["citations"][0]["type"] == "purchase-request-trace"
    assert body["citations"][0]["stages"]


def test_context_ask_maps_missing_order_to_404(client: TestClient, db_session, demo_password) -> None:
    headers = login(client, "system_admin", demo_password)
    missing_id = (db_session.scalar(select(PurchaseOrder.id).order_by(PurchaseOrder.id.desc())) or 0) + 1
    response = client.post(
        "/api/v1/ai/context/ask",
        headers=headers,
        json={"question": "为什么没结算", "context": {"object_type": "purchase_order", "object_id": missing_id}},
    )

    assert response.status_code == 404
    assert response.json()["detail"]


def test_context_ask_maps_unsupported_object_to_400(client: TestClient, demo_password) -> None:
    headers = login(client, "system_admin", demo_password)
    response = client.post(
        "/api/v1/ai/context/ask",
        headers=headers,
        json={"question": "这单卡在哪", "context": {"object_type": "rfq", "object_id": 1}},
    )

    assert response.status_code == 400
    assert "暂不支持" in response.json()["detail"]


def _stage_trace() -> dict:
    def stage(name: str, records: list[dict] | None = None) -> dict:
        values = records or []
        return {"stage": name, "status": "AVAILABLE" if values else "NO_DATA", "summary": "找到 1 条记录" if values else "没有查到关联记录", "records": values}

    return {
        "po_no": "PO-26001",
        "supplier": "示例供应商",
        "order_status": "ORDERED",
        "stages": [
            stage("采购申请", [{"number": "PR-1", "status": "APPROVED"}]),
            stage("采购订单", [{"number": "PO-26001", "status": "ORDERED"}]),
            stage("到货", [{"number": "DN-1", "status": "RECEIVED"}]),
            stage("财务对账", [{"number": "FR-1", "status": "PENDING"}]),
            stage("发票"),
            stage("付款"),
            stage("结算"),
        ],
        "conclusion": ["财务对账仍为 PENDING", "尚未生成结算单"],
        "unavailable_stages": [],
        "source_records": [],
        "answer": "订单 PO-26001 跨模块追溯\n供应商：示例供应商；订单状态：ORDERED。",
    }


def test_finance_question_focuses_the_full_finance_chain() -> None:
    """问结算时把对账、发票、付款、结算一起给出，否则看不到未完成原因的前因。"""

    answer = context._answer_for_question("这单为什么还没结算？", _stage_trace())

    assert answer.startswith("订单 PO-26001 的财务对账、发票、付款、结算情况")
    assert "- 到货：" not in answer
    assert "财务对账仍为 PENDING" in answer
    assert "尚未生成结算单" in answer
    assert "全流程" in answer


def test_stage_question_does_not_show_unrelated_finance_conclusion() -> None:
    answer = context._answer_for_question("到货了吗？", _stage_trace())

    assert "- 到货：DN-1（RECEIVED）" in answer
    assert "财务对账" not in answer
    assert "未完成原因" not in answer


def test_question_without_stage_keeps_the_full_trace() -> None:
    trace = _stage_trace()
    assert context._answer_for_question("这单怎么样？", trace) == trace["answer"]


def test_finance_question_without_finance_stages_falls_back_to_full_trace() -> None:
    """追溯结果缺少财务环节时（例如权限裁剪或测试替身）不能用聚焦回答掩盖事实。"""

    trace = _stage_trace()
    trace["stages"] = [stage for stage in trace["stages"] if stage["stage"] not in context.FINANCE_STAGES]
    assert context._answer_for_question("这单为什么还没结算？", trace) == trace["answer"]


def test_trace_not_found_error_is_not_swallowed(monkeypatch) -> None:
    """订单追溯的权限拒绝必须原样抛出，页面 Copilot 不能降级为通用回答。"""

    def denied(*_args, **_kwargs):
        raise ResourceNotFoundError("订单 PO-26001 不存在或无权查看")

    monkeypatch.setattr(context, "get_order", lambda *_a, **_k: _order())
    monkeypatch.setattr(context, "trace_purchase_order", denied)

    with pytest.raises(ResourceNotFoundError):
        context.ask_context(
            SimpleNamespace(),
            SimpleNamespace(id=7),
            AIContextAskRequest(question="为什么没结算", context={"object_type": "purchase_order", "object_id": 11}),
        )
