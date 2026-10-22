from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.rfqs import service


def _quote(quote_id, supplier_id, *, currency="CNY", items=None):
    return SimpleNamespace(
        id=quote_id,
        supplier_id=supplier_id,
        status="SUBMITTED",
        currency_code=currency,
        items=items or [],
    )


def _item(rfq_item_id=31, *, unit_id=1, price="10", tax_rate="13", tax_included=True):
    return SimpleNamespace(
        rfq_item_id=rfq_item_id,
        unit_id=unit_id,
        unit_price=Decimal(price),
        quoted_quantity=Decimal("10"),
        tax_rate=Decimal(tax_rate) if tax_rate is not None else None,
        tax_included=tax_included,
        moq_quantity=None,
        lead_days=5,
        payment_terms="月结30天",
        note=None,
    )


class _Db:
    def add(self, value):
        self.value = value

    def flush(self):
        self.value.id = 60

    def commit(self):
        pass


def _build(monkeypatch, quotes):
    rfq = SimpleNamespace(
        id=14,
        items=[SimpleNamespace(id=31, unit_id=1)],
        quotes=quotes,
    )
    monkeypatch.setattr(service, "get_rfq", lambda *_args, **_kwargs: rfq)
    result = {"comparison": None}
    monkeypatch.setattr(service.crud, "get_comparison", lambda *_args, **_kwargs: result["comparison"])
    monkeypatch.setattr(service, "add_audit_log", lambda *_args, **_kwargs: None)
    db = _Db()

    def flush():
        db.value.id = 60
        result["comparison"] = db.value

    db.flush = flush
    return service.build_comparison(db, SimpleNamespace(id=7), 14)


def test_comparison_ranks_only_quotes_with_the_same_currency_and_tax_basis(monkeypatch):
    quotes = [
        _quote(51, 8, items=[_item(price="10")]),
        _quote(52, 9, items=[_item(price="8")]),
        _quote(53, 10, currency="USD", items=[_item(price="7")]),
    ]

    comparison = _build(monkeypatch, quotes)

    rows = {row.quote_id: row for row in comparison.items}
    assert rows[51].rank_no == 2
    assert rows[52].rank_no == 1
    assert rows[52].selection_flag == 0
    assert rows[53].rank_no is None
    assert rows[53].comparison_status == "NOT_COMPARABLE"
    assert "币种" in rows[53].comparison_reasons[0]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"unit_id": 2}, "计量单位"),
        ({"tax_rate": "9"}, "税率"),
        ({"tax_included": False}, "含税口径"),
        ({"tax_rate": None}, "税率缺失"),
        ({"tax_included": None}, "含税口径缺失"),
    ],
)
def test_comparison_keeps_incompatible_quote_out_of_rank(monkeypatch, changes, reason):
    quotes = [
        _quote(51, 8, items=[_item(price="10")]),
        _quote(52, 9, items=[_item(price="8", **changes)]),
    ]

    comparison = _build(monkeypatch, quotes)

    row = next(row for row in comparison.items if row.quote_id == 52)
    assert row.rank_no is None
    assert row.selection_flag == 0
    assert row.comparison_status == "NOT_COMPARABLE"
    assert any(reason in detail for detail in row.comparison_reasons)


def test_comparison_excludes_incomplete_quote_from_every_item_ranking(monkeypatch):
    quotes = [
        _quote(51, 8, items=[_item()]),
        _quote(52, 9, items=[_item(), _item(rfq_item_id=32)]),
    ]
    rfq = SimpleNamespace(id=14, items=[SimpleNamespace(id=31, unit_id=1), SimpleNamespace(id=32, unit_id=1)], quotes=quotes)
    monkeypatch.setattr(service, "get_rfq", lambda *_args, **_kwargs: rfq)
    result = {"comparison": None}
    monkeypatch.setattr(service.crud, "get_comparison", lambda *_args, **_kwargs: result["comparison"])
    monkeypatch.setattr(service, "add_audit_log", lambda *_args, **_kwargs: None)
    db = _Db()

    def flush():
        db.value.id = 60
        result["comparison"] = db.value

    db.flush = flush
    comparison = service.build_comparison(db, SimpleNamespace(id=7), 14)

    quote_rows = [row for row in comparison.items if row.quote_id == 51]
    assert {row.rfq_item_id for row in quote_rows} == {31, 32}
    assert all(row.rank_no is None for row in quote_rows)
    assert all(row.comparison_status == "NOT_COMPARABLE" for row in quote_rows)
    assert all("未覆盖全部询价明细" in row.comparison_reasons[0] for row in quote_rows)


def test_comparison_does_not_choose_a_basis_when_signature_groups_are_tied(monkeypatch):
    quotes = [
        _quote(51, 8, currency="CNY", items=[_item()]),
        _quote(52, 9, currency="USD", items=[_item()]),
    ]

    comparison = _build(monkeypatch, quotes)

    assert all(row.rank_no is None for row in comparison.items)
    assert all("币种存在差异" in row.comparison_reasons for row in comparison.items)
    assert all("无法确定统一比较组" in row.comparison_reasons[-1] for row in comparison.items)
