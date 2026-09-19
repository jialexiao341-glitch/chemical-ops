"""受约束的 Text2SQL 查询链。

模型只负责把问题整理成结构化 QueryPlan；SQL 由后端基于白名单和 ORM 生成，
因此不会执行模型返回的原始 SQL，也不会开放任何业务写入能力。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import BusinessValidationError
from app.modules.deliveries.model import Delivery
from app.modules.finance.model import FinanceReconciliation
from app.modules.inventory.model import InventoryBalance, InventoryBatch, Warehouse
from app.modules.operation_exceptions.model import OperationException
from app.modules.products.model import Product
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.suppliers.model import Supplier
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User
from app.modules.ai.schema import AIChatMessage, AIChatRequest, AIQueryTrace
from app.modules.ai.service import chat


LOGGER = logging.getLogger("chemicalops.ai.text2sql")


class QueryFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=64)
    operator: Literal["eq", "contains", "gte", "lte", "in"] = "eq"
    value: str | int | float | list[str | int | float]


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    metric: str
    time_field: str | None = "created_at"
    date_from: date | None = None
    date_to: date | None = None
    group_by: str | None = None
    filters: list[QueryFilter] = Field(default_factory=list)
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=20, ge=1, le=100)


class Text2SQLRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    limit: int = Field(default=20, ge=1, le=100)


class Text2SQLResponse(BaseModel):
    question: str
    plan: QueryPlan
    sql: str
    parameterized_sql: str
    columns: list[str]
    slots: list[dict[str, Any]]
    template: str
    render_columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    stages: list[str]
    render: dict[str, Any]
    unit: str | None
    unit_note: str | None
    read_only: Literal[True] = True


from app.modules.ai.agent_prompt import text2sql_plan_prompt
from app.modules.ai.catalog import CATALOG
from app.modules.ai.intent import Intent, classify_intent


TABLE_REFERENCE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
FORBIDDEN_SQL = re.compile(r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|GRANT|REVOKE|CALL|LOAD|OUTFILE|INTO)\b", re.I)



def validate_sql(sql: str, table_names: frozenset[str]) -> str:
    normalized = re.sub(r"\s+", " ", sql.strip())
    if not normalized.upper().startswith("SELECT "):
        raise BusinessValidationError("只允许生成查询语句")
    if ";" in normalized or "--" in normalized or "/*" in normalized or "#" in normalized:
        raise BusinessValidationError("查询语句包含不允许的分隔符或注释")
    if FORBIDDEN_SQL.search(normalized):
        raise BusinessValidationError("查询语句包含危险操作")
    referenced = set(TABLE_REFERENCE.findall(normalized.replace(chr(96), "")))
    if not referenced or not referenced.issubset(table_names):
        raise BusinessValidationError("查询使用了未授权的数据表")
    return normalized


def _base_statement(plan: QueryPlan) -> tuple[Select[Any], Any, dict[str, Any]]:
    if plan.dataset == "purchase_orders":
        return select(PurchaseOrder).join(Supplier, PurchaseOrder.supplier_id == Supplier.id), PurchaseOrder, {"supplier": Supplier.supplier_name, "status": PurchaseOrder.status, "currency": PurchaseOrder.currency_code, "supplier_name": Supplier.supplier_name, "currency_code": PurchaseOrder.currency_code}
    if plan.dataset == "deliveries":
        return select(Delivery).join(Supplier, Delivery.supplier_id == Supplier.id), Delivery, {"supplier": Supplier.supplier_name, "status": Delivery.status, "supplier_name": Supplier.supplier_name}
    if plan.dataset == "inventory":
        stmt = select(InventoryBalance).join(Product, InventoryBalance.product_id == Product.id).join(InventoryBatch, InventoryBatch.id == InventoryBalance.batch_id).join(Warehouse, InventoryBalance.warehouse_id == Warehouse.id)
        return stmt, InventoryBalance, {"product": Product.product_name, "warehouse": Warehouse.warehouse_name, "status": InventoryBalance.status, "product_name": Product.product_name, "warehouse_name": Warehouse.warehouse_name, "expiry_date": InventoryBatch.expiry_date}
    if plan.dataset == "quality_acceptances":
        return select(QualityAcceptance).join(Delivery, QualityAcceptance.delivery_id == Delivery.id), QualityAcceptance, {"result": QualityAcceptance.result, "certificate_complete": QualityAcceptance.certificate_complete}
    if plan.dataset == "exceptions":
        return select(OperationException), OperationException, {"type": OperationException.exception_type, "severity": OperationException.severity, "status": OperationException.status}
    if plan.dataset == "finance_reconciliations":
        return select(FinanceReconciliation).join(Supplier, FinanceReconciliation.supplier_id == Supplier.id), FinanceReconciliation, {"supplier": Supplier.supplier_name, "status": FinanceReconciliation.status, "currency": FinanceReconciliation.currency_code, "supplier_name": Supplier.supplier_name, "currency_code": FinanceReconciliation.currency_code}
    if plan.dataset == "suppliers":
        return select(Supplier), Supplier, {"region": Supplier.region, "cooperation_level": Supplier.cooperation_level, "status": Supplier.status}
    raise BusinessValidationError("未授权的数据集")


def _field(model: Any, name: str) -> Any:
    value = getattr(model, name, None)
    if value is None:
        raise BusinessValidationError(f"数据集不支持字段：{name}")
    return value


def build_statement(plan: QueryPlan) -> Select[Any]:
    spec = CATALOG.get(plan.dataset)
    if spec is None:
        raise BusinessValidationError("未授权的数据集")
    stmt, model, aliases = _base_statement(plan)
    metric = func.count(model.id) if plan.metric in {"count", "amount"} else func.sum(_field(model, "quantity"))
    if plan.metric == "amount":
        metric = func.sum(_field(model, "order_amount" if plan.dataset == "purchase_orders" else "total_amount"))
    group_keys = [plan.group_by] if plan.group_by else []
    # 金额必须按币种分组，避免把 CNY、USD 等不同币种直接相加。
    if plan.metric == "amount" and "currency" in aliases and plan.group_by != "currency":
        group_keys.append("currency")
    expressions: list[Any] = [metric.label("metric_value")]
    for group_key in reversed(group_keys):
        expressions.insert(0, aliases[group_key].label(group_key))
    stmt = select(*expressions).select_from(stmt.get_final_froms()[0]) if False else stmt.with_only_columns(*expressions)
    predicates: list[Any] = []
    for item in plan.filters:
        field = aliases.get(item.field)
        if field is None:
            raise BusinessValidationError(f"不允许按字段筛选：{item.field}")
        if item.operator == "eq": predicates.append(field == item.value)
        elif item.operator == "contains": predicates.append(field.like(f"%{item.value}%"))
        elif item.operator == "gte": predicates.append(field >= item.value)
        elif item.operator == "lte": predicates.append(field <= item.value)
        elif item.operator == "in": predicates.append(field.in_(item.value if isinstance(item.value, list) else [item.value]))
    if plan.time_field and (plan.date_from or plan.date_to):
        time_field = _field(model, plan.time_field)
        if plan.date_from: predicates.append(time_field >= plan.date_from)
        if plan.date_to: predicates.append(time_field < date.fromordinal(plan.date_to.toordinal() + 1))
    if predicates: stmt = stmt.where(and_(*predicates))
    if group_keys: stmt = stmt.group_by(*(aliases[group_key] for group_key in group_keys))
    stmt = stmt.order_by(desc("metric_value") if plan.order == "desc" else "metric_value")
    return stmt.limit(plan.limit + 1)


def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)): return value.isoformat()
    if isinstance(value, Decimal):
        text = format(value, "f").rstrip("0").rstrip(".")
        return text or "0"
    if isinstance(value, str): return value.strip()
    return value


DATASET_LABELS = {
    "purchase_orders": "采购订单",
    "deliveries": "到货单",
    "inventory": "库存",
    "quality_acceptances": "质量验收",
    "exceptions": "运营异常",
    "finance_reconciliations": "财务对账",
    "suppliers": "供应商",
}
METRIC_LABELS = {"count": "数量", "amount": "金额", "sum_quantity": "数量合计"}
DIMENSION_LABELS = {"supplier": "供应商", "status": "状态", "currency": "币种", "product": "产品", "warehouse": "仓库", "result": "验收结果", "severity": "严重程度", "type": "异常类型"}
FIELD_LABELS = {"metric_value": "指标值", **DIMENSION_LABELS}


def _build_slots(plan: QueryPlan) -> list[dict[str, Any]]:
    """把 QueryPlan 转为用户可读的已抽取槽位。"""

    values: list[tuple[str, str, Any, str]] = [
        ("dataset", "数据集", plan.dataset, DATASET_LABELS.get(plan.dataset, plan.dataset)),
        ("metric", "指标", plan.metric, METRIC_LABELS.get(plan.metric, plan.metric)),
        ("time_field", "时间字段", plan.time_field, plan.time_field or "不限时间"),
        ("date_range", "时间范围", {"from": plan.date_from, "to": plan.date_to}, f"{plan.date_from or '不限'} 至 {plan.date_to or '不限'}"),
        ("group_by", "分组维度", plan.group_by, DIMENSION_LABELS.get(plan.group_by, plan.group_by or "不分组")),
        ("filters", "筛选条件", [item.model_dump(mode="json") for item in plan.filters], f"{len(plan.filters)} 项"),
        ("order", "排序", plan.order, "降序" if plan.order == "desc" else "升序"),
        ("limit", "返回上限", plan.limit, f"最多 {plan.limit} 条"),
    ]
    return [{"name": name, "label": label, "value": value, "display_value": display_value, "status": "filled" if value not in (None, [], "") else "empty"} for name, label, value, display_value in values]


def _build_query_template(plan: QueryPlan) -> str:
    metric = "SUM(order_amount)" if plan.metric == "amount" and plan.dataset == "purchase_orders" else plan.metric.upper()
    group = DIMENSION_LABELS.get(plan.group_by, plan.group_by or "整体")
    time_range = f"{plan.date_from or '起始时间'} 至 {plan.date_to or '结束时间'}" if plan.date_from or plan.date_to else "不限时间"
    return f"{DATASET_LABELS.get(plan.dataset, plan.dataset)} · {metric} · 按{group}分组 · {time_range} · {'降序' if plan.order == 'desc' else '升序'} · TOP {plan.limit}"


def _build_render_columns(plan: QueryPlan, columns: list[str]) -> list[dict[str, str]]:
    labels = {**FIELD_LABELS, "metric_value": METRIC_LABELS.get(plan.metric, "指标值")}
    return [{"key": column, "label": labels.get(column, column), "format": "amount" if column == "metric_value" and plan.metric == "amount" else "text"} for column in columns]


def _unit_metadata(plan: QueryPlan, rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """只从查询结果或固定指标语义推导单位，不让模型猜单位。"""

    if plan.metric == "amount":
        currencies = sorted({str(row.get("currency")).strip().upper() for row in rows if row.get("currency")})
        if len(currencies) == 1:
            return currencies[0], "币种来自查询结果的 currency 字段"
        if currencies:
            return "多币种", "查询结果已按币种分组，不能合并为单一币种"
        return None, "查询结果未返回币种，不能安全补充金额单位"
    if plan.metric == "count":
        return "条", "数量指标的固定单位"
    if plan.metric == "sum_quantity":
        return "原计量单位", "库存数量的计量单位未进入当前聚合结果"
    return None, None


def _compile_statement(statement: Select[Any], db: Session, *, literal_binds: bool) -> str:
    bind = db.get_bind() if callable(getattr(db, "get_bind", None)) else None
    dialect = getattr(bind, "dialect", None)
    return str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": literal_binds}))


def _validate_plan(db: Session, user: User, plan: QueryPlan) -> None:
    spec = CATALOG.get(plan.dataset)
    if spec is None or plan.metric not in spec.metrics:
        raise BusinessValidationError("查询指标不在允许范围内")
    if plan.group_by and plan.group_by not in spec.dimensions:
        raise BusinessValidationError("分组字段不在允许范围内")
    if plan.time_field and plan.time_field not in spec.times:
        raise BusinessValidationError("时间字段不在允许范围内")
    if any(item.field not in spec.filters for item in plan.filters):
        raise BusinessValidationError("筛选字段不在允许范围内")
    role_codes = set(get_user_role_codes(db, user.id))
    permission_codes = set(get_user_permission_codes(db, user.id))
    if "SYS_ADMIN" not in role_codes and spec.permission not in permission_codes:
        raise BusinessValidationError("当前用户没有执行该数据集查询的权限")


_QUERY_PLAN_FIELDS = frozenset({"dataset", "metric", "time_field", "date_from", "date_to", "group_by", "filters", "order", "limit"})


def _extract_query_plan_payload(raw: str) -> dict[str, Any]:
    """从模型输出中提取第一个合法 JSON 对象，兼容代码块和前置说明。"""

    cleaned = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).replace("```", "")
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            payload, _ = decoder.raw_decode(cleaned, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise BusinessValidationError("AI 未返回有效的查询计划")


def _normalize_query_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """规范化常见模型别名；最终仍由 QueryPlan 和 RBAC 白名单校验。"""

    aliases = {
        "data_source": "dataset",
        "data_set": "dataset",
        "measure": "metric",
        "dimension": "group_by",
        "sort_order": "order",
        "top_n": "limit",
    }
    normalized = {aliases.get(key, key): value for key, value in payload.items() if aliases.get(key, key) in _QUERY_PLAN_FIELDS}
    dataset_aliases = {"purchase_order": "purchase_orders", "purchase_orders_summary": "purchase_orders"}
    metric_aliases = {"sum_amount": "amount", "total_amount": "amount", "order_amount": "amount", "sum_order_amount": "amount", "total": "amount"}
    group_aliases = {"supplier_name": "supplier", "supplier_id": "supplier", "currency_code": "currency"}
    if normalized.get("dataset") in dataset_aliases:
        normalized["dataset"] = dataset_aliases[normalized["dataset"]]
    if normalized.get("metric") in metric_aliases:
        normalized["metric"] = metric_aliases[normalized["metric"]]
    if normalized.get("group_by") in group_aliases:
        normalized["group_by"] = group_aliases[normalized["group_by"]]
    if normalized.get("order") in {"升序", "正序"}:
        normalized["order"] = "asc"
    elif normalized.get("order") in {"降序", "倒序"}:
        normalized["order"] = "desc"
    if normalized.get("filters") is None:
        normalized["filters"] = []
    elif isinstance(normalized.get("filters"), dict):
        normalized["filters"] = [normalized["filters"]]
    if isinstance(normalized.get("limit"), str) and normalized["limit"].isdigit():
        normalized["limit"] = int(normalized["limit"])
    for field in ("date_from", "date_to"):
        if normalized.get(field) in {"", "null", "None"}:
            normalized[field] = None
    return normalized


def _fallback_query_plan(question: str) -> QueryPlan | None:
    """为高频供应商采购金额查询提供不依赖模型格式的安全兜底。"""

    normalized = question.lower()
    is_overdue_delivery = "逾期" in normalized and any(marker in normalized for marker in ("到货", "收货", "入库"))
    if is_overdue_delivery:
        today = date.today()
        return QueryPlan(
            dataset="deliveries",
            metric="count",
            time_field="expected_arrival_date",
            date_from=today - timedelta(days=today.weekday()) if "本周" in normalized else None,
            date_to=today - timedelta(days=1),
            filters=[QueryFilter(field="status", operator="eq", value="IN_TRANSIT")],
            group_by="supplier",
            order="desc",
            limit=20,
        )
    is_supplier_amount = "供应商" in normalized and ("采购" in normalized or "订单" in normalized) and any(marker in normalized for marker in ("金额", "总额", "合计", "花费"))
    if not is_supplier_amount:
        return None
    today = date.today()
    limit_match = re.search(r"(?:top|最多(?:显示)?|前)\s*(\d+)", normalized) or re.search(r"(\d+)\s*家", normalized)
    limit = min(int(limit_match.group(1)), 100) if limit_match else 20
    return QueryPlan(
        dataset="purchase_orders",
        metric="amount",
        time_field="order_date" if any(marker in normalized for marker in ("本月", "上月", "今年", "去年")) else "created_at",
        date_from=today.replace(day=1) if "本月" in normalized else None,
        date_to=today if "本月" in normalized else None,
        group_by="supplier",
        order="desc",
        limit=limit,
    )

async def _understand_question(question: str, settings: Settings) -> QueryPlan:
    fallback = _fallback_query_plan(question)
    if fallback is not None and "逾期" in question and any(marker in question for marker in ("到货", "收货", "入库")):
        LOGGER.info("AI 查询计划使用安全兜底 question=%s plan=%s", question, fallback.model_dump(mode="json"))
        return fallback
    prompt = text2sql_plan_prompt(question)
    result = await chat(AIChatRequest(messages=[AIChatMessage(role="user", content=prompt)]), settings, response_format={"type": "json_object"})
    raw = result.message.content
    LOGGER.info("AI 查询计划原始输出 question=%s raw=%s", question, raw)
    try:
        payload = _extract_query_plan_payload(raw)
        return QueryPlan.model_validate(_normalize_query_plan_payload(payload))
    except (BusinessValidationError, ValueError, TypeError) as exc:
        LOGGER.warning("AI 查询计划解析失败 question=%s error=%s raw=%s", question, exc, raw)
        fallback = _fallback_query_plan(question)
        if fallback is not None:
            LOGGER.info("AI 查询计划使用安全兜底 question=%s plan=%s", question, fallback.model_dump(mode="json"))
            return fallback
        raise BusinessValidationError("AI 返回的查询计划格式不正确") from exc




class Text2SQLState(TypedDict, total=False):
    question: str
    request_limit: int
    plan: QueryPlan
    sql: str
    parameterized_sql: str
    slots: list[dict[str, Any]]
    template: str
    render_columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    truncated: bool
    stages: list[str]
    render: dict[str, Any]
    unit: str | None
    unit_note: str | None


async def run_text2sql(
    db: Session,
    user: User,
    request: Text2SQLRequest,
    settings: Settings | None = None,
) -> Text2SQLResponse:
    """执行 Query Understanding -> Slot Filling -> Planning -> Validation -> Execution。"""

    intent = classify_intent(request.question)
    if intent.intent is not Intent.QUERY:
        raise BusinessValidationError("Text2SQL 只支持采购运营相关的查询咨询，请改为查询订单、库存、到货、质量、异常、财务或供应商数据。")

    runtime = settings or get_settings()

    async def understand(state: Text2SQLState) -> dict[str, Any]:
        plan = await _understand_question(state["question"], runtime)
        return {
            "plan": plan,
            "slots": _build_slots(plan),
            "template": _build_query_template(plan),
            "stages": [*state.get("stages", []), "query_understanding"],
        }

    def validate_plan_node(state: Text2SQLState) -> dict[str, Any]:
        plan = state["plan"].model_copy(update={"limit": min(state["plan"].limit, state["request_limit"])})
        _validate_plan(db, user, plan)
        return {"plan": plan, "stages": [*state.get("stages", []), "slot_filling"]}

    def generate_sql(state: Text2SQLState) -> dict[str, Any]:
        # ORM 语句由白名单映射生成；模型返回值只作为 QueryPlan，不进入执行器。
        statement = build_statement(state["plan"])
        tables = CATALOG[state["plan"].dataset].tables
        parameterized_sql = validate_sql(_compile_statement(statement, db, literal_binds=False), tables)
        sql = validate_sql(_compile_statement(statement, db, literal_binds=True), tables)
        return {"sql": sql, "parameterized_sql": parameterized_sql, "stages": [*state.get("stages", []), "query_planning"]}

    def validate_sql_node(state: Text2SQLState) -> dict[str, Any]:
        return {"sql": validate_sql(state["sql"], CATALOG[state["plan"].dataset].tables), "stages": [*state.get("stages", []), "sql_validation"]}

    def execute(state: Text2SQLState) -> dict[str, Any]:
        result = db.execute(build_statement(state["plan"])).mappings().all()
        truncated = len(result) > state["plan"].limit
        result = result[: state["plan"].limit]
        rows = [{str(key): _serialize(value) for key, value in row.items()} for row in result]
        columns = list(rows[0].keys()) if rows else (["metric_value"] if not state["plan"].group_by else [state["plan"].group_by, "metric_value"])
        render_columns = _build_render_columns(state["plan"], columns)
        unit, unit_note = _unit_metadata(state["plan"], rows)
        return {
            "rows": rows,
            "columns": [column for column in columns if column],
            "render_columns": render_columns,
            "unit": unit,
            "unit_note": unit_note,
            "row_count": len(rows),
            "truncated": truncated,
            "render": {
                "type": "table",
                "title": f"{DATASET_LABELS.get(state['plan'].dataset, state['plan'].dataset)}查询结果",
                "empty_text": "没有符合条件的数据",
                "columns": render_columns,
                "unit": unit,
                "unit_note": unit_note,
            },
            "stages": [*state.get("stages", []), "execution"],
        }

    graph = StateGraph(Text2SQLState)
    graph.add_node("query_understanding", understand)
    graph.add_node("slot_filling", validate_plan_node)
    graph.add_node("query_planning", generate_sql)
    graph.add_node("sql_validation", validate_sql_node)
    graph.add_node("execution", execute)
    graph.add_edge(START, "query_understanding")
    graph.add_edge("query_understanding", "slot_filling")
    graph.add_edge("slot_filling", "query_planning")
    graph.add_edge("query_planning", "sql_validation")
    graph.add_edge("sql_validation", "execution")
    graph.add_edge("execution", END)
    app = graph.compile(checkpointer=MemorySaver())
    state = await app.ainvoke(
        {"question": request.question, "request_limit": request.limit, "stages": []},
        config={"configurable": {"thread_id": f"text2sql:{user.id}:{uuid4().hex}"}},
    )
    return Text2SQLResponse(
        question=request.question,
        plan=state["plan"],
        sql=state["sql"],
        parameterized_sql=state["parameterized_sql"],
        columns=state["columns"],
        slots=state["slots"],
        template=state["template"],
        render_columns=state["render_columns"],
        rows=state["rows"],
        row_count=state["row_count"],
        truncated=state["truncated"],
        stages=state["stages"],
        render=state["render"],
        unit=state.get("unit"),
        unit_note=state.get("unit_note"),
    )
