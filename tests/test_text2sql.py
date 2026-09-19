import asyncio
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.ai import text2sql
from app.modules.ai.catalog import CATALOG
from app.modules.ai.text2sql import QueryFilter, QueryPlan, Text2SQLRequest, build_statement, run_text2sql, validate_sql


def test_text2sql_sql_validation_is_select_only_and_table_scoped():
    sql = validate_sql("SELECT count(*) FROM purchase_orders", CATALOG["purchase_orders"].tables)
    assert sql.startswith("SELECT")

    with pytest.raises(BusinessValidationError):
        validate_sql("DELETE FROM purchase_orders", CATALOG["purchase_orders"].tables)

    with pytest.raises(BusinessValidationError):
        validate_sql("SELECT * FROM sys_users", CATALOG["purchase_orders"].tables)


def test_text2sql_builds_parameterized_grouped_statement_from_whitelist():
    statement = build_statement(
        QueryPlan(
            dataset="purchase_orders",
            metric="amount",
            group_by="supplier",
            filters=[QueryFilter(field="status", operator="eq", value="APPROVED")],
            limit=10,
        )
    )
    compiled = str(statement.compile())
    assert "purchase_orders" in compiled
    assert "suppliers" in compiled
    assert "GROUP BY" in compiled
    assert "status" in compiled


def test_text2sql_plan_rejects_unknown_fields():
    with pytest.raises(BusinessValidationError):
        build_statement(QueryPlan(dataset="purchase_orders", metric="count", filters=[QueryFilter(field="password_hash", value="x")]))


def test_text2sql_normalizes_markdown_json_and_common_aliases(monkeypatch):
    async def fake_chat(*_args, **_kwargs):
        content = "规划结果：\n" + "`" * 3 + "json\n" + '{"dataset":"purchase_order","metric":"sum_amount","group_by":"supplier_name","filters":null,"order":"降序","top_n":"10"}' + "\n" + "`" * 3
        return SimpleNamespace(message=SimpleNamespace(content=content))

    monkeypatch.setattr(text2sql, "chat", fake_chat)
    plan = asyncio.run(text2sql._understand_question("查询供应商采购金额排名", SimpleNamespace()))

    assert plan.dataset == "purchase_orders"
    assert plan.metric == "amount"
    assert plan.group_by == "supplier"
    assert plan.filters == []
    assert plan.order == "desc"
    assert plan.limit == 10


def test_text2sql_uses_safe_supplier_amount_fallback_when_model_plan_is_invalid(monkeypatch):
    async def fake_chat(*_args, **_kwargs):
        return SimpleNamespace(message=SimpleNamespace(content="无法生成计划"))

    monkeypatch.setattr(text2sql, "chat", fake_chat)
    plan = asyncio.run(text2sql._understand_question("查询本月各供应商的采购订单总金额，按金额从高到低，最多显示10家", SimpleNamespace()))

    assert plan.dataset == "purchase_orders"
    assert plan.metric == "amount"
    assert plan.group_by == "supplier"
    assert plan.time_field == "order_date"
    assert plan.limit == 10


class _FakeResult:
    def mappings(self):
        return self

    def all(self):
        return [{"metric_value": 3}]


class _FakeDB:
    def execute(self, _statement):
        return _FakeResult()


def test_text2sql_runs_the_langgraph_stages(monkeypatch):
    async def fake_understand(_question, _settings):
        return QueryPlan(dataset="purchase_orders", metric="count", limit=5)

    monkeypatch.setattr(text2sql, "_understand_question", fake_understand)
    monkeypatch.setattr(text2sql, "_validate_plan", lambda _db, _user, _plan: None)

    result = asyncio.run(
        run_text2sql(
            _FakeDB(),
            SimpleNamespace(id=7),
            Text2SQLRequest(question="查询采购订单数量", limit=5),
        )
    )

    assert result.read_only is True
    assert result.slots[0]["name"] == "dataset"
    assert result.template.startswith("采购订单")
    assert result.render_columns == [{"key": "metric_value", "label": "数量", "format": "text"}]
    assert result.render["type"] == "table"
    assert result.stages == [
        "query_understanding",
        "slot_filling",
        "query_planning",
        "sql_validation",
        "execution",
    ]
    assert result.rows == [{"metric_value": 3}]
