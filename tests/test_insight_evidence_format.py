from app.modules.insights.controller import _evidence, _result


def test_insight_evidence_trims_decimal_padding_without_changing_identifiers():
    result = _result("test", "测试", "测试", "")

    _evidence(result, "库存", "可用 126.000000 升；纯度 99.500000%；单据 PO-2026-0001", "库存记录")

    assert result.evidence[0].value == "可用 126 升；纯度 99.5%；单据 PO-2026-0001"
