"""页面上下文协议的契约与鉴权测试；页面只传对象引用，服务端重新取证。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.core.errors import BusinessValidationError
from app.core.errors import AuthorizationError
from app.core.errors import ResourceNotFoundError
from app.modules.ai import context
from app.modules.ai.schema import AIContextAskRequest
from app.modules.deliveries import service as delivery_service
from app.modules.inventory import service as inventory_service
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_requests.model import PurchaseRequest
from app.modules.quality_acceptances import service as quality_acceptance_service

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


def test_finance_reconciliation_context_shows_line_matching_and_payment_cap(monkeypatch) -> None:
    from app.modules.ai import finance_read_model

    reconciliation = SimpleNamespace(
        id=71, reconciliation_no="FR-71", status="CONFIRMED", total_amount=Decimal("100.00"),
        currency_code="CNY", supplier_id=9,
    )
    read_model = {
        "invoices": [{"status": "VERIFIED", "count": 1, "amount": Decimal("80")}],
        "payments": [{"status": "REQUESTED", "count": 1, "amount": Decimal("30")}],
        "lines": [{"reconciliation_item_id": 501, "line_no": 1, "product_name": "乙醇",
            "unit_name": "千克", "ordered_quantity": Decimal("10"), "received_quantity": Decimal("8"),
            "accepted_quantity": Decimal("8"), "returned_quantity": Decimal("0"),
            "reconciliation_quantity": Decimal("8"), "amount_incl_tax": Decimal("100"),
            "invoiced_reserved_amount": Decimal("80"), "verified_invoice_amount": Decimal("80"),
            "warnings": []}],
        "source_changed": True, "line_warnings": ["历史来源版本已变化"],
        "unallocated_invoices": ["FI-UNMATCHED"],
        "payment_precheck": {"verified_invoice_amount": Decimal("80"), "active_payment_amount": Decimal("30"),
            "remaining_reconciliation_amount": Decimal("70"), "max_new_payment_amount": Decimal("70"),
            "currency_code": "CNY", "blockers": [], "limitation": "付款服务提交时重新校验。"},
    }
    monkeypatch.setattr(context.finance_service, "get_reconciliation", lambda *_args: reconciliation)
    monkeypatch.setattr(finance_read_model, "read_reconciliation", lambda *_args: read_model)
    db = SimpleNamespace(get=lambda *_args: SimpleNamespace(supplier_name="示例供应商", supplier_code="SUP-9"))

    response = context.ask_context(db, SimpleNamespace(id=7), AIContextAskRequest(
        question="对账明细和付款前置是什么？",
        context={"object_type": "finance_reconciliation", "object_id": 71},
    ))

    assert "第 1 行 乙醇" in response.answer
    assert "当前单笔付款理论上限 70.00 CNY" in response.answer
    assert "保存版本相比已变化" in response.answer
    assert "FI-UNMATCHED" in response.answer
    assert "付款服务提交时重新校验" in response.answer


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


@pytest.mark.parametrize(
    ("status", "actual_quantity", "expected_phrase"),
    [
        ("IN_TRANSIT", Decimal("0"), "尚未确认收货"),
        ("RECEIVED", Decimal("8"), "已确认收货"),
    ],
)
def test_delivery_context_reads_authorized_delivery_and_returns_receipt_evidence(
    monkeypatch, status, actual_quantity, expected_phrase,
) -> None:
    delivery = SimpleNamespace(
        id=51, delivery_no="DL20261022000051", po_id=11, supplier_id=7,
        status=status, shipment_date=date(2026, 10, 20),
        expected_arrival_date=date(2026, 10, 22), actual_arrival_date=None,
        logistics_company="示例物流", tracking_no="TRACK-51", received_at=None, note=None,
        items=[SimpleNamespace(
            id=61, line_no=1, product_id=9, po_item_id=31, batch_no="B-51",
            package_spec="1 桶/20 千克", planned_quantity=Decimal("10"),
            actual_quantity=actual_quantity, short_quantity=Decimal("0"), unit_id=2,
            production_date=None, expiry_date=None, document_complete=1,
        )],
    )
    seen = {}
    order = SimpleNamespace(id=11, po_no="PO-26001")

    def fake_get_delivery(db, user, delivery_id):
        seen.update(db=db, user_id=user.id, delivery_id=delivery_id)
        return delivery

    monkeypatch.setattr(delivery_service, "get_delivery", fake_get_delivery)
    monkeypatch.setattr(context, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(context, "get_user_permission_codes", lambda *_args: ["warehouse.deliveries.read"])
    monkeypatch.setattr(context, "read_order", lambda _db, _user, order_id: order)

    response = context.ask_context(
        "db-session", SimpleNamespace(id=7),
        AIContextAskRequest(
            question="这张到货单目前进展如何？",
            context={"object_type": "delivery", "object_id": 51},
        ),
    )

    assert seen == {"db": "db-session", "user_id": 7, "delivery_id": 51}
    assert response.model == "delivery-context"
    assert response.context.object_type == "delivery"
    assert response.context.object_id == 51
    assert response.context.reference_no == "DL20261022000051"
    assert response.context.status == status
    assert "采购订单 PO-26001" in response.answer
    assert expected_phrase in response.answer
    assert "计划 10，实收" in response.answer
    assert response.citations[0]["type"] == "delivery-context"
    assert response.citations[0]["source_records"] == response.context.source_records
    assert {item["dataset"] for item in response.context.source_records} == {
        "deliveries", "delivery_items", "purchase_orders",
    }


def test_delivery_context_preserves_not_found_or_scope_denial(monkeypatch) -> None:
    def denied(*_args, **_kwargs):
        raise ResourceNotFoundError("到货单不存在或无权查看")

    monkeypatch.setattr(delivery_service, "get_delivery", denied)
    monkeypatch.setattr(context, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(context, "get_user_permission_codes", lambda *_args: ["warehouse.deliveries.read"])

    with pytest.raises(ResourceNotFoundError, match="无权查看"):
        context.ask_context(
            SimpleNamespace(), SimpleNamespace(id=7),
            AIContextAskRequest(
                question="进展如何？",
                context={"object_type": "delivery", "object_id": 51},
            ),
        )


def test_delivery_context_requires_delivery_read_permission(monkeypatch) -> None:
    def must_not_read(*_args, **_kwargs):
        raise AssertionError("delivery lookup must not run without read permission")

    monkeypatch.setattr(context, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(context, "get_user_permission_codes", lambda *_args: [])
    monkeypatch.setattr(delivery_service, "get_delivery", must_not_read)

    with pytest.raises(AuthorizationError, match="没有到货单读取权限"):
        context.ask_context(
            SimpleNamespace(), SimpleNamespace(id=7),
            AIContextAskRequest(
                question="进展如何？",
                context={"object_type": "delivery", "object_id": 51},
            ),
        )


def test_inventory_balance_context_reads_scoped_balance_and_batch_evidence(monkeypatch) -> None:
    balance = SimpleNamespace(
        id=81, warehouse_id=4, location_id=5, product_id=6, batch_id=7, unit_id=8,
        quantity=Decimal("12.500000"), locked_quantity=Decimal("2.000000"), status="AVAILABLE",
    )
    rows = {
        "Warehouse": SimpleNamespace(id=4, warehouse_name="甲仓", warehouse_code="WH-A"),
        "WarehouseLocation": SimpleNamespace(id=5, location_name="A-01", location_code="A-01"),
        "Product": SimpleNamespace(id=6, product_name="乙醇", product_code="ETOH"),
        "InventoryBatch": SimpleNamespace(id=7, batch_no="B-2026", expiry_date=date(2027, 1, 1), production_date=date(2026, 1, 1)),
        "Unit": SimpleNamespace(id=8, unit_name="千克"),
    }
    db = SimpleNamespace(get=lambda model, _id: rows[model.__name__])
    seen = {}

    def read_balance(_db, user, balance_id):
        seen.update(db=_db, user_id=user.id, balance_id=balance_id)
        return balance

    monkeypatch.setattr(inventory_service, "get_balance_for_user", read_balance)
    monkeypatch.setattr(context, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(context, "get_user_permission_codes", lambda *_args: ["warehouse.inventory.read"])

    response = context.ask_context(
        db, SimpleNamespace(id=7),
        AIContextAskRequest(question="这笔库存余额有多少可用量，批次何时到期？", context={"object_type": "inventory_balance", "object_id": 81}),
    )

    assert seen == {"db": db, "user_id": 7, "balance_id": 81}
    assert response.model == "inventory-balance-context"
    assert response.context.title == "库存余额 #81：乙醇"
    assert response.context.status == "AVAILABLE"
    assert "可用数量：10.500000 千克" in response.answer
    assert "批次：B-2026" in response.answer
    assert "有效期：2027-01-01" in response.answer
    assert response.citations[0]["type"] == "inventory-balance-context"
    assert {source["dataset"] for source in response.context.source_records} == {
        "inventory_balances", "inventory_batches",
    }


def test_inventory_balance_context_requires_permission_before_read(monkeypatch) -> None:
    monkeypatch.setattr(context, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(context, "get_user_permission_codes", lambda *_args: [])
    monkeypatch.setattr(inventory_service, "get_balance_for_user", lambda *_args: pytest.fail("balance read without permission"))

    with pytest.raises(AuthorizationError, match="没有库存读取权限"):
        context.ask_context(
            SimpleNamespace(), SimpleNamespace(id=7),
            AIContextAskRequest(question="库存多少？", context={"object_type": "inventory_balance", "object_id": 81}),
        )


def test_inventory_balance_context_preserves_scope_denial(monkeypatch) -> None:
    monkeypatch.setattr(context, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(context, "get_user_permission_codes", lambda *_args: ["warehouse.inventory.read"])
    monkeypatch.setattr(inventory_service, "get_balance_for_user", lambda *_args: (_ for _ in ()).throw(ResourceNotFoundError("库存余额不存在")))

    with pytest.raises(ResourceNotFoundError, match="库存余额不存在"):
        context.ask_context(
            SimpleNamespace(), SimpleNamespace(id=7),
            AIContextAskRequest(question="库存多少？", context={"object_type": "inventory_balance", "object_id": 81}),
        )


def test_quality_acceptance_context_answers_saved_results_with_delivery_sources(monkeypatch) -> None:
    acceptance = SimpleNamespace(
        id=91, acceptance_no="QA20261022000091", delivery_id=51, result="PASSED",
        inspection_time=None, test_result={"by_delivery_item": {"61": {"外观": "澄清"}}},
        certificate_complete=1, report_file_id=72, conclusion="符合采购要求",
    )
    delivery = SimpleNamespace(
        id=51, delivery_no="DL20261022000051",
        items=[SimpleNamespace(id=61, line_no=1, batch_no="B-91", product_id=9)],
    )
    seen = {}

    def read_acceptance(_db, user, acceptance_id):
        seen.update(user_id=user.id, acceptance_id=acceptance_id)
        return acceptance

    db = SimpleNamespace(get=lambda model, _id: delivery)
    monkeypatch.setattr(quality_acceptance_service, "get_acceptance", read_acceptance)
    monkeypatch.setattr(context, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(context, "get_user_permission_codes", lambda *_args: ["quality.acceptances.read"])

    response = context.ask_context(
        db, SimpleNamespace(id=7),
        AIContextAskRequest(question="这张验收单的检测结果和结论是什么？", context={"object_type": "quality_acceptance", "object_id": 91}),
    )

    assert seen == {"user_id": 7, "acceptance_id": 91}
    assert response.model == "quality-acceptance-context"
    assert response.context.object_type == "quality_acceptance"
    assert response.context.title == "质量验收 QA20261022000091"
    assert response.context.status == "PASSED"
    assert "关联到货单：DL20261022000051" in response.answer
    assert "检测结果：第 1 行 外观：澄清" in response.answer
    assert "验收结论：符合采购要求" in response.answer
    assert "质量证明文件：齐全" in response.answer
    assert "检测报告：已登记" in response.answer
    assert response.citations[0]["type"] == "quality-acceptance-context"
    assert {source["dataset"] for source in response.context.source_records} == {
        "quality_acceptances", "deliveries", "delivery_items",
    }


def test_quality_acceptance_context_requires_read_permission_before_lookup(monkeypatch) -> None:
    monkeypatch.setattr(context, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(context, "get_user_permission_codes", lambda *_args: [])
    monkeypatch.setattr(quality_acceptance_service, "get_acceptance", lambda *_args: pytest.fail("acceptance read without permission"))

    with pytest.raises(AuthorizationError, match="没有质量验收读取权限"):
        context.ask_context(
            SimpleNamespace(), SimpleNamespace(id=7),
            AIContextAskRequest(question="验收结果是什么？", context={"object_type": "quality_acceptance", "object_id": 91}),
        )


def test_quality_acceptance_context_preserves_scope_denial(monkeypatch) -> None:
    monkeypatch.setattr(context, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(context, "get_user_permission_codes", lambda *_args: ["quality.acceptances.read"])
    monkeypatch.setattr(quality_acceptance_service, "get_acceptance", lambda *_args: (_ for _ in ()).throw(ResourceNotFoundError("质量验收记录 91 不存在")))

    with pytest.raises(ResourceNotFoundError, match="质量验收记录 91 不存在"):
        context.ask_context(
            SimpleNamespace(), SimpleNamespace(id=7),
            AIContextAskRequest(question="验收结果是什么？", context={"object_type": "quality_acceptance", "object_id": 91}),
        )


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
