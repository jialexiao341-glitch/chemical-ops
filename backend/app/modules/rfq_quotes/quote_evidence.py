"""报价字段的统一词面证据边界；不推断语义、不换算单位或币种。"""
from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata


NUMERIC_FIELDS = frozenset({'quoted_quantity', 'unit_price', 'tax_rate', 'moq_quantity',
                           'freight_amount', 'freight_tax_rate', 'lead_days'})


def normalized(value: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def supported(field: str, value, quote: str | None) -> bool:
    if value is None or not quote or not quote.strip():
        return False
    text = normalized(quote)
    if field in {'tax_included', 'freight_tax_included'}:
        negative = r'不含税|未税|(?<![a-z])(?:excluded|not\s+included|exclusive\s+of\s+tax)(?![a-z])'
        has_negative = bool(re.search(negative, text))
        remaining = re.sub(negative, '', text)
        has_positive = bool(re.search(r'含税|(?<![a-z])(?:included|inclusive\s+of\s+tax)(?![a-z])', remaining))
        return has_negative != has_positive and value is has_positive
    if field in NUMERIC_FIELDS:
        try:
            number = Decimal(str(value))
            if not number.is_finite() or number < 0:
                return False
            if field in {'quoted_quantity', 'moq_quantity'} and number <= 0:
                return False
            if field in {'tax_rate', 'freight_tax_rate'} and number > 100:
                return False
            tokens = re.findall(r'(?<![a-z0-9_.])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.])', text)
            # 数字证据必须是单字段短引句；拒绝宽泛整行中碰巧出现的同一个数字。
            return len(tokens) == 1 and Decimal(tokens[0].replace(',', '')) == number
        except (InvalidOperation, ValueError):
            return False
    if field in {'quote_date', 'valid_until'}:
        try:
            expected = date.fromisoformat(str(value))
        except ValueError:
            return False
        matches = re.findall(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?', text)
        return any((int(y), int(m), int(d)) == (expected.year, expected.month, expected.day) for y, m, d in matches)
    token = normalized(str(value))
    if not token:
        return False
    if field == 'currency_code':
        return bool(re.fullmatch(r'[a-z]{3}', token) and re.search(r'(?<![a-z])' + re.escape(token) + r'(?![a-z])', text))
    return token in text
