from decimal import Decimal

import pytest

from app.modules.rfqs.total_cost import calculate_total_cost
from app.modules.rfqs import service
from app.modules.rfqs.schema import SupplierQuoteItemCreate


def test_total_cost_uses_requested_quantity_moq_and_separate_tax_bases():
    result = calculate_total_cost(
        requested_quantity=Decimal("10"),
        requested_unit_id=1,
        quoted_unit_id=1,
        unit_price=Decimal("100"),
        tax_rate=Decimal("13"),
        tax_included=False,
        moq_quantity=Decimal("12"),
        moq_unit_id=1,
        freight_amount=Decimal("20"),
        freight_tax_rate=Decimal("6"),
        freight_tax_included=False,
    )

    assert result.purchase_quantity == Decimal("12")
    assert result.moq_extra_quantity == Decimal("2")
    assert result.goods_amount == Decimal("1200")
    assert result.goods_tax == Decimal("156")
    assert result.freight_amount == Decimal("20")
    assert result.freight_tax == Decimal("1.2")
    assert result.total_cost == Decimal("1377.2")
    assert result.complete is True


def test_total_cost_keeps_freight_unknown_and_does_not_claim_a_complete_total():
    result = calculate_total_cost(
        requested_quantity=Decimal("10"),
        requested_unit_id=1,
        quoted_unit_id=1,
        unit_price=Decimal("100"),
        tax_rate=Decimal("13"),
        tax_included=True,
        moq_quantity=None,
        moq_unit_id=None,
        freight_amount=None,
        freight_tax_rate=None,
        freight_tax_included=None,
    )

    assert result.goods_amount == Decimal("1000")
    assert result.goods_tax == Decimal("115.044248")
    assert result.freight_amount is None
    assert result.total_cost is None
    assert result.complete is False
    assert "运费未登记" in result.reasons


def test_total_cost_does_not_apply_moq_across_different_units():
    result = calculate_total_cost(
        requested_quantity=Decimal("10"),
        requested_unit_id=1,
        quoted_unit_id=1,
        unit_price=Decimal("100"),
        tax_rate=Decimal("13"),
        tax_included=False,
        moq_quantity=Decimal("5"),
        moq_unit_id=2,
        freight_amount=Decimal("0"),
        freight_tax_rate=Decimal("0"),
        freight_tax_included=True,
    )

    assert result.purchase_quantity is None
    assert result.total_cost is None
    assert "MOQ单位与询价单位不同" in result.reasons


def test_total_cost_does_not_multiply_price_across_different_quote_units():
    result = calculate_total_cost(
        requested_quantity=Decimal("10"),
        requested_unit_id=1,
        quoted_unit_id=2,
        unit_price=Decimal("100"),
        tax_rate=Decimal("13"),
        tax_included=False,
        moq_quantity=None,
        moq_unit_id=None,
        freight_amount=Decimal("0"),
        freight_tax_rate=None,
        freight_tax_included=None,
    )

    assert result.goods_amount is None
    assert result.total_cost is None
    assert "报价单位与询价单位不同" in result.reasons


def test_quality_history_respects_quality_permission_and_reports_observed_counts(monkeypatch):
    user = type("User", (), {"id": 7})()
    scoped = []
    monkeypatch.setattr(service, "get_user_permission_codes", lambda *_args: ["quality.acceptances.read"])
    monkeypatch.setattr(service, "get_user_role_codes", lambda *_args: ["QUALITY_MANAGER"])
    monkeypatch.setattr(service, "acceptance_read_condition", lambda actor, roles: scoped.append((actor, roles)) or True)
    class Rows:
        @staticmethod
        def all():
            return [(8, "PASSED", 2), (8, "FAILED", 1)]

    db = type("Db", (), {"execute": lambda *_args: Rows()})()

    result = service.quality_history_by_supplier(db, user, {8})

    assert result[8]["status"] == "OBSERVED"
    assert result[8]["sample_count"] == 3
    assert result[8]["passed"] == 2
    assert result[8]["failed"] == 1
    assert "不等同供应商风险评分" in result[8]["description"]
    assert scoped == [(user, ["QUALITY_MANAGER"])]


def test_quality_history_stays_unknown_without_quality_permission(monkeypatch):
    monkeypatch.setattr(service, "get_user_permission_codes", lambda *_args: ["procurement.rfqs.compare"])
    result = service.quality_history_by_supplier(type("Db", (), {})(), type("User", (), {"id": 7})(), {8})

    assert result[8] == {"status": "UNKNOWN", "reason": "当前账号无质量验收读取权限"}


def test_quote_input_validates_freight_fields_as_optional_nonnegative_values():
    quote_item = SupplierQuoteItemCreate(
        rfq_item_id=31,
        quoted_quantity=Decimal("10"),
        unit_id=1,
        unit_price=Decimal("100"),
        freight_amount=Decimal("0"),
        freight_tax_rate=Decimal("6"),
        freight_tax_included=False,
    )

    assert quote_item.freight_amount == Decimal("0")
    assert quote_item.freight_tax_rate == Decimal("6")
    assert quote_item.freight_tax_included is False
    with pytest.raises(ValueError):
        SupplierQuoteItemCreate(
            rfq_item_id=31, quoted_quantity=1, unit_id=1, unit_price=100,
            freight_amount=-1,
        )
