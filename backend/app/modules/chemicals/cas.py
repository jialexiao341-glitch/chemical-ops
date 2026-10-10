"""CAS 号的提取与校验；不依赖 AI 路由或数据库。"""

import re

_CAS_RE = re.compile(r"(?<![\d-])\d{2,7}-\d{2}-\d(?![\d-])")


def valid_cas_checksum(cas: str) -> bool:
    """校验 CAS 校验码（加权求和取模）。"""

    digits = cas.replace("-", "")
    check_digit = int(digits[-1])
    weighted = sum(int(digit) * index for index, digit in enumerate(reversed(digits[:-1]), start=1))
    return weighted % 10 == check_digit


def extract_valid_cas(text: str) -> list[str]:
    """提取文本中校验码合法的 CAS 号（去重、保序）。"""

    found: list[str] = []
    for match in _CAS_RE.finditer(text):
        cas = match.group(0)
        if valid_cas_checksum(cas) and cas not in found:
            found.append(cas)
    return found
