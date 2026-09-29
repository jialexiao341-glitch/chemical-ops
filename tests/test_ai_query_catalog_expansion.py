"""新增业务汇总的 SQL 口径与读取权限。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from app.core.errors import BusinessValidationError
from app.modules.ai import text2sql
from app.modules.ai.text2sql import _inventory_movement_trace_plan, _supplier_profile_plan
from app.modules.ai.catalog import CATALOG, catalog_prompt
from app.modules.ai.text2sql import QueryFilter, QueryPlan, _normalize_query_plan_payload, _reject_unsupported_metric, _validate_plan, build_statement
from app.modules.inventory import service as inventory_service


@pytest.mark.parametrize(
    ("dataset", "metric", "expected_table", "expected_value"),
    [
        ("supplier_quotes", "count", "supplier_quotes", "count(supplier_quotes.id)"),
        ("inventory_transactions", "count", "inventory_transactions", "count(inventory_transactions.id)"),
        ("finance_invoices", "amount", "finance_invoices", "sum(finance_invoices.amount_incl_tax)"),
        ("finance_payments", "amount", "finance_payments", "sum(finance_payments.amount)"),
    ],
)
def test_new_catalog_queries_use_business_fields_and_are_model_visible(
    dataset: str, metric: str, expected_table: str, expected_value: str
) -> None:
    group_by = "type" if dataset == "inventory_transactions" else "status"
    statement = build_statement(QueryPlan(dataset=dataset, metric=metric, group_by=group_by, limit=10))
    sql = str(statement).lower()

    assert dataset in catalog_prompt()
    assert expected_table in CATALOG[dataset].tables
    assert expected_value in sql
    assert "group by" in sql
    if metric == "amount":
        assert "currency" in sql  # 金额按币种拆分，不跨币种求和。


@pytest.mark.parametrize(
    ("dataset", "permission"),
    [
        ("supplier_quotes", "procurement.rfqs.read"),
        ("inventory_transactions", "warehouse.inventory.read"),
        ("finance_invoices", "finance.invoices.read"),
        ("finance_payments", "finance.payments.read"),
    ],
)
def test_new_catalog_queries_require_matching_permission(
    monkeypatch: pytest.MonkeyPatch, dataset: str, permission: str
) -> None:
    user = SimpleNamespace(id=1)
    plan = QueryPlan(dataset=dataset, metric="count")
    monkeypatch.setattr(text2sql, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(text2sql, "get_user_permission_codes", lambda *_args: [])
    with pytest.raises(BusinessValidationError, match="没有执行"):
        _validate_plan(SimpleNamespace(), user, plan)

    monkeypatch.setattr(text2sql, "get_user_permission_codes", lambda *_args: [permission])
    _validate_plan(SimpleNamespace(), user, plan)


def test_quote_price_and_inventory_quantities_cannot_be_misaggregated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(text2sql, "get_user_role_codes", lambda *_args: ["SYS_ADMIN"])
    monkeypatch.setattr(text2sql, "get_user_permission_codes", lambda *_args: [])
    for dataset in ("supplier_quotes", "inventory_transactions"):
        with pytest.raises(BusinessValidationError, match="指标"):
            _validate_plan(SimpleNamespace(), SimpleNamespace(id=1), QueryPlan(dataset=dataset, metric="amount"))


def test_paid_amount_keeps_status_and_paid_date_filters() -> None:
    plan = QueryPlan(
        dataset="finance_payments",
        metric="amount",
        time_field="paid_at",
        date_from="2026-09-01",
        date_to="2026-09-30",
        filters=[QueryFilter(field="status", value="PAID")],
    )
    sql = str(build_statement(plan)).lower()
    assert "finance_payments.status =" in sql
    assert "finance_payments.paid_at >=" in sql
    assert "finance_payments.paid_at <" in sql


def test_quote_and_inventory_counts_respect_user_data_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(id=7)
    db = SimpleNamespace()
    monkeypatch.setattr(text2sql, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(inventory_service, "accessible_warehouse_ids", lambda *_args: {3, 5})

    quote_sql = str(build_statement(QueryPlan(dataset="supplier_quotes", metric="count"), db, user)).lower()
    movement_sql = str(build_statement(QueryPlan(dataset="inventory_transactions", metric="count"), db, user)).lower()

    assert "rfqs.requester_id =" in quote_sql
    assert "inventory_transactions.warehouse_id in" in movement_sql


def test_known_finance_rows_keep_paid_status_and_currencies_separate() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE suppliers (id INTEGER PRIMARY KEY, supplier_name TEXT)")
        connection.exec_driver_sql("CREATE TABLE finance_payments (id INTEGER PRIMARY KEY, supplier_id INTEGER, amount NUMERIC, currency_code TEXT, status TEXT, paid_at TEXT)")
        connection.exec_driver_sql("INSERT INTO suppliers VALUES (1, '华东原料')")
        connection.exec_driver_sql("INSERT INTO finance_payments VALUES (1, 1, 100, 'CNY', 'PAID', '2026-09-10'), (2, 1, 30, 'USD', 'PAID', '2026-09-11'), (3, 1, 40, 'CNY', 'REQUESTED', NULL)")
        plan = QueryPlan(dataset="finance_payments", metric="amount", time_field="paid_at", filters=[QueryFilter(field="status", value="PAID")])
        rows = connection.execute(build_statement(plan)).mappings().all()

    assert {(row["currency"], int(row["metric_value"])) for row in rows} == {("CNY", 100), ("USD", 30)}


def test_model_plan_normalizes_common_payment_shapes() -> None:
    payload = {
        "dataset": "finance_payments",
        "metric": "amount",
        "group_by": ["supplier", "currency"],
        "filters": [{"field": "status", "operator": "=", "value": "PAID"}],
        "limit": None,
        "order": None,
    }
    plan = QueryPlan.model_validate(_normalize_query_plan_payload(payload))

    assert plan.group_by == "supplier"
    assert plan.filters[0].operator == "eq"
    assert plan.limit == 20
    assert plan.order == "desc"


def test_model_plan_does_not_silently_drop_unsupported_groups() -> None:
    payload = {"dataset": "finance_payments", "metric": "count", "group_by": ["supplier", "status"]}
    with pytest.raises(ValueError):
        QueryPlan.model_validate(_normalize_query_plan_payload(payload))


@pytest.mark.parametrize("question", ["统计供应商报价金额合计", "统计库存流水数量合计", "查看库存变动净变化"])
def test_unsupported_amount_or_quantity_question_is_rejected(question: str) -> None:
    with pytest.raises(BusinessValidationError, match="不支持"):
        _reject_unsupported_metric(question)


def test_supported_counts_and_batch_trace_are_not_blocked() -> None:
    for question in ("按供应商统计报价单笔数", "按类型统计库存流水笔数", "这个批次的库存变动来源是什么"):
        _reject_unsupported_metric(question)


def test_aggregate_questions_do_not_enter_object_trace_routes() -> None:
    db = SimpleNamespace()
    user = SimpleNamespace(id=1)
    assert _supplier_profile_plan(db, user, "按供应商统计报价单笔数") is None
    assert _inventory_movement_trace_plan(db, user, "按类型统计库存流水笔数") is None
