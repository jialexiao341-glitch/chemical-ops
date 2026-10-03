"""阶段 0～3 的 30 个来源与数值固定样本检查。"""
from types import SimpleNamespace

import pytest

from app.modules.ai import agent_tools as tools
from scripts.agent_evaluation_data import evaluation_db


CASES = (
    # 库存：权限范围、状态口径、单位、合计、截断、来源与精确仓库。
    ("I01", "inventory.query_available", 7, {}, "visible_ids", [1, 2, 4]),
    ("I02", "inventory.query_available", 7, {}, "unit_total", (1, 80)),
    ("I03", "inventory.query_available", 7, {}, "unit_total", (2, 5)),
    ("I04", "inventory.query_available", 7, {}, "row_quantity", (1, 80)),
    ("I05", "inventory.query_available", 7, {}, "row_quantity", (2, 0)),
    ("I06", "inventory.query_available", 7, {}, "source_ids", [1, 2, 4]),
    ("I07", "inventory.query_available", 7, {}, "expired_warning", True),
    ("I08", "inventory.query_available", 7, {"limit": 1}, "truncated", (1, 3)),
    ("I09", "inventory.query_available", 7, {"limit": 1}, "unit_total", (1, 80)),
    ("I10", "inventory.query_available", 7, {"limit": 1}, "unit_total", (2, 5)),
    ("I11", "inventory.query_available", 9, {}, "visible_ids", [1, 2, 3, 4]),
    ("I12", "inventory.query_available", 9, {}, "unit_total", (1, 1079)),
    ("I13", "inventory.query_available", 9, {}, "inactive_excluded", 5),
    ("I14", "inventory.query_available", 7, {"warehouse_id": 1}, "visible_ids", [1, 2]),
    ("I15", "inventory.query_available", 8, {}, "unit_total", (1, 999)),
    # 报价：版本、状态、有效期、可比口径、来源及截断。
    ("Q16", "supplier_quotes.compare", 7, {}, "quote_ids", [2, 3, 5, 6, 7, 8, 9]),
    ("Q17", "supplier_quotes.compare", 7, {}, "rank", (2, 2)),
    ("Q18", "supplier_quotes.compare", 7, {}, "rank", (3, 1)),
    ("Q19", "supplier_quotes.compare", 7, {}, "rank", (5, None)),
    ("Q20", "supplier_quotes.compare", 7, {}, "rank", (6, None)),
    ("Q21", "supplier_quotes.compare", 7, {}, "rank", (7, None)),
    ("Q22", "supplier_quotes.compare", 7, {}, "rank", (8, None)),
    ("Q23", "supplier_quotes.compare", 7, {}, "rank", (9, None)),
    ("Q24", "supplier_quotes.compare", 7, {}, "excluded_quote", 4),
    ("Q25", "supplier_quotes.compare", 7, {}, "excluded_quote", 12),
    ("Q26", "supplier_quotes.compare", 7, {}, "excluded_quote", 13),
    ("Q27", "supplier_quotes.compare", 7, {}, "excluded_quote", 14),
    ("Q28", "supplier_quotes.compare", 7, {}, "source_ids", [2, 3, 5, 6, 7, 8, 9]),
    ("Q29", "supplier_quotes.compare", 7, {}, "source_parent", 1),
    ("Q30", "supplier_quotes.compare", 7, {"limit": 1}, "all_unranked", True),
)


@pytest.fixture
def evidence_db():
    """使用与固定评估相同的隔离样本和真实 RBAC 表。"""
    with evaluation_db() as db:
        yield db


@pytest.mark.parametrize("case_id,tool_name,actor_id,extra,check,expected", CASES, ids=[c[0] for c in CASES])
def test_fixed_source_and_number_scenarios(evidence_db, case_id, tool_name, actor_id, extra, check, expected):
    """每个场景均对隔离 SQLite 中的实际工具结果做独立预期值核对。"""
    arguments = {"product_id": 1, **extra}
    if tool_name == "supplier_quotes.compare":
        arguments["rfq_item_id"] = 11
    result = tools.execute_tool(
        evidence_db,
        SimpleNamespace(id=actor_id),
        tools.ToolCall(tool=tool_name, arguments=arguments),
    )

    if check == "visible_ids":
        actual = [row.balance_id for row in result.rows]
        assert actual == expected, case_id
    elif check == "unit_total":
        unit_id, quantity = expected
        actual = {row.unit_id: row.available_quantity for row in result.totals}
        assert actual[unit_id] == quantity, case_id
    elif check == "row_quantity":
        balance_id, quantity = expected
        row = next(row for row in result.rows if row.balance_id == balance_id)
        assert row.available_quantity == quantity, case_id
    elif check == "source_ids":
        assert [source.record_id for source in result.sources] == expected, case_id
    elif check == "expired_warning":
        assert any("过期批次" in warning for warning in result.warnings) is expected, case_id
    elif check == "truncated":
        row_count, total_rows = expected
        assert result.truncated and len(result.rows) == row_count and result.total_rows == total_rows, case_id
    elif check == "inactive_excluded":
        assert expected not in {row.balance_id for row in result.rows}, case_id
    elif check == "quote_ids":
        assert [row.quote_item_id for row in result.rows] == expected, case_id
    elif check == "rank":
        quote_id, rank = expected
        row = next(row for row in result.rows if row.quote_item_id == quote_id)
        assert row.rank == rank, case_id
    elif check == "excluded_quote":
        assert expected not in {row.quote_item_id for row in result.rows}, case_id
    elif check == "source_parent":
        assert {source.parent_id for source in result.sources} == {expected}, case_id
    elif check == "all_unranked":
        assert result.truncated and all(row.rank is None for row in result.rows) is expected, case_id
    else:  # pragma: no cover - guards accidental incomplete matrix edits.
        pytest.fail(f"{case_id}: unknown check {check}")
