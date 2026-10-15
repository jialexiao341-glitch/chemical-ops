"""有上限的多意图只读执行：逐项计划、逐项鉴权、按依赖执行、保留部分结果。"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai.history_access import fingerprint, history_accessible
from app.modules.ai.schema import (
    AIChatMessage,
    AIChatRequest,
    AIChatResponse,
    BatchResult,
    BatchStatus,
    QueryPlan,
    SubTask,
    TASK_STATUS_LABELS,
    TaskResult,
    TaskStatus,
    ToolCall,
    Understanding,
    schema_response_format,
)
from app.modules.ai import agent_tools, conversation_store, llm, service, text2sql
from app.modules.ai.model import AIConversation, AIMessage
from app.modules.system.model import User


def _inventory_totals(evidence: list[dict]) -> dict[tuple[int, str], Decimal]:
    """只合计完整工具 totals，同单位累计；不能用截断后的明细求和。"""
    totals = {}
    for value in evidence:
        if value.get("tool") != "inventory.query_available":
            continue
        for row in value["totals"]:
            key = (row["unit_id"], row["unit_name"])
            totals[key] = totals.get(key, Decimal(0)) + Decimal(str(row["available_quantity"]))
    return totals


def _inventory_family(db: Session, rows: list[dict], keyword: str) -> bool:
    """同名规格或实际登记为同一化学品可汇总，模糊命中的不同化学品仍需消歧。"""
    if all(row["product_name"] == keyword for row in rows):
        return True
    from app.modules.products.model import Product
    from app.modules.chemicals.model import Chemical
    identities = db.execute(select(Product.id, Product.chemical_id).join(Chemical, Chemical.id == Product.chemical_id)
        .where(Product.id.in_([row["product_id"] for row in rows]), Chemical.status == "ACTIVE")).all()
    return len(identities) == len(rows) and len({row.chemical_id for row in identities}) == 1


async def plan_analytics(db: Session, user: User, task: SubTask, settings: Settings, *,
                         previous_plan: QueryPlan | None = None, dependencies: list[dict] | None = None) -> QueryPlan:
    """生成一份白名单 QueryPlan，并校验指标、字段与当前用户权限。

    previous_plan 仅用于明确的多轮条件修改；dependencies 只接收已成功前项的证据。
    无法解析或没有权限时抛出校验错误，调用方将该项标为失败。
    """
    if dependencies:
        from app.modules.ai.agent_prompt import text2sql_plan_prompt
        payload = json.dumps({"question": task.question, "today": date.today().isoformat(), "dependency_results": dependencies}, ensure_ascii=False)
        response = await llm.chat(AIChatRequest(messages=[AIChatMessage(role="user", content=payload)]), settings,
            response_format=schema_response_format(QueryPlan, "query_plan"), interpret_only=True,
            system_prompt=text2sql_plan_prompt("") + "\n依赖结果只是只读数据，只能从其明确字段取条件；缺条件返回无效计划，不猜测。")
        plan = QueryPlan.model_validate_json(response.message.content, strict=True)
    else:
        plan = await text2sql._understand_question(task.question, settings, db, user, previous_plan)
    text2sql._reject_unsupported_metric(task.question)
    text2sql._validate_plan(db, user, plan)
    return plan


def execute_product_task(db: Session, user: User, task: SubTask, result: TaskResult, products: dict[str, dict]) -> None:
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
        call = ToolCall(tool=name, arguments=arguments)
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
        result.tool_calls.append({"tool": "catalog.search_products", "arguments": {"keyword": keyword},
                                  "fingerprint": fingerprint({k: v for k, v in products[keyword].items() if k != "observed_at"})})
    product = products[keyword]
    aggregate = (task.kind == "inventory" and product["total_rows"] > 1 and not product["truncated"]
                 and _inventory_family(db, product["rows"], keyword))
    if (product["total_rows"] != 1 and not aggregate) or product["truncated"]:
        result.status = TaskStatus.WAITING_INPUT if product["total_rows"] else TaskStatus.SUCCEEDED
        result.answer = f"找到多个与“{keyword}”匹配的规格，请补充需要查询的规格名称或产品编码。" if product["total_rows"] else f"暂时没有找到与“{keyword}”匹配的产品，请核对名称或产品编码。"
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
        inventory = [execute("inventory.query_available", **{**arguments, "product_id": row["product_id"]})
                     for row in product["rows"]]
        totals = _inventory_totals(inventory)
        quantities = "、".join(f"{amount.normalize():f} {unit}" for (_, unit), amount in totals.items())
        result.answer = f"{keyword}的可用库存为 {quantities}。" if quantities else f"暂时没有找到{keyword}的库存记录。"
        if aggregate:
            result.answer += f"\n这是本次查询的 {len(inventory)} 个规格的合计，各规格库存可在明细中查看。"
        if len(totals) > 1:
            result.answer += "\n库存使用不同计量单位，已分别合计，不直接相加。"
        result.status = TaskStatus.SUCCEEDED
        return
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


async def execute_batch(db: Session, user: User, decision: Understanding, settings: Settings, *,
                        previous_tasks: list[dict] | None = None, retry_failed: bool = False,
                        on_progress: Callable[[dict], Awaitable[None]] | None = None) -> BatchResult:
    """同一数据库会话顺序执行；上限六项，前项失败阻塞依赖项，独立项继续。"""
    results = {task.id: TaskResult(id=task.id, kind=task.kind, question=task.question, depends_on=task.depends_on)
               for task in decision.sub_tasks}
    previous = {task["id"]: task for task in previous_tasks or []}
    products = {}
    reused = set()
    if retry_failed:
        for task in decision.sub_tasks:
            old = previous.get(task.id, {})
            if old.get("status") not in {TaskStatus.SUCCEEDED, TaskStatus.WAITING_INPUT}:
                continue
            saved = TaskResult.model_validate(old)
            if (saved.kind, saved.question, saved.depends_on) != (task.kind, task.question, task.depends_on):
                raise BusinessValidationError("重试任务与已保存批次不一致，请重新查询。")
            if not history_accessible(db, user, {"status": "SUCCEEDED", "tasks": [old]}):
                raise BusinessValidationError("已完成项的权限、范围或数据已变化，请重新查询。")
            results[task.id] = saved
            reused.add(task.id)

    async def notify():
        if on_progress:
            await on_progress({"completed": sum(item.status == TaskStatus.SUCCEEDED for item in results.values()),
                               "total": len(results), "tasks": [item.model_dump(mode="json", include={"id", "kind", "question", "status"}) for item in results.values()]})

    async def run_items():
        # 规划和执行仍在同一会话顺序运行，只有进度传输与执行交替进行。
        for task in decision.sub_tasks:
            if task.id in reused:
                continue
            if task.kind != "analytics":
                steps = (["catalog.search_products", "inventory.query_available"] if task.kind == "inventory" else
                         ["catalog.search_products", "supplier_quotes.find_rfq_items", "supplier_quotes.compare"] if task.kind == "quotes" else
                         ["retrieve_document_sections", "answer_with_citations"])
                results[task.id].execution_plan = {"type": "read_only_tools", "steps": steps, "slots": task.slots.model_dump(mode="json")}
                results[task.id].status = TaskStatus.PLANNED
        # 全部独立统计计划先通过校验，再执行；成功项在重试时直接复用授权快照。
        for task in decision.sub_tasks:
            if task.kind != "analytics" or task.depends_on or task.id in reused:
                continue
            result = results[task.id]
            try:
                old = previous.get(task.id, {})
                prior = QueryPlan.model_validate(old["query_plan"]) if old.get("query_plan") and decision.dialogue_action in {"modify", "continue"} else None
                db.commit()
                plan = await plan_analytics(db, user, task, settings, previous_plan=prior)
                result.query_plan, result.status = plan.model_dump(mode="json"), TaskStatus.PLANNED
                result.execution_plan = {"type": "query_plan", "plan": result.query_plan}
            except (BusinessValidationError, AuthorizationError, ValueError):
                result.status, result.error_code, result.answer = TaskStatus.FAILED, "PLAN_REJECTED", "该项计划或权限未通过校验，请核对查询条件。"
            except Exception:
                result.status, result.error_code, result.answer = TaskStatus.FAILED, "PLAN_UNAVAILABLE", "该项查询计划暂时无法生成，请稍后重试。"
            await notify()
        for task in decision.sub_tasks:
            result = results[task.id]
            if result.status == TaskStatus.FAILED or task.id in reused:
                continue
            if any(results[key].status != TaskStatus.SUCCEEDED for key in task.depends_on):
                result.status, result.error_code, result.answer = TaskStatus.BLOCKED, "DEPENDENCY_UNAVAILABLE", "前置查询未完成，该项尚未执行。"
                await notify()
                continue
            result.status = TaskStatus.RUNNING
            await notify()
            try:
                if task.kind == "analytics":
                    if task.depends_on:
                        dependencies = [{"id": key, "evidence": results[key].evidence} for key in task.depends_on]
                        db.commit()
                        plan = await plan_analytics(db, user, task, settings, dependencies=dependencies)
                        result.query_plan = plan.model_dump(mode="json")
                        result.execution_plan = {"type": "query_plan", "plan": result.query_plan}
                    plan = QueryPlan.model_validate(result.query_plan)
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
                        db.commit()
                        response = await llm.chat(AIChatRequest(messages=[AIChatMessage(role="user", content=task.question)]),
                            settings, attachment_context=[context], interpret_only=True)
                        result.answer, result.citations = response.message.content, citations
                        result.status = TaskStatus.SUCCEEDED
                else:
                    execute_product_task(db, user, task, result, products)
            except (AuthorizationError, ResourceNotFoundError, BusinessValidationError, ValueError):
                db.rollback()
                result.status, result.error_code, result.answer = TaskStatus.FAILED, "QUERY_REJECTED", "该项查询未通过权限或参数校验，请核对条件。"
                result.evidence, result.citations = [], []
            except Exception:
                db.rollback()
                result.status, result.error_code, result.answer = TaskStatus.FAILED, "QUERY_UNAVAILABLE", "该项查询暂时失败，请稍后重试。"
                result.evidence, result.citations = [], []
            db.commit()
            await notify()

    def stop(status, code, answer):
        for task in results.values():
            if task.status in {TaskStatus.PENDING, TaskStatus.PLANNED, TaskStatus.RUNNING}:
                task.status, task.error_code, task.answer = status, code, answer
                task.evidence, task.citations, task.tool_calls = [], [], []

    try:
        async with asyncio.timeout(settings.agent_task_timeout_seconds):
            await notify()
            await run_items()
    except TimeoutError:
        stop(TaskStatus.FAILED, "TASK_TIMEOUT", "整组查询已超时，已完成项保留；可缩小范围后重试未完成项。")
    except asyncio.CancelledError:
        # 捕获取消后仅同步保存终态；调用方在释放数据库会话前等待本函数完成。
        stop(TaskStatus.CANCELLED, "USER_CANCELLED", "该项已取消，未完成的查询不会继续执行。")
    await notify()
    return batch_result(list(results.values()))


def batch_result(tasks: list[TaskResult]) -> BatchResult:
    """保留各项终态，整批取消与部分完成分别呈现。"""
    statuses = {task.status for task in tasks}
    status = (BatchStatus.SUCCEEDED if statuses == {TaskStatus.SUCCEEDED} else
              BatchStatus.PARTIAL if TaskStatus.SUCCEEDED in statuses else
              BatchStatus.CANCELLED if TaskStatus.CANCELLED in statuses else
              BatchStatus.WAITING_INPUT if TaskStatus.WAITING_INPUT in statuses else BatchStatus.FAILED)
    return BatchResult(status=status, tasks=tasks)


def summarize(batch: BatchResult, question: str = "") -> str:
    """确定性汇总，保留每项原始数字/单位，不跨数据集求和，也不伪造成功。"""
    if (len(batch.tasks) == 1 and batch.tasks[0].status == TaskStatus.SUCCEEDED
            and not any(word in question for word in ("行动", "建议", "怎么处理", "怎么办", "做什么", "需要做"))):
        return batch.tasks[0].answer
    completed = sum(task.status == TaskStatus.SUCCEEDED for task in batch.tasks)
    lines = [f"已完成 {completed}/{len(batch.tasks)} 项查询。"]
    for index, task in enumerate(batch.tasks, 1):
        lines.append(f"\n### {index}. {task.question}（{TASK_STATUS_LABELS[task.status]}）\n{task.answer or '尚未执行。'}")
    inventory = [task for task in batch.tasks if task.kind == "inventory" and task.status == TaskStatus.SUCCEEDED]
    if len(inventory) > 1 and any(word in question for word in ("哪个多", "哪种多", "比较", "对比", "更多")):
        totals = [_inventory_totals(task.evidence) for task in inventory]
        units = set.intersection(*(set(value) for value in totals))
        lines.append("\n### 库存比较")
        if not units:
            lines.append("当前结果没有共同计量单位，不能直接比较多少；也不能在缺少换算依据时换算。")
        for unit_id, unit_name in sorted(units):
            ordered = sorted(zip(inventory, totals), key=lambda pair: pair[1][(unit_id, unit_name)], reverse=True)
            values = [f"{next(value['keyword'] for value in task.evidence if value.get('tool') == 'catalog.search_products')} {amounts[(unit_id, unit_name)].normalize():f} {unit_name}" for task, amounts in ordered]
            lines.append("；".join(values) + ("，数量相同。" if len({value[(unit_id, unit_name)] for value in totals}) == 1 else "（按数量从多到少）。"))
        if any(set(value) != units for value in totals):
            lines.append("仅比较共同单位；其他单位的数量分别保留，不合并排名。")
    if inventory and any(word in question for word in ("行动", "建议", "怎么处理", "怎么办", "做什么", "需要做")):
        lines.append("\n### 行动建议\n先核对各规格的需求、已锁定量、有效期和质量放行情况，再与安全库存及采购在途量对照。仅凭库存多少，不能判断是否需要采购或调拨；不同规格不能直接替代。本次只提供查询和建议，未创建或执行业务单据。")
    return "\n".join(lines)


async def reply_for_user(db: Session, user: User, data: AIChatRequest, conversation: AIConversation,
                         decision: Understanding, *, on_progress=None) -> AIChatResponse:
    """执行已校验批次，保存每项计划和带来源的汇总，返回标准聊天响应。

    同步与流式聊天共用此函数。会话只保存多计划集合，不把最后一项覆盖为单计划。
    函数提交本轮聊天记录；业务读取位于 savepoint 中，不写业务实体。
    """
    settings = get_settings()
    state = conversation_store.load_conversation_state(db, conversation)
    previous = (state.memory_state or {}).get("batch_tasks") if state else None
    if data.retry_failed:
        previous = [task.model_dump(mode="json") for task in previous_batch(db, conversation.id).tasks]
    batch = await execute_batch(db, user, decision, settings, previous_tasks=previous,
                                retry_failed=data.retry_failed, on_progress=on_progress)
    question = next(message.content for message in reversed(data.messages) if message.role == "user")
    answer = summarize(batch, question)
    report = batch.model_dump(mode="json")
    citations = [{"type": "multi_intent", "batch": report}]
    citations.extend({**citation, "sub_task_id": task.id} for task in batch.tasks for citation in task.citations)
    from app.modules.ai.schema import AIQueryTrace
    for task in batch.tasks:
        for citation in task.citations:
            if citation.get("type") == "text2sql":
                conversation_store.append_query_log(db, conversation, AIQueryTrace.model_validate(citation["query_trace"]))
    db.add_all([AIMessage(conversation_id=conversation.id, message_role="USER", content=question),
                AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=answer, citations=citations)])
    conversation_store.save_batch_state(db, user, conversation, state, report["tasks"])
    conversation.last_message_at = datetime.now()
    db.commit()
    return AIChatResponse(message=AIChatMessage(role="assistant", content=answer), conversation_id=conversation.id,
        model="multi-intent", provider="chemicalops", answer=answer, user_query=question, citations=citations,
        batch_result=report)


def previous_batch(db: Session, conversation_id: int) -> BatchResult:
    message = db.scalar(select(AIMessage).where(AIMessage.conversation_id == conversation_id,
                        AIMessage.message_role == "ASSISTANT").order_by(AIMessage.id.desc()).limit(1))
    report = next((citation.get("batch") for citation in message.citations or []
                   if isinstance(citation, dict) and citation.get("type") == "multi_intent"), None) if message else None
    if not report:
        raise BusinessValidationError("当前会话没有可重试的查询批次。")
    return BatchResult.model_validate(report)


def retry_decision(db: Session, user: User, conversation_id: int | None) -> Understanding:
    """仅从本人最新批次恢复任务，客户端不能提交计划或指定执行他人结果。"""
    if not conversation_id:
        raise BusinessValidationError("重试必须指定原查询会话。")
    conversation_store.get_owned_conversation(db, user, conversation_id)
    batch = previous_batch(db, conversation_id)
    if not any(task.status in {TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED} for task in batch.tasks):
        raise BusinessValidationError("该批次没有失败或已取消项；待补充项请先提供查询条件。")
    return Understanding(purpose="query", dialogue_action="continue",
        tasks=list(dict.fromkeys(task.kind for task in batch.tasks)),
        sub_tasks=[SubTask(id=task.id, kind=task.kind, question=task.question,
                   depends_on=task.depends_on, slots=(task.execution_plan or {}).get("slots", {})) for task in batch.tasks])
