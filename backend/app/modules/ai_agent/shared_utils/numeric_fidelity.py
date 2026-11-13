"""生成文案的字面值与字段/行关联护栏；无法确定的关联使用调用方模板回退。

不尝试通过关键词猜测自然语言指标。多字段必须逐项使用服务端显示名，
多行必须在同一分句保留实体名。该保守契约不代表真实模型回答质量评测。
"""
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


def _unit_aliases(text: str) -> set[str]:
    allowed = set(UNITS.findall(text))
    for group in UNIT_GROUPS:
        if allowed.intersection(group):
            allowed.update(group)
    return allowed


def _numeric_associations(answer: str, evidence: object) -> bool:
    if not isinstance(evidence, dict):
        return not numbers(answer)
    labels = {column["key"]: column["label"] for column in evidence.get("render_columns", [])
              if isinstance(column, dict) and column.get("key") and column.get("label")}
    # 元数据、字段说明和提问均不能充当业务事实。仅遍历结果行或快照数据。
    data = evidence.get("rows", evidence)
    facts = []

    def visit(value: object, inherited_unit: str = "") -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, inherited_unit)
        elif isinstance(value, dict):
            unit = str(value.get("unit") or value.get("currency") or value.get("currency_code") or inherited_unit)
            anchors = [str(item) for key, item in value.items()
                       if isinstance(item, str) and not NUMBER.fullmatch(item)
                       and key not in {"unit", "currency", "currency_code", "date"}]
            for key, item in value.items():
                if isinstance(item, (dict, list)):
                    visit(item, unit)
                elif not isinstance(item, bool) and NUMBER.fullmatch(str(item)):
                    facts.append((labels.get(key, key), Decimal(str(item).replace(",", "")),
                                  _unit_aliases(unit), anchors))

    visit(data, str(evidence.get("unit") or ""))
    for match in NUMBER.finditer(answer):
        value = Decimal(match.group().replace(",", ""))
        # 保留小数点和千分位；仅以自然语言分句符划分关联范围。
        prefix = re.split(r"[；;。！？\n，]", answer[:match.start()])[-1]
        unit_match = UNITS.match(answer[match.end():].lstrip(" *"))
        candidates = []
        for label, expected, allowed_units, anchors in facts:
            if value != expected or (unit_match and unit_match.group() not in allowed_units):
                continue
            # 单一无显示名指标保留旧协议；复杂结果必须明确字段关系。
            if len(facts) > 1 or labels:
                if not re.search(re.escape(label) + r"\s*[*：:]*\s*(?:为|是)?\s*[*]*\s*$", prefix):
                    continue
            if isinstance(data, list) and len(data) > 1:
                all_anchors = {anchor for fact in facts for anchor in fact[3]}
                last = max(((prefix.rfind(anchor), anchor) for anchor in all_anchors), default=(-1, ""))
                if last[0] < 0 or last[1] not in anchors:
                    continue
            candidates.append(expected)
        if not candidates:
            return False
    return True


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
    return _numeric_associations(answer, evidence)
