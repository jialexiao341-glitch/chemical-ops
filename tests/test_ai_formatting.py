"""AI 回答中的小数展示：去掉数据库标度，不改变业务值。"""

from decimal import Decimal
from types import SimpleNamespace

from app.modules.ai.formatting import format_amount, format_decimal


def test_format_decimal_trims_trailing_scale():
    assert format_decimal(Decimal("54.240000")) == "54.24"
    assert format_decimal(Decimal("54.200000")) == "54.2"
    assert format_decimal(Decimal("100.000000")) == "100"
    assert format_decimal(Decimal("0.000000")) == "0"
    assert format_decimal("54.240000") == "54.24"
    assert format_decimal(54.24) == "54.24"
    assert format_decimal(0) == "0"
    assert format_decimal(None) == ""
    assert format_decimal("未填写") == "未填写"


def test_format_amount_keeps_two_decimals_without_database_scale():
    assert format_amount(Decimal("54.240000")) == "54.24"
    assert format_amount(Decimal("1200.000000")) == "1200.00"
    assert format_amount(Decimal("0.000000")) == "0.00"
    assert format_amount("54.240000") == "54.24"
    assert format_amount(None) == ""


def test_finance_context_answer_uses_readable_amounts():
    from app.modules.ai.context import _finance_reconciliation_answer

    trace = {
        "reconciliation": SimpleNamespace(
            reconciliation_no="FR20261004001014", status="CONFIRMED",
            total_amount=Decimal("54.240000"), currency_code="CNY"),
        "supplier": None,
        "read_model": {
            "invoices": [{"status": "VERIFIED", "count": 1, "amount": Decimal("0.000000")}],
            "payments": [{"status": "PAID", "count": 0, "amount": Decimal("0.000000")}],
            "lines": [],
            "line_warnings": [],
            "source_changed": False,
            "unallocated_invoices": [],
            "payment_precheck": {
                "verified_invoice_amount": Decimal("0.000000"),
                "active_payment_amount": Decimal("0.000000"),
                "max_new_payment_amount": Decimal("0.000000"),
                "blockers": [],
                "limitation": "仅计算当前理论上限。",
            },
        },
    }

    answer = _finance_reconciliation_answer(trace)
    assert "54.24 CNY" in answer
    assert "0.00 CNY" in answer
    assert "54.240000" not in answer
    assert "0.000000" not in answer
