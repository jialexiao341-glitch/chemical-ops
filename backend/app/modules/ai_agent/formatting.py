"""AI 回答中的数值展示格式。

数据库金额与数量使用 Decimal，直接插值会把数据库标度一并带上
（例如 54.240000）。展示层统一去掉无意义的尾随零，不改变业务精度。
"""

from decimal import Decimal, InvalidOperation


def _to_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def format_decimal(value: object | None) -> str:
    """把 Decimal/数字/数字字符串格式化为无尾随零的文本；None 返回空串。"""

    if value is None:
        return ""
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return value if isinstance(value, str) else str(value)
    text = format(decimal_value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_amount(value: object | None) -> str:
    """金额按两位小数展示；数据库多余标度不直接暴露给用户。"""

    if value is None:
        return ""
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return value if isinstance(value, str) else str(value)
    return format(decimal_value, ".2f")
