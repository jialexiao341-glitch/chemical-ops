"""生成文案的数值/单位白名单；不能替代指标语义和引用关系评测。"""
import json
import re
from decimal import Decimal

NUMBER = re.compile(r"(?<![A-Za-z0-9_.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
UNIT_GROUPS = (
    ("CNY", "人民币", "元"), ("USD", "美元"), ("EUR", "欧元"),
    ("千克", "公斤", "kg"), ("吨", "t"), ("克", "g"),
    ("毫升", "mL", "ml"), ("升", "L"), ("%", "％"),
)
UNITS = re.compile("|".join((r"(?<![A-Za-z])" + re.escape(unit) + r"(?![A-Za-z])") if unit.isascii() and unit.isalpha() else re.escape(unit) for group in UNIT_GROUPS for unit in group))
CHINESE_QUANTITY = re.compile(r"[零〇一二三四五六七八九十百千万亿两]+(?:点[零一二三四五六七八九]+)?(?=\s*(?:元|美元|欧元|吨|千克|公斤|升|克|毫升|条|单|个|件|%|％))")


def numbers(text: str) -> set[Decimal]:
    return {Decimal(match.group().replace(",", "")) for match in NUMBER.finditer(text)}


def faithful_numbers(answer: str, evidence: object) -> bool:
    """只用服务端证据，不把用户提问或生成指令当作数值依据。"""
    source = json.dumps(evidence, ensure_ascii=False, default=str)
    if not numbers(answer) <= numbers(source):
        return False
    # 不允许通过中文数字或数量级换写绕开 literal 校验。
    if any(match.group() not in source for match in CHINESE_QUANTITY.finditer(answer)):
        return False
    if re.search(r"\d\s*[万亿]", answer) and not re.search(r"\d\s*[万亿]", source):
        return False
    allowed = set(UNITS.findall(source))
    for group in UNIT_GROUPS:
        if allowed.intersection(group):
            allowed.update(group)
    # 单位仅在数值之后识别，避免将名称中的单字误判为单位。
    for match in NUMBER.finditer(answer):
        tail = answer[match.end():].lstrip()
        unit = UNITS.match(tail)
        if unit and unit.group() not in allowed:
            return False
    return True
