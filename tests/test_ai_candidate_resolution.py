"""Agent 与批次共用的产品候选边界。"""

from datetime import date

import pytest
from sqlalchemy import text

from app.core.errors import BusinessValidationError
from app.modules.ai.candidate_resolution import inventory_family, validate_selection
from app.modules.ai.product_query_policy import (
    can_aggregate_inventory,
    unsupported_product_slot_prompt,
    unsupported_product_slots,
)
from app.modules.ai.schema import PendingChoice, Slots
from tests.test_agent_read_tools import tool_db


@pytest.mark.parametrize("kind", ["inventory", "quotes"])
def test_product_queries_reject_unexecutable_date_and_unit_slots(kind):
    slots = Slots(date_from=date(2026, 10, 1), date_to=date(2026, 10, 22), unit="升")

    assert unsupported_product_slots(kind, slots) == ("date_from", "date_to", "unit")


def test_non_product_query_has_no_product_tool_slot_restrictions():
    assert unsupported_product_slots("analytics", Slots(date_from=date(2026, 10, 1))) == ()


def test_unsupported_product_slot_prompt_is_shared_and_explains_unit_boundary():
    assert unsupported_product_slot_prompt(("date_from", "unit")) == (
        "当前库存与报价工具不支持按指定起始日期、计量单位筛选。请确认是否按现有记录口径执行；"
        "库存按原始单位分别展示，不做单位换算。"
    )


@pytest.mark.parametrize(
    "total_rows,truncated,explicit_aggregate,same_product_family,expected",
    [
        (0, False, True, True, False),
        (2, True, True, True, False),
        (2, False, True, False, True),
        (2, False, False, True, True),
        (2, False, False, False, False),
        (1, False, False, False, False),
    ],
)
def test_inventory_aggregation_requires_complete_explicit_or_same_family_candidates(
    total_rows, truncated, explicit_aggregate, same_product_family, expected
):
    assert can_aggregate_inventory(
        total_rows=total_rows,
        truncated=truncated,
        explicit_aggregate=explicit_aggregate,
        same_product_family=same_product_family,
    ) is expected


def test_inventory_family_accepts_exact_product_name_without_chemical_table(tool_db):
    assert inventory_family(
        tool_db,
        [{"product_id": 1, "product_name": "测试乙醇"}, {"product_id": 3, "product_name": "测试乙醇"}],
        "测试乙醇",
    )


def test_inventory_family_uses_only_same_active_chemical_identity(tool_db):
    tool_db.execute(text("INSERT INTO md_products (id, product_name, status, product_code, unit_id, chemical_id) VALUES (3, '乙醇衍生产品', 'ACTIVE', 'P-DERIVATIVE', 1, 1)"))
    rows = [{"product_id": 1, "product_name": "测试乙醇"}, {"product_id": 3, "product_name": "乙醇衍生产品"}]

    assert inventory_family(tool_db, rows, "测试乙醇")
    tool_db.execute(text("UPDATE md_chemicals SET status = 'INACTIVE' WHERE id = 1"))
    assert not inventory_family(tool_db, rows, "测试乙醇")


def test_candidate_selection_rejects_stale_revision():
    pending = PendingChoice(
        entity="product",
        lookup_arguments={"keyword": "测试乙醇"},
        candidates=[{"product_id": 1}],
        revision=3,
    )

    with pytest.raises(BusinessValidationError, match="当前版本"):
        validate_selection(pending, entity="product", selected_id=1, revision=2)
