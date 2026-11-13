"""化学品接口的 Pydantic 请求和响应模型。"""

from datetime import datetime
from decimal import Decimal
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChemicalFields(BaseModel):
    """化学品字段；历史记录可缺少 CAS 号。"""

    chemical_name: str = Field(min_length=1, max_length=255)
    english_name: str | None = Field(default=None, max_length=255)
    alias_text: str | None = None
    cas_no: str | None = Field(default=None, max_length=32)
    chemical_formula: str | None = Field(default=None, max_length=128)
    molecular_weight: Decimal | None = None
    hazard_class: str | None = Field(default=None, max_length=128)
    source_text: str | None = Field(default=None, max_length=500)


class ChemicalValidationMixin(BaseModel):
    @field_validator('chemical_name', 'cas_no', 'english_name', 'chemical_formula', 'source_text', mode='before', check_fields=False)
    @classmethod
    def validate_text(cls, value, info):
        field = info.field_name
        value = value.strip() if isinstance(value, str) else value
        if field in ('chemical_name', 'cas_no'):
            if not value:
                raise ValueError('此字段为必填项')
            if field == 'cas_no':
                if not re.fullmatch(r'[0-9]{2,7}-[0-9]{2}-[0-9]', value):
                    raise ValueError('CAS 号格式应为 123-45-6')
                digits = value.replace('-', '')
                if sum(int(digit) * i for i, digit in enumerate(reversed(digits[:-1]), 1)) % 10 != int(digits[-1]):
                    raise ValueError('CAS 号校验位不正确')
        elif field == 'english_name' and value and not re.search(r'[A-Za-z]', value):
            raise ValueError('英文名称须包含英文字母')
        elif field == 'chemical_formula' and value:
            # 允许常见元素符号、括号和水合物分隔符；不推断化学组成是否真实。
            tokens = re.findall(r'[A-Z][a-z]?|[0-9]+|[()\[\].·]', value)
            stack = []
            balanced = True
            for token in tokens:
                if token in ('(', '['):
                    stack.append(token)
                elif token in (')', ']'):
                    if not stack or stack.pop() != {')': '(', ']': '['}[token]:
                        balanced = False
                        break
            if ''.join(tokens) != value or not tokens or not re.match(r'[A-Z(\[]', value) or not re.search(r'[A-Za-z0-9)\]]$', value) or not balanced or stack:
                raise ValueError('分子式格式不正确')
        elif field == 'source_text' and value and (re.match(r'(?i)^(https?\s*:|www\.)', value) or '://' in value):
            try:
                parsed = urlsplit(value)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or any(c.isspace() for c in value) or parsed.port is not None and not 0 < parsed.port < 65536:
                    raise ValueError
            except ValueError:
                raise ValueError('资料来源网址须为有效的 HTTP 或 HTTPS 地址') from None
        return value or None

    @field_validator('molecular_weight', check_fields=False)
    @classmethod
    def validate_weight(cls, value):
        if value is not None and (not value.is_finite() or value <= 0):
            raise ValueError('分子量须大于 0')
        return value


class ChemicalCreate(ChemicalValidationMixin, ChemicalFields):
    """创建和 CSV 导入共用校验。"""
    cas_no: str = Field(min_length=1, max_length=32)


class ChemicalUpdate(ChemicalValidationMixin):
    """部分更新接口允许提交的可选字段。"""

    chemical_name: str | None = Field(default=None, min_length=1, max_length=255)
    english_name: str | None = Field(default=None, max_length=255)
    alias_text: str | None = None
    cas_no: str | None = Field(default=None, max_length=32)
    chemical_formula: str | None = Field(default=None, max_length=128)
    molecular_weight: Decimal | None = None
    hazard_class: str | None = Field(default=None, max_length=128)
    source_text: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern="^(ACTIVE|INACTIVE)$")


class ChemicalRead(ChemicalFields):
    """包含系统生成字段的化学品响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_at: datetime
    updated_at: datetime


class ChemicalPage(BaseModel):
    """分页化学品列表响应。"""

    items: list[ChemicalRead]
    total: int
    page: int
    page_size: int
