"""回归用例的确定性脱敏：只按固定规则遮蔽联系与身份信息，不调用模型。

规则只覆盖可判定的敏感字段（电话、邮箱、身份证、银行卡、IP、联系人/单位名称）。
产品名、供应商名等业务实体不在这里改写，仍需提交人确认；服务端在保存前统一执行，
避免客户端漏改把原始联系方式写进评测集。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 顺序即优先级：身份证先于银行卡（18 位身份证也满足 16-19 位数字），
# 邮箱先于手机号，单位名称先于联系人，避免后一条规则只遮蔽半段文本。
_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("email", "[邮箱]", re.compile(r"(?<![\w.%+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("id_card", "[身份证号]", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("bank_card", "[银行卡号]", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    ("mobile", "[手机号]", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("landline", "[电话]", re.compile(r"(?<!\d)0\d{2,3}[- ]?\d{7,8}(?!\d)")),
    ("ip", "[IP]", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")),
    ("company", "[单位名称]",
     re.compile(r"(客户名称|供应商名称|单位名称|公司名称)\s*[:：]\s*[^\s，。；、,;]{1,40}")),
    ("contact", "[联系人]",
     re.compile(r"(联系人|收货人|采购员|审批人|经办人|姓名)\s*[:：]\s*"
                r"[\u4e00-\u9fa5]{2,4}(?=[\s，。；、,;]|$)")),
)

CONTACT_KINDS = frozenset(kind for kind, _, _ in _PATTERNS)


@dataclass(frozen=True)
class RedactionResult:
    """脱敏后文本与命中统计；不保留原始敏感值，避免二次泄露。"""

    text: str
    findings: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.findings)


def redact(text: str) -> RedactionResult:
    """按固定规则遮蔽敏感信息；同一输入重复执行结果不变。"""
    masked = text
    findings: dict[str, int] = {}
    for kind, placeholder, pattern in _PATTERNS:
        if kind in ("company", "contact"):
            # 标签保留、值整段替换，避免“联系人：[已脱敏]”之外残留姓名片段。
            def _replace_label(match: re.Match[str], ph: str = placeholder) -> str:
                return f"{match.group(1)}：{ph}"

            masked, count = pattern.subn(_replace_label, masked)
        else:
            masked, count = pattern.subn(placeholder, masked)
        if count:
            findings[kind] = count
    return RedactionResult(text=masked, findings=findings)


def has_findings(text: str) -> bool:
    return redact(text).changed