"""自然语言 → 列表筛选条件（NL2Filter）。

与 Text2SQL 互补：Text2SQL 回答「分析查询」，这里把自然语言解析成
**列表页可用的筛选参数**（不执行任何查询）。

安全边界与 Text2SQL 一致：
- 数据集只能取自 CATALOG 白名单，按 spec.permission 做权限校验；
- 字段只能落在 spec.filters / spec.times 内，其余条件丢弃并说明原因；
- 枚举值经 DATASET_VALUE_HINTS 归一为后端规范值（如 审批中 → APPROVING），
  防止把中文标签原样塞进查询参数。
"""

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError
from app.modules.ai.schema import (
    AIChatMessage,
    AIChatRequest,
    NLFilterRequest,
    NLFilterResult,
    NLFilterTimeRange,
)
from app.modules.ai.catalog import CATALOG, DatasetSpec
from app.modules.ai.llm import chat
from app.modules.ai.llm import extract_json_object
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User

MAX_FILTER_KEYS = 10
MAX_KEYWORDS_LENGTH = 200

# 各数据集常用枚举的「中文标签 → 规范值」；模型输出中文时在此归一。
# 只收录列表接口真实接受的字段，键名与 CATALOG 的 filters 对齐。
DATASET_VALUE_HINTS: dict[str, dict[str, dict[str, str]]] = {
    "purchase_requests": {
        "status": {
            "草稿": "DRAFT",
            "已提交": "SUBMITTED",
            "审批中": "APPROVING",
            "已批准": "APPROVED",
            "已驳回": "REJECTED",
            "已取消": "CANCELLED",
        },
        "priority": {"低": "LOW", "普通": "NORMAL", "高": "HIGH", "紧急": "URGENT"},
    },
    "purchase_orders": {
        "status": {
            "草稿": "DRAFT",
            "审批中": "APPROVING",
            "已批准": "APPROVED",
            "已下单": "ORDERED",
            "部分到货": "PARTIAL",
            "已完成": "COMPLETED",
            "已取消": "CANCELLED",
        },
    },
    "deliveries": {
        "status": {
            "在途": "IN_TRANSIT",
            "已收货": "RECEIVED",
            "检验中": "INSPECTING",
            "验收通过": "ACCEPTED",
            "异常": "EXCEPTION",
        },
    },
    "inventory": {
        "status": {"可用": "AVAILABLE", "冻结": "FROZEN"},
    },
    "quality_acceptances": {
        "result": {
            "待检验": "PENDING",
            "合格": "PASSED",
            "部分合格": "PARTIAL",
            "不合格": "FAILED",
            "待复检": "REINSPECTION",
        },
        "certificate_complete": {"齐全": "1", "不齐全": "0"},
    },
    "exceptions": {
        "type": {
            "短交": "SHORT_DELIVERY",
            "质量异常": "QUALITY",
            "单证缺失": "DOCUMENT",
            "逾期到货": "OVERDUE",
            "其他": "OTHER",
        },
        "severity": {"低": "LOW", "中": "MEDIUM", "高": "HIGH", "严重": "CRITICAL"},
        "status": {
            "待处理": "OPEN",
            "处理中": "PROCESSING",
            "已解决": "RESOLVED",
            "已关闭": "CLOSED",
            "已取消": "CANCELLED",
        },
    },
    "finance_reconciliations": {
        "status": {
            "草稿": "DRAFT",
            "已确认": "CONFIRMED",
            "有争议": "DISPUTED",
            "已关闭": "CLOSED",
            "已取消": "CANCELLED",
        },
    },
    "supplier_quotes": {
        "status": {"草稿": "DRAFT", "已提交": "SUBMITTED", "已中选": "SELECTED", "未中选": "REJECTED"},
    },
    "inventory_transactions": {
        "type": {"入库": "INBOUND", "出库": "OUTBOUND", "盘点调整": "ADJUSTMENT"},
    },
    "finance_invoices": {
        "status": {"草稿": "DRAFT", "已提交": "SUBMITTED", "已核验": "VERIFIED", "已驳回": "REJECTED", "已作废": "VOIDED"},
    },
    "finance_payments": {
        "status": {"已申请": "REQUESTED", "已批准": "APPROVED", "已付款": "PAID", "已驳回": "REJECTED", "已取消": "CANCELLED"},
    },
    "suppliers": {
        "status": {
            "合作中": "ACTIVE",
            "已暂停": "SUSPENDED",
            "已停用": "INACTIVE",
        },
    },
}


def resolve_dataset(dataset: str) -> DatasetSpec:
    """取白名单数据集，未知键报业务错误并列出可选值。"""

    spec = CATALOG.get(dataset)
    if spec is None:
        options = "、".join(sorted(CATALOG))
        raise BusinessValidationError(f"不支持的数据集「{dataset}」，可选：{options}")
    return spec


def require_dataset_access(db: Session, user: User, spec: DatasetSpec) -> None:
    """与 Text2SQL 相同的权限口径：SYS_ADMIN 免查，其余按数据集权限码。"""

    role_codes = set(get_user_role_codes(db, user.id))
    permission_codes = set(get_user_permission_codes(db, user.id))
    if "SYS_ADMIN" not in role_codes and spec.permission not in permission_codes:
        raise BusinessValidationError("当前用户没有解析该数据集筛选条件的权限")


def build_filter_prompt(
    dataset: str, spec: DatasetSpec, question: str, today: date | None = None
) -> str:
    """生成 NL2Filter 提示词；只输出 JSON，不解释。"""

    hints = DATASET_VALUE_HINTS.get(dataset, {})
    hint_text = (
        "\n字段枚举值提示（输出必须用右侧规范值，或直接给规范值）：\n"
        + "\n".join(
            f"- {field}: " + "；".join(f"{label}={value}" for label, value in mapping.items())
            for field, mapping in hints.items()
        )
        if hints
        else ""
    )
    current_date = (today or date.today()).isoformat()
    return (
        "你是 ChemicalOps 化工采购平台的筛选条件解析器。"
        "把用户描述解析成列表页筛选参数，只输出一个 JSON 对象，不要输出任何解释。\n"
        f"今天是 {current_date}。\n"
        f"数据集：{dataset}（{spec.label}）\n"
        f"允许的筛选字段（filters 的键只能从这里选）：{sorted(spec.filters)}\n"
        f"允许的时间字段（time_range.field 只能从这里选）：{sorted(spec.times)}\n"
        f"{hint_text}\n"
        "输出格式：\n"
        '{"filters": {"字段": "值"},'
        ' "time_range": {"field": "时间字段", "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"},'
        ' "keywords": "单号或名称等模糊搜索词"}\n'
        "规则：\n"
        "1. filters 每个键必须在允许的筛选字段内，值是单个标量（字符串/数字），"
        "最多 10 项；条件之间是「且」的关系；无法归类的条件放进 keywords 或省略；\n"
        "2. 用户没给时间范围时 time_range 输出 null；给了相对时间（本月/最近7天）"
        "按今天换算成绝对日期；只有一个边界时另一侧留空（值为 null）；\n"
        "3. keywords 是给关键字模糊搜索用的自由文本（如单号片段、供应商名），"
        "没有就输出 null；长度不超过 200；\n"
        "4. 不在白名单内的字段一律不要输出。\n\n"
        f"用户描述：{question}"
    )


def _parse_date(value: Any) -> date | None:
    """解析模型给的日期；接受 YYYY-MM-DD 与带时间的 ISO 串。"""

    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    return date.fromisoformat(text[:10])


def validate_filter_payload(
    payload: dict[str, Any], spec: DatasetSpec, dataset: str
) -> tuple[dict[str, str], NLFilterTimeRange | None, str | None, list[str]]:
    """白名单 + 格式校验模型输出（纯函数，便于单测）。

    返回 (filters, time_range, keywords, dropped)；被剔除的条件写进 dropped。
    """

    dropped: list[str] = []
    hints = DATASET_VALUE_HINTS.get(dataset, {})
    raw_filters = payload.get("filters")
    if raw_filters is None:
        raw_filters = {}
    if not isinstance(raw_filters, dict):
        raise BusinessValidationError("AI 返回的筛选条件格式不正确")

    filters: dict[str, str] = {}
    for key, value in list(raw_filters.items())[:MAX_FILTER_KEYS + 5]:
        if len(filters) >= MAX_FILTER_KEYS:
            dropped.append(f"{key}: 超过最多 {MAX_FILTER_KEYS} 项，已忽略")
            continue
        if key not in spec.filters:
            dropped.append(f"{key}: 字段不在允许范围")
            continue
        if value is None or isinstance(value, (dict, list, tuple, set)):
            dropped.append(f"{key}: 值必须是单个标量")
            continue
        text = str(value).strip()
        if not text:
            continue
        field_hints = hints.get(key)
        if field_hints:
            # 中文标签归一为规范值；已是规范值时放行，未知值剔除
            canonical = field_hints.get(text, text)
            if canonical not in field_hints.values():
                dropped.append(f"{key}={text}: 不是该字段的合法取值")
                continue
            text = canonical
        filters[key] = text

    time_range: NLFilterTimeRange | None = None
    raw_range = payload.get("time_range")
    if isinstance(raw_range, dict) and raw_range:
        field = str(raw_range.get("field") or "").strip()
        if field not in spec.times:
            dropped.append(f"time_range.field={field or '(空)'}: 时间字段不在允许范围")
        else:
            try:
                parsed_from = _parse_date(raw_range.get("date_from"))
                parsed_to = _parse_date(raw_range.get("date_to"))
                if parsed_from is None and parsed_to is None:
                    dropped.append("time_range: 缺少起止日期")
                else:
                    if parsed_from and parsed_to and parsed_from > parsed_to:
                        dropped.append("time_range: 开始日期晚于结束日期，已忽略")
                    else:
                        time_range = NLFilterTimeRange(
                            field=field, date_from=parsed_from, date_to=parsed_to
                        )
            except ValueError:
                dropped.append(
                    f"time_range: 日期格式不正确（{raw_range.get('date_from')} / {raw_range.get('date_to')}）"
                )
    elif raw_range is not None and not isinstance(raw_range, dict):
        dropped.append("time_range: 格式不正确")

    keywords: str | None = None
    raw_keywords = payload.get("keywords")
    if raw_keywords is not None:
        if isinstance(raw_keywords, str):
            cleaned = raw_keywords.strip()[:MAX_KEYWORDS_LENGTH]
            keywords = cleaned or None
        else:
            dropped.append("keywords: 必须是字符串")

    return filters, time_range, keywords, dropped


async def parse_filters(db: Session, user: User, request: NLFilterRequest) -> NLFilterResult:
    """自然语言 → 白名单内的列表筛选条件（不执行查询）。"""

    dataset = request.dataset.strip()
    spec = resolve_dataset(dataset)
    require_dataset_access(db, user, spec)

    prompt = build_filter_prompt(dataset, spec, request.question)
    result = await chat(
        AIChatRequest(messages=[AIChatMessage(role="user", content=prompt)]),
        response_format={"type": "json_object"},
    )
    raw = result.message.content
    try:
        payload = extract_json_object(raw)
    except BusinessValidationError as exc:
        raise BusinessValidationError("AI 未能返回合法的筛选条件，请换个说法重试") from exc

    filters, time_range, keywords, dropped = validate_filter_payload(payload, spec, dataset)
    if not filters and time_range is None and not keywords:
        detail = f"（已剔除：{'；'.join(dropped)}）" if dropped else ""
        raise BusinessValidationError(
            f"未能从描述中解析出可用的筛选条件，请明确字段与取值，例如「审批中的高优先级申请」{detail}"
        )

    return NLFilterResult(
        dataset=dataset,
        dataset_label=spec.label,
        filters=filters,
        time_range=time_range,
        keywords=keywords,
        dropped=dropped,
        raw=raw,
    )
