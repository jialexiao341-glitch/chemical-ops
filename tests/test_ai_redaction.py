"""回归用例确定性脱敏：只遮蔽可判定的联系与身份信息，业务实体保持原样。"""

from app.modules.ai import redaction


def test_redacts_contact_identity_and_network_fields():
    question = (
        "联系人：张三，电话13800138000，邮箱zhang.san@example.com，"
        "身份证110101199001011234，银行卡6222020202020202，IP 192.168.1.8；"
        "客户名称：上海某某化工有限公司。查合成乙醇库存。"
    )

    result = redaction.redact(question)

    assert "13800138000" not in result.text
    assert "zhang.san@example.com" not in result.text
    assert "110101199001011234" not in result.text
    assert "6222020202020202" not in result.text
    assert "192.168.1.8" not in result.text
    assert "张三" not in result.text
    assert "上海某某化工有限公司" not in result.text
    assert "联系人：[联系人]" in result.text
    assert "电话[手机号]" in result.text
    assert "客户名称：[单位名称]" in result.text
    assert result.findings == {
        "email": 1, "id_card": 1, "bank_card": 1, "mobile": 1,
        "ip": 1, "company": 1, "contact": 1,
    }
    # 业务实体不能被误伤：产品名与单号仍需可复现。
    assert "查合成乙醇库存" in result.text


def test_plain_business_text_is_untouched_and_redaction_is_idempotent():
    question = "采购单 PO-2026-001 的合成乙醇到货了吗？数量 120 千克。"

    result = redaction.redact(question)

    assert result.text == question
    assert result.findings == {}
    assert redaction.has_findings(question) is False

    once = redaction.redact("联系电话 13800138000，联系人：李四")
    twice = redaction.redact(once.text)
    assert twice.text == once.text
    assert twice.findings == {}


def test_redacts_landline_and_contact_punctuation_variants():
    result = redaction.redact("收货人: 王五；座机 021-12345678，邮箱 a@b.cn")

    assert "王五" not in result.text
    assert "021-12345678" not in result.text
    assert result.text.count("[联系人]") == 1
    assert result.findings["landline"] == 1