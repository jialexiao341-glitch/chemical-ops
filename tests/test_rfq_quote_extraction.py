import json
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.rfqs import quote_extraction, service as rfq_service


def _rfq(status="RESPONDING"):
    return SimpleNamespace(
        id=14,
        status=status,
        items=[SimpleNamespace(id=31, requested_name="乙醇", specification="纯度99%", quantity="10")],
    )


def _model_result(*, item_id=31, quote="物料：乙醇，数量：10 L，单价：12.5 CNY/L", tax_included=None,
                  freight_amount=None, freight_tax_rate=None, freight_tax_included=None,
                  moq_quantity=None, moq_unit_name=None):
    return {
        "supplier_name": "甲公司",
        "currency_code": "CNY",
        "quote_date": "2026-10-20",
        "valid_until": "2026-11-20",
        "note": None,
        "evidence": {
            "supplier_name": "供应商：甲公司",
            "currency_code": "币种：CNY",
            "quote_date": "报价日期：2026-10-20",
            "valid_until": "有效期至：2026-11-20",
        },
        "items": [{
            "rfq_item_id": item_id,
            "product_label": "乙醇",
            "supplier_model": "E-99",
            "quoted_quantity": "10",
            "unit_name": "L",
            "unit_price": "12.5",
            "tax_rate": "13",
            "tax_included": tax_included,
            "moq_quantity": moq_quantity,
            "moq_unit_name": moq_unit_name,
            "freight_amount": freight_amount,
            "freight_tax_rate": freight_tax_rate,
            "freight_tax_included": freight_tax_included,
            "lead_days": 7,
            "payment_terms": "月结30天",
            "quote": quote,
        }],
    }


def _configure(monkeypatch, model_result):
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: _rfq())
    monkeypatch.setattr(quote_extraction.file_service, "scan_content", lambda _content: SimpleNamespace(status="CLEAN"))
    monkeypatch.setattr(
        quote_extraction.file_service,
        "upload_file",
        lambda *_args, **_kwargs: SimpleNamespace(id=72, file_name="报价.csv"),
    )

    async def fake_chat(*_args, **_kwargs):
        payload = json.dumps(model_result, ensure_ascii=False)
        return SimpleNamespace(answer=payload, message=SimpleNamespace(content=payload))

    async def fake_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(quote_extraction, "chat", fake_chat)
    monkeypatch.setattr(quote_extraction.asyncio, "to_thread", fake_to_thread)


def _run_immediate(coroutine):
    """Drive the fully stubbed async service without creating a Windows event loop."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("test coroutine unexpectedly suspended")


def test_quote_file_extracts_candidates_with_verifiable_source_and_stores_only_file(monkeypatch):
    quote = "乙醇：10 L，单价 12.5 CNY/L；运费 25.50 元，税率 6%，未税。"
    _configure(monkeypatch, _model_result(
        quote=quote, freight_amount="25.50", freight_tax_rate="6", freight_tax_included=False,
    ))

    result = _run_immediate(quote_extraction.parse_quote_file(
        SimpleNamespace(),
        SimpleNamespace(id=5),
        14,
        file_name="报价.csv",
        mime_type="text/csv",
        content=f"供应商：甲公司\n币种：CNY\n报价日期：2026-10-20\n有效期至：2026-11-20\n{quote}".encode(),
    ))

    assert result.file_id == 72
    assert result.supplier_name == "甲公司"
    assert result.currency_code == "CNY"
    assert result.items[0].rfq_item_id == 31
    assert result.items[0].unit_price == "12.5"
    assert result.items[0].freight_amount == "25.50"
    assert result.items[0].freight_tax_rate == "6"
    assert result.items[0].freight_tax_included is False
    assert result.items[0].source_location == "正文"
    assert result.evidence[0].source_quote == "供应商：甲公司"


def test_quote_file_preserves_explicit_tax_basis_for_manual_review(monkeypatch):
    _configure(monkeypatch, _model_result(
        quote="乙醇未税单价 12.5 CNY/L，税率 13%",
        tax_included=False,
    ))

    result = _run_immediate(quote_extraction.parse_quote_file(
        SimpleNamespace(),
        SimpleNamespace(id=5),
        14,
        file_name="报价.csv",
        mime_type="text/csv",
        content="乙醇未税单价 12.5 CNY/L，税率 13%".encode(),
    ))

    assert result.items[0].tax_included is False


def test_quote_file_preserves_moq_unit_for_manual_review(monkeypatch):
    quote = "乙醇报价 12.5 CNY/L，MOQ 20 L。"
    _configure(monkeypatch, _model_result(quote=quote, moq_quantity="20", moq_unit_name="L"))

    result = _run_immediate(quote_extraction.parse_quote_file(
        SimpleNamespace(), SimpleNamespace(id=5), 14,
        file_name="报价.csv", mime_type="text/csv", content=quote.encode(),
    ))

    assert result.items[0].moq_quantity == "20"
    assert result.items[0].moq_unit_name == "L"


def test_quote_file_discards_items_without_exact_source_quote(monkeypatch):
    _configure(monkeypatch, _model_result(quote="这段内容不在报价文件中"))

    with pytest.raises(BusinessValidationError, match="带可核对原文引用"):
        _run_immediate(quote_extraction.parse_quote_file(
            SimpleNamespace(), SimpleNamespace(id=5), 14,
            file_name="报价.csv", mime_type="text/csv",
            content="物料：乙醇，数量：10 L，单价：12.5 CNY/L".encode(),
        ))


def test_quote_file_keeps_unmatched_item_for_manual_review(monkeypatch):
    _configure(monkeypatch, _model_result(item_id=999))

    result = _run_immediate(quote_extraction.parse_quote_file(
        SimpleNamespace(), SimpleNamespace(id=5), 14,
        file_name="报价.csv", mime_type="text/csv",
        content="物料：乙醇，数量：10 L，单价：12.5 CNY/L".encode(),
    ))

    assert result.items[0].rfq_item_id is None
    assert any("未能可靠匹配" in warning for warning in result.warnings)


def test_source_location_preserves_pdf_page_and_excel_sheet_row():
    assert quote_extraction._source_location("[第 2 页]\n报价总额 125 元", "报价总额 125 元") == "第 2 页"
    assert quote_extraction._source_location(
        "[工作表：报价明细]\n第 5 行：乙醇\t12.5 元/L", "乙醇\t12.5 元/L"
    ) == "工作表：报价明细 · 第 5 行"


def test_quote_file_rejects_rfq_that_no_longer_accepts_quotes(monkeypatch):
    monkeypatch.setattr(rfq_service, "get_rfq", lambda *_args, **_kwargs: _rfq(status="CLOSED"))

    with pytest.raises(BusinessValidationError, match="不接受报价文件"):
        _run_immediate(quote_extraction.parse_quote_file(
            SimpleNamespace(), SimpleNamespace(id=5), 14,
            file_name="报价.csv", mime_type="text/csv", content=b"quote",
        ))


def test_quote_create_rejects_source_file_owned_by_another_user():
    class FakeDb:
        @staticmethod
        def get(_model, _file_id):
            return SimpleNamespace(uploader_id=99, file_category="SUPPLIER_QUOTE")

    data = SimpleNamespace(source_file_id=72)
    with pytest.raises(BusinessValidationError, match="不属于当前报价人"):
        rfq_service.create_quote_for_supplier(
            FakeDb(), SimpleNamespace(id=5), _rfq(), 8, data,
        )
