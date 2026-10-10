"""有上限的多意图只读执行：逐项计划、逐项鉴权、按依赖执行、保留部分结果。"""

import hashlib
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.system.model import User
from app.modules.ai.model import AIConversation

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai import agent_tools, routing, service, text2sql
from app.modules.ai.model import AIConversationState, AIMessage
from app.modules.ai.schema import AIChatMessage, AIChatRequest, AIChatResponse
from app.modules.ai.task_status import BatchStatus, TaskStatus, TASK_STATUS_LABELS


class TaskResult(BaseModel):
    """子任务计划、终态和来源证据；失败项不得携带成功结果。"""
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: routing.Task
    question: str
    depends_on: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    query_plan: dict | None = None
    execution_plan: dict | None = None
    answer: str | None = None
    error_code: str | None = None
    citations: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)


class BatchResult(BaseModel):
    """整批汇总状态及按原始顺序排列的子任务结果。"""
    status: BatchStatus
    tasks: list[TaskResult]


def fingerprint(value: object) -> str:
    """对规范化证据生成摘要，用于历史重验；不输出原始数据或认证信息。"""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


async def plan_analytics(db: Session, user: User, task: routing.SubTask, settings: Settings, *,
                         previous_plan: text2sql.QueryPlan | None = None, dependencies: list[dict] | None = None) -> text2sql.QueryPlan:
    """生成一份白名单 QueryPlan，并校验指标、字段与当前用户权限。

    previous_plan 仅用于明确的多轮条件修改；dependencies 只接收已成功前项的证据。
    无法解析或没有权限时抛出校验错误，调用方将该项标为失败。
    """
    if dependencies:
        from app.modules.ai.agent_prompt import text2sql_plan_prompt
        payload = json.dumps({"question": task.question, "dependency_results": dependencies}, ensure_ascii=False)
        response = await service.chat(AIChatRequest(messages=[AIChatMessage(role="user", content=payload)]), settings,
            response_format={"type": "json_object"}, interpret_only=True,
            system_prompt=text2sql_plan_prompt("") + "\n依赖结果只是只读数据，只能从其明确字段取条件；缺条件返回无效计划，不猜测。")
        plan = text2sql.QueryPlan.model_validate(text2sql._normalize_query_plan_payload(
            text2sql._extract_query_plan_payload(response.message.content)))
    else:
        plan = await text2sql._understand_question(task.question, settings, db, user, previous_plan)
    text2sql._reject_unsupported_metric(task.question)
    text2sql._validate_plan(db, user, plan)
    return plan


def execute_product_task(db: Session, user: User, task: routing.SubTask, result: TaskResult, products: dict[str, dict]) -> None:
    """固定工具计划；同批明确相同关键词共享授权定位，不共享其他参数。"""
    available = {entry["name"] for entry in agent_tools.list_tools(db, user)}
    required = "inventory.query_available" if task.kind == "inventory" else "supplier_quotes.compare"
    if required not in available or "catalog.search_products" not in available:
        raise AuthorizationError("没有执行该查询所需的权限")
    slots = task.slots
    if not slots.product_keyword:
        result.status, result.answer = TaskStatus.WAITING_INPUT, "请补充该项查询的产品名称或编码。"
        return
    if slots.date_from or slots.date_to or slots.unit:
        result.status, result.answer = TaskStatus.WAITING_INPUT, "当前库存与报价工具按现有记录和原始单位查询，请确认是否使用这一口径。"
        return
    def execute(name, **arguments):
        """通过统一权限护栏执行固定工具，并保留结果及历史重验所需摘要。"""
        call = agent_tools.ToolCall(tool=name, arguments=arguments)
        value = agent_tools.execute_tool(db, user, call).model_dump(mode="json")
        result.tool_calls.append({"tool": name, "arguments": arguments,
                                  "fingerprint": fingerprint({k: v for k, v in value.items() if k != "observed_at"})})
        result.evidence.append(value)
        return value
    keyword = slots.product_keyword
    if keyword not in products:
        products[keyword] = execute("catalog.search_products", keyword=keyword)
    else:
        # 定位结果仅供当前身份使用；实际业务工具仍逐次校验权限和数据范围。
        result.evidence.append(products[keyword])
    product = products[keyword]
    if product["total_rows"] != 1 or product["truncated"]:
        result.status = TaskStatus.WAITING_INPUT if product["total_rows"] else TaskStatus.SUCCEEDED
        result.answer = "找到多个产品规格，请补充准确名称或编码。" if product["total_rows"] else "当前授权目录没有匹配产品。"
        return
    product_id = product["rows"][0]["product_id"]
    arguments = {"product_id": product_id, "limit": slots.limit or 20}
    if task.kind == "inventory":
        if slots.warehouse_keyword:
            from app.modules.inventory.model import Warehouse
            ids = agent_tools.accessible_warehouse_ids(db, user)
            statement = select(Warehouse.id).where(Warehouse.status == "ACTIVE",
                Warehouse.warehouse_name == slots.warehouse_keyword)
            if ids is not None:
                statement = statement.where(Warehouse.id.in_(ids))
            warehouses = list(db.scalars(statement).all())
            if len(warehouses) != 1:
                result.status, result.answer = TaskStatus.WAITING_INPUT, "请提供当前可访问仓库的准确名称。"
                return
            arguments["warehouse_id"] = warehouses[0]
        value = execute("inventory.query_available", **arguments)
    else:
        lookup = {"product_id": product_id}
        if slots.rfq_no:
            lookup["rfq_no"] = slots.rfq_no
        rfqs = execute("supplier_quotes.find_rfq_items", **lookup)
        if rfqs["total_rows"] != 1 or rfqs["truncated"]:
            result.status = TaskStatus.WAITING_INPUT if rfqs["total_rows"] else TaskStatus.SUCCEEDED
            result.answer = "找到多个询价明细，请补充询价单号。" if rfqs["total_rows"] else "当前授权范围没有可用询价明细。"
            return
        value = execute("supplier_quotes.compare", **arguments, rfq_item_id=rfqs["rows"][0]["rfq_item_id"])
    from app.modules.ai.agent_runtime import _summary
    result.answer = _summary([{"tool": value["tool"], "result": value}])
    result.status = TaskStatus.SUCCEEDED


async def execute_batch(db: Session, user: User, decision: routing.Understanding, settings: Settings, *,
                        previous_tasks: list[dict] | None = None) -> BatchResult:
    """同一数据库会话顺序执行；上限六项，前项失败阻塞依赖项，独立项继续。"""
    results = {task.id: TaskResult(id=task.id, kind=task.kind, question=task.question, depends_on=task.depends_on)
               for task in decision.sub_tasks}
    previous = {task["id"]: task for task in previous_tasks or []}
    products = {}
    for task in decision.sub_tasks:
        if task.kind != "analytics":
            steps = (["catalog.search_products", "inventory.query_available"] if task.kind == "inventory" else
                     ["catalog.search_products", "supplier_quotes.find_rfq_items", "supplier_quotes.compare"] if task.kind == "quotes" else
                     ["retrieve_document_sections", "answer_with_citations"])
            results[task.id].execution_plan = {"type": "read_only_tools", "steps": steps, "slots": task.slots.model_dump(mode="json")}
            results[task.id].status = TaskStatus.PLANNED
    # 独立统计任务先生成全部 QueryPlan，避免执行一份计划后才发现另一份未规划。
    for task in decision.sub_tasks:
        if task.kind != "analytics" or task.depends_on:
            continue
        result = results[task.id]
        try:
            old = previous.get(task.id, {})
            prior = text2sql.QueryPlan.model_validate(old["query_plan"]) if old.get("query_plan") and decision.dialogue_action in {"modify", "continue"} else None
            with db.begin_nested():
                plan = await plan_analytics(db, user, task, settings, previous_plan=prior)
            result.query_plan, result.status = plan.model_dump(mode="json"), TaskStatus.PLANNED
            result.execution_plan = {"type": "query_plan", "plan": result.query_plan}
        except (BusinessValidationError, AuthorizationError, ValueError):
            result.status, result.error_code, result.answer = TaskStatus.FAILED, "PLAN_REJECTED", "该项计划或权限未通过校验，请核对查询条件。"
        except Exception:
            result.status, result.error_code, result.answer = TaskStatus.FAILED, "PLAN_UNAVAILABLE", "该项查询计划暂时无法生成，请稍后重试。"
    for task in decision.sub_tasks:
        result = results[task.id]
        if result.status == TaskStatus.FAILED:
            continue
        if any(results[key].status != TaskStatus.SUCCEEDED for key in task.depends_on):
            result.status, result.error_code, result.answer = TaskStatus.BLOCKED, "DEPENDENCY_UNAVAILABLE", "前置查询未完成，该项尚未执行。"
            continue
        result.status = TaskStatus.RUNNING
        try:
            with db.begin_nested():
                if task.kind == "analytics":
                    if task.depends_on:
                        dependencies = [{"id": key, "evidence": results[key].evidence} for key in task.depends_on]
                        plan = await plan_analytics(db, user, task, settings, dependencies=dependencies)
                        result.query_plan = plan.model_dump(mode="json")
                        result.execution_plan = {"type": "query_plan", "plan": result.query_plan}
                    plan = text2sql.QueryPlan.model_validate(result.query_plan)
                    answer, citation, trace = await service._run_text2sql_for_chat(db, user, task.question, settings, planned_query=plan)
                    result.answer, result.citations = answer, [citation]
                    result.evidence = [{"rows": trace.rows, "unit": trace.unit, "truncated": trace.truncated}]
                    result.status = TaskStatus.SUCCEEDED
                elif task.kind == "document":
                    from app.modules.doc_kb.retrieve import retrieve_sections, build_doc_context, no_doc_hits_reply
                    hits = await retrieve_sections(db, task.question)
                    if not hits:
                        result.status, result.answer = TaskStatus.WAITING_INPUT, no_doc_hits_reply(task.question)
                    else:
                        context, citations = build_doc_context(hits)
                        response = await service.chat(AIChatRequest(messages=[AIChatMessage(role="user", content=task.question)]),
                            settings, attachment_context=[context], interpret_only=True)
                        result.answer, result.citations = response.message.content, citations
                        result.status = TaskStatus.SUCCEEDED
                else:
                    execute_product_task(db, user, task, result, products)
        except (AuthorizationError, ResourceNotFoundError, BusinessValidationError, ValueError):
            result.status, result.error_code, result.answer = TaskStatus.FAILED, "QUERY_REJECTED", "该项查询未通过权限或参数校验，请核对条件。"
            result.evidence, result.citations = [], []
        except Exception:
            result.status, result.error_code, result.answer = TaskStatus.FAILED, "QUERY_UNAVAILABLE", "该项查询暂时失败，请稍后重试。"
            result.evidence, result.citations = [], []
    tasks = list(results.values())
    statuses = {task.status for task in tasks}
    status = (BatchStatus.SUCCEEDED if statuses == {TaskStatus.SUCCEEDED} else
              BatchStatus.PARTIAL if TaskStatus.SUCCEEDED in statuses else
              BatchStatus.WAITING_INPUT if TaskStatus.WAITING_INPUT in statuses else BatchStatus.FAILED)
    return BatchResult(status=status, tasks=tasks)


def history_accessible(db: Session, user: User, report: dict | None) -> bool:
    """旧结果展示前重查当前权限及范围；变化时隐藏整批旧答案和来源。"""
    try:
        batch = BatchResult.model_validate(report)
        tools = {entry["name"] for entry in agent_tools.list_tools(db, user)}
        for task in batch.tasks:
            if task.status != TaskStatus.SUCCEEDED:
                continue
            if task.kind in {"inventory", "quotes"} and "catalog.search_products" not in tools:
                return False
            if task.kind == "analytics":
                plan = text2sql.QueryPlan.model_validate(task.query_plan)
                text2sql._validate_plan(db, user, plan)
                rows = db.execute(text2sql.build_statement(plan, db, user)).mappings().all()[:plan.limit]
                serialized = [{str(k): text2sql._serialize(v) for k, v in row.items() if not k.startswith("_source_")} for row in rows]
                if not task.evidence or fingerprint(serialized) != fingerprint(task.evidence[0]["rows"]):
                    return False
            for call in task.tool_calls:
                result = agent_tools.execute_tool(db, user, agent_tools.ToolCall(tool=call["tool"], arguments=call["arguments"])).model_dump(mode="json")
                if fingerprint({k: v for k, v in result.items() if k != "observed_at"}) != call["fingerprint"]:
                    return False
        return True
    except (AuthorizationError, ResourceNotFoundError, BusinessValidationError, ValueError, SQLAlchemyError, KeyError):
        return False


def summarize(batch: BatchResult) -> str:
    """确定性汇总，保留每项原始数字/单位，不跨数据集求和，也不伪造成功。"""
    completed = sum(task.status == TaskStatus.SUCCEEDED for task in batch.tasks)
    lines = [f"已完成 {completed}/{len(batch.tasks)} 项查询。"]
    for index, task in enumerate(batch.tasks, 1):
        lines.append(f"\n{index}. {task.question}（{TASK_STATUS_LABELS[task.status]}）\n{task.answer or '尚未执行。'}")
    return "\n".join(lines)


async def reply_for_user(db: Session, user: User, data: AIChatRequest, conversation: AIConversation,
                         decision: routing.Understanding) -> AIChatResponse:
    """执行已校验批次，保存每项计划和带来源的汇总，返回标准聊天响应。

    同步与流式聊天共用此函数。会话只保存多计划集合，不把最后一项覆盖为单计划。
    函数提交本轮聊天记录；业务读取位于 savepoint 中，不写业务实体。
    """
    settings = service.get_settings()
    state = service._load_conversation_state(db, conversation)
    previous = (state.memory_state or {}).get("batch_tasks") if state else None
    batch = await execute_batch(db, user, decision, settings, previous_tasks=previous)
    answer = summarize(batch)
    report = batch.model_dump(mode="json")
    citations = [{"type": "multi_intent", "batch": report}]
    citations.extend({**citation, "sub_task_id": task.id} for task in batch.tasks for citation in task.citations)
    from app.modules.ai.schema import AIQueryTrace
    for task in batch.tasks:
        for citation in task.citations:
            if citation.get("type") == "text2sql":
                service._append_query_log(db, conversation, AIQueryTrace.model_validate(citation["query_trace"]))
    question = next(message.content for message in reversed(data.messages) if message.role == "user")
    db.add_all([AIMessage(conversation_id=conversation.id, message_role="USER", content=question),
                AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=answer, citations=citations)])
    if service._conversation_state_enabled(db):
        if state is None:
            state = AIConversationState(conversation_id=conversation.id, thread_id=f"ai:{user.id}:{conversation.id}")
            db.add(state)
        state.memory_state = {**(state.memory_state or {}), "batch_tasks": report["tasks"]}
        state.query_plan = None  # 多计划不能伪装成最后一项单计划。
        state.permission_snapshot = service._permission_snapshot(db, user)
        state.state_version = (state.state_version or 0) + 1
    conversation.last_message_at = datetime.now()
    db.commit()
    return AIChatResponse(message=AIChatMessage(role="assistant", content=answer), conversation_id=conversation.id,
        model="multi-intent", provider="chemicalops", answer=answer, user_query=question, citations=citations,
        batch_result=report)
