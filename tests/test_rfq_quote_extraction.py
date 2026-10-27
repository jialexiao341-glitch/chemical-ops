import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.rfqs import quote_extraction, service as rfq_service


def _rfq(status="RESPONDING"):
    return SimpleNamespace(
        id=14,
        status=status,
        items=[SimpleNamespace(id=31, requested_name="乙醇", specification=None, quantity="10")],
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
            "evidence": {
                "product_label": "乙醇", "supplier_model": "E-99",
                "quoted_quantity": "10 L", "unit_name": "CNY/L", "unit_price": "12.5 CNY/L",
                "tax_rate": "税率 13%", "tax_included": "未税",
                "moq_quantity": "MOQ 20 L", "moq_unit_name": "MOQ 20 L",
                "freight_amount": "运费 25.50 元", "freight_tax_rate": "税率 6%",
                "freight_tax_included": "未税", "lead_days": "交期7天", "payment_terms": "月结30天",
            },
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


def test_fields_without_individual_evidence_are_not_prefilled(monkeypatch):
    prediction = _model_result()
    prediction['items'][0].pop('evidence')
    _configure(monkeypatch, prediction)
    result = _run_immediate(quote_extraction.parse_quote_file(SimpleNamespace(), SimpleNamespace(id=5), 14,
        file_name='quote.csv', mime_type='text/csv', content=prediction['items'][0]['quote'].encode()))
    assert result.items[0].unit_price is None
    assert result.items[0].tax_rate is None
    assert result.items[0].rfq_item_id is None


def test_header_value_must_match_its_actual_evidence(monkeypatch):
    prediction = _model_result()
    prediction['currency_code'] = 'USD'
    _configure(monkeypatch, prediction)
    result = _run_immediate(quote_extraction.parse_quote_file(SimpleNamespace(), SimpleNamespace(id=5), 14,
        file_name='quote.csv', mime_type='text/csv', content=('币种：CNY\n'+prediction['items'][0]['quote']).encode()))
    assert result.currency_code is None


@pytest.mark.parametrize(('field', 'value', 'proof', 'expected'), [
    ('unit_price', '12.5', '单价12.5元', True),
    ('unit_price', '12.5', '数量10 单价12.5', False),
    ('unit_price', '99', '型号E99', False),
    ('unit_price', '-1', '单价-1', False),
    ('unit_price', 'NaN', 'NaN', False),
    ('quoted_quantity', '0', '数量0', False),
    ('tax_rate', '101', '税率101%', False),
    ('tax_included', True, '不含税', False),
    ('tax_included', False, 'not included', True),
    ('tax_included', True, '含税与未税', False),
    ('currency_code', 'USD', 'Currency CNY', False),
])
def test_field_evidence_boundaries(field, value, proof, expected):
    assert quote_extraction.supported(field, value, proof) is expected


def _parse_prediction(monkeypatch, prediction, *, source=None):
    _configure(monkeypatch, prediction)
    return _run_immediate(quote_extraction.parse_quote_file(
        SimpleNamespace(), SimpleNamespace(id=5), 14, file_name='quote.csv',
        mime_type='text/csv', content=(source or '\n'.join(item['quote'] for item in prediction['items'])).encode()))


def test_other_row_evidence_cannot_fill_current_row(monkeypatch):
    prediction = _model_result()
    prediction['items'][0]['tax_rate'] = '13'
    result = _parse_prediction(monkeypatch, prediction, source=prediction['items'][0]['quote']+'\n甲醇 税率 13%')
    assert result.items[0].tax_rate is None


def test_matching_requires_verified_specification(monkeypatch):
    prediction = _model_result()
    _configure(monkeypatch, prediction)
    rfq = _rfq()
    rfq.items[0].specification = '纯度99%'
    monkeypatch.setattr(rfq_service, 'get_rfq', lambda *_args: rfq)
    result = _run_immediate(quote_extraction.parse_quote_file(
        SimpleNamespace(), SimpleNamespace(id=5), 14, file_name='quote.csv',
        mime_type='text/csv', content=prediction['items'][0]['quote'].encode()))
    assert result.items[0].rfq_item_id is None


@pytest.mark.parametrize('ambiguous', [False, True])
def test_verified_name_and_specification_bind_only_one_inquiry_row(monkeypatch, ambiguous):
    prediction = _model_result(quote='乙醇 纯度99% 单价12.5 CNY/L')
    prediction['items'][0]['specification'] = '纯度99%'
    prediction['items'][0]['evidence']['specification'] = '纯度99%'
    _configure(monkeypatch, prediction)
    rfq = _rfq()
    rfq.items[0].specification = '纯度99%'
    if ambiguous:
        rfq.items.append(SimpleNamespace(id=32, requested_name='乙醇', specification='纯度99%', quantity='20'))
    monkeypatch.setattr(rfq_service, 'get_rfq', lambda *_args: rfq)
    result = _run_immediate(quote_extraction.parse_quote_file(
        SimpleNamespace(), SimpleNamespace(id=5), 14, file_name='quote.csv',
        mime_type='text/csv', content=prediction['items'][0]['quote'].encode()))
    assert result.items[0].rfq_item_id == (None if ambiguous else 31)


def test_identical_candidates_are_deduplicated(monkeypatch):
    prediction = _model_result()
    prediction['items'].append(deepcopy(prediction['items'][0]))
    result = _parse_prediction(monkeypatch, prediction)
    assert len(result.items) == 1
    assert result.items[0].rfq_item_id == 31


@pytest.mark.parametrize('second_id', [31, None, 999])
def test_conflicting_prices_are_not_bound_automatically(monkeypatch, second_id):
    prediction = _model_result()
    other = deepcopy(prediction['items'][0])
    other['quote'] = other['quote'].replace('12.5', '15.5')
    other['unit_price'] = '15.5'
    other['rfq_item_id'] = second_id
    other['evidence']['unit_price'] = '15.5 CNY/L'
    prediction['items'].append(other)
    result = _parse_prediction(monkeypatch, prediction)
    assert len(result.items) == 2
    assert all(item.rfq_item_id is None for item in result.items)
    assert any('冲突候选' in warning for warning in result.warnings)
