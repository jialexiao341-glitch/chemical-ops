"""历史业务证据在展示或送入模型之前按当前身份重新核验。"""

from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai.schema import (
    QueryPlan,
)


def query_accessible(db, user, citation: dict) -> bool:
    """重跑固定只读查询，比较明细、截断状态和来源；不调用模型。"""
    from app.modules.ai import text2sql
    from app.modules.ai.multi_intent import fingerprint

    try:
        if citation.get("type") == "order_trace":
            from app.modules.ai.order_trace import trace_purchase_order
            return fingerprint(trace_purchase_order(db, user, citation["po_no"])) == fingerprint(citation["order_trace"])
        plan = QueryPlan.model_validate(citation["query_plan"])
        text2sql._validate_plan(db, user, plan)
        fetched = db.execute(text2sql.build_statement(plan, db, user)).mappings().all()
        raw = [{str(k): text2sql._serialize(v) for k, v in row.items()} for row in fetched[:plan.limit]]
        rows = [{k: v for k, v in row.items() if not k.startswith("_source_")} for row in raw]
        trace = citation["query_trace"]
        return (fingerprint(rows) == fingerprint(trace["rows"])
                and (len(fetched) > plan.limit) == trace["truncated"]
                and fingerprint(text2sql._source_records(plan.dataset, raw)) == fingerprint(citation["source_records"]))
    except (AuthorizationError, BusinessValidationError, ResourceNotFoundError, SQLAlchemyError, ValueError, KeyError, TypeError):
        return False


def visible_message(db, user, message) -> tuple[str, list | None]:
    """统一历史页面和理解模型的可见内容，拒绝时同时移除全部来源。"""
    from app.modules.ai import agent_runtime, multi_intent

    def unavailable(text):
        # 旧版本也把业务引用保存到了用户消息；保留原问题但不能返回失效的证据。
        return (text if message.message_role == "ASSISTANT" else message.content), []

    for citation in message.citations or []:
        if not isinstance(citation, dict):
            continue
        kind = citation.get("type")
        if kind == "multi_intent":
            if not multi_intent.history_accessible(db, user, citation.get("batch")):
                return unavailable("这组查询的权限、范围或数据已变化，请重新查询。")
        elif kind in {"text2sql", "order_trace"}:
            if not query_accessible(db, user, citation):
                return unavailable("该查询的权限、范围或数据已变化，请重新查询。")
        elif kind == "agent_task":
            try:
                agent_runtime.get_task(db, user, citation["task_id"])
            except (AuthorizationError, ResourceNotFoundError, BusinessValidationError, KeyError):
                return unavailable("任务结果当前不可访问，请核对权限或服务状态。")
    return message.content, message.citations
