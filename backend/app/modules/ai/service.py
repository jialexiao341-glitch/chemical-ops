"""AI 助手调用服务。"""

import asyncio
import base64
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.modules.ai import conversation_store
from app.core.config import Settings, get_settings
from app.core.errors import BusinessValidationError
from app.core.observability import get_request_id
from app.modules.ai.schema import (
    AIChatMessage,
    AIChatRequest,
    AIChatResponse,
    AIQueryTrace,
    Intent,
    IntentResult,
    Understanding,
)
from app.modules.ai.agent_prompt import (
    UNSUPPORTED_REPLY,
    build_project_reply,
    fallback_guidance_prompt,
    greeting_reply,
    result_rewrite_prompt,
)
from app.modules.ai.llm import chat, stream_chat
from app.modules.ai.gateway import bind_user, reset_user
from app.modules.files import service as file_service
from app.modules.files import mineru
from app.modules.files.parser import parse_file_content
from app.modules.files.scanner import scan_content
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import User


LOGGER = logging.getLogger("chemicalops.ai")
STREAM_CHUNK_SIZE = 4
STREAM_CHUNK_DELAY_SECONDS = 0.03
MAX_ATTACHMENT_CONTEXT_CHARS = 48_000
MAX_ATTACHMENT_IMAGE_BYTES = 8 * 1024 * 1024


async def _stream_text_chunks(content: str) -> AsyncIterator[str]:
    """把已经生成的安全文本分成小段输出，避免前端一次性出现整段内容。"""

    for index in range(0, len(content), STREAM_CHUNK_SIZE):
        yield content[index : index + STREAM_CHUNK_SIZE]
        await asyncio.sleep(STREAM_CHUNK_DELAY_SECONDS)


def _text_fingerprint(value: str) -> str:
    """日志只保留不可逆摘要，避免记录问题、答案或附件正文。"""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _query_log_fields(user: User, query: str) -> dict[str, object]:
    return {
        "request_id": get_request_id(),
        "user_id": user.id,
        "query_length": len(query),
        "query_hash": _text_fingerprint(query),
    }


async def _classify_chat_intent(db: Session, question: str, *, user: User, data: AIChatRequest) -> IntentResult:
    """聊天与 Agent 使用同一语义结果；客户端只能复用后端签发的短期结果。"""
    from app.modules.ai import routing
    if data.retry_failed:
        if data.attachments or data.attachment_file_ids:
            raise BusinessValidationError("重试使用原查询条件；修改附件或条件请重新发起查询。")
        from app.modules.ai.multi_intent import retry_decision
        decision = retry_decision(db, user, data.conversation_id)
        return IntentResult(Intent.MULTI, "retry_failed", decision.model_dump(mode="json"))
    if data.route_token:
        decision = routing.read_ticket(data.route_token, user.id, question, data.conversation_id)
    else:
        context = routing.conversation_context(db, user, data.conversation_id)
        # Context and authorization checks are complete; release the read transaction
        # before waiting for the routing model.
        db.commit()
        decision = await routing.understand(question, context)
    route = decision.route
    if route == "batch":
        return IntentResult(Intent.MULTI, "semantic_route", decision.model_dump(mode="json"))
    if route == "agent":
        # 普通聊天 API 不静默把 Agent 任务降级为另一种查询。
        return IntentResult(Intent.CLARIFY, "请使用只读查询任务入口继续该库存或报价查询。")
    if route in {"clarify", "cancel"}:
        return IntentResult(Intent.CLARIFY, "已取消本次请求。" if route == "cancel" else
                            decision.question or "这次请求包含不同处理流程，请先选择要查询的业务数据或化学品资料。")
    return IntentResult({"capability": Intent.PROJECT, "greeting": Intent.GREETING,
                         "guidance": Intent.GUIDANCE, "document": Intent.DOC,
                         "query": Intent.QUERY}.get(route, Intent.UNSUPPORTED), "semantic_route", decision.model_dump(mode="json"))


def _resolved_query_question(question: str, intent: IntentResult) -> str:
    """单项续问使用理解器已还原的对象和条件，不能把“第二项”再交给无历史的规划器。"""
    from app.modules.ai.routing import Understanding

    if intent.understanding:
        decision = Understanding.model_validate(intent.understanding)
        if len(decision.sub_tasks) == 1:
            return decision.sub_tasks[0].question
    return question


def _build_native_image_part(file_name: str, mime_type: str, content: bytes) -> dict[str, object] | None:
    """为 DeepSeek Flash 组装原生视觉图片块；文档格式仍由解析器处理。"""

    extension = Path(file_name).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg"}:
        return None
    normalised_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalised_mime not in {"image/png", "image/jpeg"}:
        normalised_mime = "image/png" if extension == ".png" else "image/jpeg"
    encoded = base64.b64encode(content).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{normalised_mime};base64,{encoded}"}}


async def _prepare_attachments(
    db: Session,
    user: User,
    data: AIChatRequest,
    runtime: Settings,
) -> tuple[list[str], list[dict[str, object]], list[dict[str, object]]]:
    """读取当前用户可访问的附件，并生成稳定、受限的上下文和引用。"""

    attachment_context: list[str] = []
    native_image_parts: list[dict[str, object]] = []
    citations: list[dict[str, object]] = []
    context_chars = 0
    role_codes = set(get_user_role_codes(db, user.id))

    for file_id in dict.fromkeys(data.attachment_file_ids):
        value = file_service.get_file(db, user, file_id)
        if value.uploader_id != user.id and "SYS_ADMIN" not in role_codes:
            raise BusinessValidationError("只能将自己上传的文件提交给 AI 分析")
        try:
            _, content = file_service.read_file(db, user, file_id)
            scan_result = scan_content(content, settings=runtime)
            if runtime.file_scan_enabled and scan_result.status != "CLEAN":
                value.parse_status = "FAILED"
                value.parse_error = "附件未通过当前安全扫描，AI 不会读取其内容"
                citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": "SCAN_BLOCKED", "parser": "clamav", "references": [], "error": scan_result.detail or value.parse_error, "context_included": False})
                continue
            extension = Path(value.file_name).suffix.lower()
            native_image = _build_native_image_part(value.file_name, value.mime_type, content) if runtime.llm_model.lower() == "deepseek-flash" else None
            if native_image is not None:
                if len(content) > MAX_ATTACHMENT_IMAGE_BYTES:
                    value.parse_status = "TOO_LARGE"
                    value.parse_error = "图片超过 AI 单次视觉分析上限"
                    citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": "TOO_LARGE", "parser": "native-vision", "references": [], "error": value.parse_error})
                else:
                    native_image_parts.append(native_image)
                    value.parse_status = "SUCCEEDED"
                    value.parse_error = None
                    citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": "SUCCEEDED", "parser": "native-vision", "references": []})
                continue

            remote_error: str | None = None
            if runtime.mineru_enabled and extension in mineru.SUPPORTED_REMOTE_EXTENSIONS:
                value.parse_status = "PROCESSING"
                value.parse_error = None
                db.flush()
                db.commit()
                try:
                    parsed = await asyncio.to_thread(mineru.parse_bytes, value.file_name, content, runtime)
                except mineru.MinerUParseError as exc:
                    remote_error = str(exc)
                    LOGGER.warning("MinerU 附件解析失败，回退本地解析 file_id=%s error_type=%s", file_id, exc.__class__.__name__)
                    parsed = parse_file_content(value.file_name, value.mime_type, content)
            else:
                parsed = parse_file_content(value.file_name, value.mime_type, content)

            value.parse_status = parsed.status
            value.parse_error = parsed.error or remote_error
            citation: dict[str, object] = {
                "file_id": value.id,
                "file_name": value.file_name,
                "source": "用户上传附件",
                "parse_status": parsed.status,
                "parser": parsed.parser,
                "references": parsed.references,
            }
            if remote_error:
                citation["remote_error"] = remote_error
            if parsed.error:
                citation["error"] = parsed.error
            citations.append(citation)

            text = parsed.text or parsed.error or "文件没有可解析正文，请不要猜测其内容。"
            remaining = MAX_ATTACHMENT_CONTEXT_CHARS - context_chars
            if remaining <= 0:
                citations[-1]["context_included"] = False
                continue
            clipped = text[:remaining]
            if len(clipped) < len(text):
                clipped += "\n[附件上下文已达到本次查询上限，未继续读取。]"
                citations[-1]["context_truncated"] = True
            attachment_context.append(f"附件：{value.file_name}\n{clipped}")
            context_chars += len(clipped)
            citations[-1]["context_included"] = True
            if parsed.text:
                try:
                    result_key = file_service.store_parse_result(value.id, parsed.text)
                    if result_key:
                        citations.append({"type": "parsed_result", "file_id": value.id, "object_key": result_key, "source": "解析结果 Markdown"})
                except Exception as exc:
                    LOGGER.warning("解析结果保存失败 file_id=%s error_type=%s", value.id, exc.__class__.__name__)
        except Exception as exc:
            LOGGER.warning("AI 附件读取失败 file_id=%s error_type=%s", file_id, exc.__class__.__name__)
            value.parse_status = "FAILED"
            value.parse_error = "文件解析失败，请检查文件格式或重新上传"
            citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": "FAILED", "parser": "none", "references": [], "error": value.parse_error, "context_included": True})
            attachment_context.append(f"附件：{value.file_name}\n{value.parse_error}，请不要基于该附件推断业务结论。")

    return attachment_context, native_image_parts, citations


def _format_text2sql_result(result: object) -> str:
    """AI 重组不可用时的自然语言兜底；只使用已经清洗过的查询结果。"""

    rows = getattr(result, "rows", [])
    plan = getattr(result, "plan", None)
    render_columns = getattr(result, "render_columns", [])
    labels = {item.get("key"): item.get("label", item.get("key")) for item in render_columns if isinstance(item, dict)}
    unit = {"CNY": "元（CNY）", "USD": "美元（USD）", "EUR": "欧元（EUR）", "条": "条"}.get(getattr(result, "unit", None) or "", getattr(result, "unit", None) or "")
    if not rows:
        return "暂时没有找到符合条件的记录。"
    lines = [f"找到了 {len(rows)} 条符合条件的记录。"]
    for index, row in enumerate(rows, start=1):
        values = "；".join(
            f"{labels.get(key, key)}：{value}{(' ' + unit) if key == 'metric_value' and unit and unit != '条' else ''}"
            for key, value in row.items()
        )
        lines.append(f"{index}. {values}")
    if plan is not None and getattr(plan, "limit", None) and getattr(result, "truncated", False):
        lines.append("当前仅展示部分结果。")
    return "\n".join(lines)


async def _rewrite_text2sql_answer(result: object, dataset_label: str, settings: Settings) -> str | None:
    """把查询结果交给模型重写成结论先行的自然中文。

    任何失败（未启用、超时、格式错误）都返回 None，由 _format_text2sql_result 模板兜底，
    保证查询路径永远有答案。
    """

    try:
        payload = json.dumps(
            {
                "question": getattr(result, "question", ""),
                "dataset_label": dataset_label,
                "rows": list(getattr(result, "rows", []) or [])[:50],
                "render_columns": getattr(result, "render_columns", []),
                "unit": getattr(result, "unit", None),
                "unit_note": getattr(result, "unit_note", None),
                "row_count": getattr(result, "row_count", 0),
                "truncated": bool(getattr(result, "truncated", False)),
            },
            ensure_ascii=False,
            default=str,
        )
        rewritten = await chat(
            AIChatRequest(messages=[AIChatMessage(role="user", content=payload)]),
            settings,
            response_format={"type": "json_object"},
            system_prompt=result_rewrite_prompt(""), interpret_only=True,
        )
        raw = (rewritten.answer or rewritten.message.content or "").strip()
        if not raw:
            return None
        from app.modules.ai.llm import extract_json_object

        parsed = extract_json_object(raw)
        answer = parsed.get("answer")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
        return None
    except Exception as exc:  # 重写失败不能影响查询主链路
        LOGGER.warning("AI 答案重写失败，使用模板兜底 error_type=%s", type(exc).__name__)
        return None


async def _compose_non_query_reply(
    intent: Intent, reason: str, question: str, settings: Settings | None = None
) -> tuple[str, str]:
    """非查询意图的回复组装，返回 (内容, model 标签)。

    - PROJECT / GREETING / 明确的范围外问题：确定性文案，不调用模型；
    - 未命中任何规则的疑问（no_supported_marker）：交给模型做范围判断与改问引导，
      失败时退回固定文案，保证永远有回复。
    """

    if intent is Intent.CLARIFY:
        return reason, "semantic-router"
    if intent is Intent.GUIDANCE:
        response = await chat(AIChatRequest(messages=[AIChatMessage(role="user", content=question)]), settings,
                              system_prompt="""# 任务
回答 ChemicalOps 业务操作指导，不查询或执行真实业务。
# 约束
不编造产品现有按钮、实际状态、单据、库存或价格。不确定系统是否支持时明确说明，必要时询问具体页面。
# 输出
简洁中文说明操作原则和所需信息；不得声称已经执行任何操作。""", interpret_only=True)
        return response.message.content, "guidance"
    if intent is Intent.PROJECT:
        return build_project_reply(question), "rule-based"
    if intent is Intent.GREETING:
        return greeting_reply(), "rule-based"
    # 空消息与明确的范围外话题保持固定拒绝，不浪费模型调用
    if reason != "no_supported_marker":
        return UNSUPPORTED_REPLY, "rule-based"
    try:
        runtime = settings or get_settings()
        guided = await chat(
            AIChatRequest(messages=[AIChatMessage(role="user", content=fallback_guidance_prompt(question))]),
            runtime,
        )
        content = (guided.answer or guided.message.content or "").strip()
        if content:
            return content, "guidance"
    except Exception as exc:
        LOGGER.warning("AI 引导回复失败，使用固定文案 error_type=%s", type(exc).__name__)
    return UNSUPPORTED_REPLY, "rule-based"


async def _run_text2sql_for_chat(
    db: Session,
    user: User,
    question: str,
    settings: Settings,
    *,
    previous_plan: object | None = None,
    thread_id: str | None = None,
    planned_query: object | None = None,
) -> tuple[str, dict[str, object], AIQueryTrace]:
    """聊天入口的业务查询路由；Text2SQL 结果不再经过通用聊天上下文。"""

    from app.modules.ai.order_trace import extract_order_trace_no, trace_purchase_order
    from app.modules.ai.text2sql import Text2SQLRequest, run_text2sql

    query_fields = _query_log_fields(user, question)
    LOGGER.info("AI 查询开始 %s", query_fields)
    order_no = extract_order_trace_no(question)
    if order_no and planned_query is None:
        result = trace_purchase_order(db, user, order_no)
        executed_at = datetime.now()
        rows = [
            {
                "stage": item["stage"],
                "status": item["status"],
                "summary": item["summary"],
                "records": item["records"],
                "truncated": item.get("truncated", False),
            }
            for item in result["stages"]
        ]
        trace = AIQueryTrace(
            query=question,
            answer=result["answer"],
            dataset="purchase_order_trace",
            dataset_label="采购订单跨模块追溯",
            permission="采购订单读取权限为入口；其余环节按各自读取权限独立核验",
            thread_id=thread_id,
            executed_at=executed_at,
            data_scope={"po_no": order_no, "module_permissions_applied": True},
            slots=[],
            template="fixed_purchase_order_trace_v1",
            sql="固定服务端只读 ORM 查询；逐环节按模块权限取数，未使用模型生成 SQL。",
            columns=[
                {"key": "stage", "label": "业务环节"},
                {"key": "status", "label": "可见状态"},
                {"key": "summary", "label": "说明"},
            ],
            rows=rows,
            row_count=len(rows),
            truncated=any(item.get("truncated", False) for item in result["stages"]),
            stages=["order_anchor", "module_permission_checks", "read_only_relation_queries"],
            render={"type": "table", "title": f"订单 {order_no} 追溯", "columns": ["stage", "status", "summary"]},
        )
        conversation_store.save_order_trace_state(db, user, thread_id, trace)
        citation: dict[str, object] = {
            "type": "order_trace",
            "source": "关联业务模块的只读追溯",
            "dataset": "purchase_order_trace",
            "dataset_label": "采购订单跨模块追溯",
            "permission": trace.permission,
            "executed_at": executed_at.isoformat(),
            "po_no": order_no,
            "source_records": result["source_records"],
            "order_trace": result,
            "query_trace": trace.model_dump(mode="json"),
        }
        LOGGER.info("AI 订单追溯完成 %s stage_count=%s", query_fields, len(rows))
        return result["answer"], citation, trace

    result = await run_text2sql(db, user, Text2SQLRequest(question=question, limit=getattr(planned_query, "limit", 20)), settings, previous_plan=previous_plan, thread_id=thread_id, planned_query=planned_query, intent_verified=True)
    from app.modules.ai.catalog import CATALOG

    executed_at = datetime.now()
    dataset_spec = CATALOG[result.plan.dataset]
    permission = dataset_spec.permission
    if result.plan.dataset == "weekly_order_risks":
        permission = "procurement.orders.read + warehouse.deliveries.read"
    elif result.plan.dataset == "accepted_orders_finance_gaps":
        permission = "procurement.orders.read + warehouse.deliveries.read + quality.acceptances.read + finance.reconciliations.read + finance.invoices.read + finance.payments.read + finance.settlements.read"
    elif result.plan.dataset == "supplier_quote_delivery_profile":
        permission = "master.suppliers.read + procurement.rfqs.read + procurement.orders.read + warehouse.deliveries.read + operations.exceptions.read"
    data_scope = {
        "date_from": result.plan.date_from.isoformat() if result.plan.date_from else None,
        "date_to": result.plan.date_to.isoformat() if result.plan.date_to else None,
        "filters": [item.model_dump(mode="json") for item in result.plan.filters],
    }
    context = None
    if previous_plan is not None:
        old_plan = previous_plan.model_dump(mode="json") if hasattr(previous_plan, "model_dump") else {}
        new_plan = result.plan.model_dump(mode="json")
        changed = [key for key in new_plan if old_plan.get(key) != new_plan.get(key)]
        context = {
            "continued": True,
            "inherited": [key for key in new_plan if key not in changed],
            "changed": changed,
        }
    trace = AIQueryTrace(
        query=result.question,
        slots=result.slots,
        dataset=result.plan.dataset,
        dataset_label=dataset_spec.label,
        permission=permission,
        thread_id=thread_id,
        executed_at=executed_at,
        data_scope=data_scope,
        context=context,
        template=result.template,
        sql=result.sql,
        parameterized_sql=result.parameterized_sql,
        columns=result.render_columns,
        rows=result.rows,
        unit=result.unit,
        unit_note=result.unit_note,
        row_count=result.row_count,
        truncated=result.truncated,
        stages=result.stages,
        render=result.render,
    )
    answer = _format_text2sql_result(result)
    # 先模板后重写：模型输出自然中文结论，失败时模板兜底，查询链路永不因重写而中断
    db.commit()
    rewritten = await _rewrite_text2sql_answer(result, dataset_spec.label, settings)
    if rewritten:
        answer = rewritten
    trace.answer = answer
    LOGGER.info("AI 查询槽位 user_id=%s slot_count=%s filled_count=%s", user.id, len(result.slots), sum(slot.get("status") == "filled" for slot in result.slots))
    LOGGER.info("AI 查询模板 user_id=%s template_hash=%s", user.id, _text_fingerprint(result.template))
    LOGGER.info("AI 生成 SQL user_id=%s sql_hash=%s", user.id, _text_fingerprint(result.sql))
    LOGGER.info(
        "AI 查询完成 user_id=%s row_count=%s truncated=%s unit=%s",
        user.id,
        result.row_count,
        result.truncated,
        result.unit or "未提供",
    )
    LOGGER.info("AI 回复答案 user_id=%s answer_length=%s answer_hash=%s", user.id, len(answer), _text_fingerprint(answer))
    citation = {
        "type": "text2sql",
        "source": "实时数据库只读查询",
        "dataset": result.plan.dataset,
        "dataset_label": dataset_spec.label,
        "permission": permission,
        "thread_id": thread_id,
        "executed_at": executed_at.isoformat(),
        "data_scope": data_scope,
        "query_plan": result.plan.model_dump(mode="json"),
        "row_count": result.row_count,
        "source_records": result.source_records,
        "stages": result.stages,
        "query_trace": trace.model_dump(mode="json"),
    }
    return answer, citation, trace


async def chat_for_user(db: Session, user: User, data: AIChatRequest) -> AIChatResponse:
    """绑定用户并运行同步 AI 用例，使嵌套 Gateway 请求共享并发配额。"""

    token = bind_user(user.id)
    try:
        return await _chat_for_user_impl(db, user, data)
    finally:
        reset_user(token)


async def _chat_for_user_impl(db: Session, user: User, data: AIChatRequest) -> AIChatResponse:
    """持久化用户消息并调用模型，再持久化助手回复。"""


    conversation = conversation_store.ensure_conversation(db, user, data)
    # Persist conversation metadata before any model, vector, or document-service wait.
    db.commit()
    user_message = next((message for message in reversed(data.messages) if message.role == "user"), None)
    if user_message is None:
        raise BusinessValidationError("至少需要一条用户消息")
    LOGGER.info("AI 请求进入 mode=sync user_id=%s query_length=%s", user.id, len(user_message.content))
    intent_result = await _classify_chat_intent(db, user_message.content, user=user, data=data)
    LOGGER.info("AI 意图识别 mode=sync user_id=%s intent=%s reason=%s", user.id, intent_result.intent, intent_result.reason)
    if intent_result.intent is Intent.MULTI and not data.attachment_file_ids:
        from app.modules.ai import routing, multi_intent
        return await multi_intent.reply_for_user(db, user, data, conversation,
                                                 Understanding.model_validate(intent_result.understanding))
    if intent_result.intent is Intent.DOC and not data.attachment_file_ids:
        from app.modules.doc_kb.retrieve import build_doc_context, no_doc_hits_reply, retrieve_sections

        hits = await retrieve_sections(db, user_message.content)
        if not hits:
            fixed_content = no_doc_hits_reply(user_message.content)
            LOGGER.info("AI 文档检索为空 user_id=%s question_hash=%s", user.id, _text_fingerprint(user_message.content))
            conversation_store.save_chat_turn(db, conversation, user_message.content, fixed_content)
            return AIChatResponse(
                message=AIChatMessage(role="assistant", content=fixed_content),
                conversation_id=conversation.id,
                model="rule-based",
                provider="chemicalops",
                citations=None,
                user_query=user_message.content,
                answer=fixed_content,
            )
        context, citations = build_doc_context(hits)
        runtime = get_settings()
        db.commit()
        result = await chat(data, runtime, attachment_context=[context])
        conversation_store.save_chat_turn(db, conversation, user_message.content, result.message.content, citations=citations)
        result.conversation_id = conversation.id
        result.citations = citations
        result.user_query = user_message.content
        result.answer = result.message.content
        LOGGER.info(
            "AI 文档问答完成 user_id=%s hits=%s answer_length=%s",
            user.id,
            len(hits),
            len(result.message.content),
        )
        return result
    if intent_result.intent is Intent.QUERY and not data.attachment_file_ids:
        runtime = get_settings()
        previous_plan = conversation_store.previous_query_plan(db, conversation)
        thread_id = f"ai:{user.id}:{conversation.id}"
        content, citation, query_trace = await _run_text2sql_for_chat(
            db, user, _resolved_query_question(user_message.content, intent_result), runtime, previous_plan=previous_plan, thread_id=thread_id
        )
        citations = [citation]
        from app.modules.ai.text2sql import QueryPlan

        plan_payload = citation.get("query_plan") if isinstance(citation, dict) else None
        if isinstance(plan_payload, dict):
            conversation_store.save_query_state(db, user, conversation, plan=QueryPlan.model_validate(plan_payload), trace=query_trace, citations=citations)
        conversation_store.append_query_log(db, conversation, query_trace)
        conversation_store.save_chat_turn(db, conversation, user_message.content, content, citations=citations)
        return AIChatResponse(
            message=AIChatMessage(role="assistant", content=content),
            conversation_id=conversation.id,
            model="text2sql",
            provider="chemicalops",
            citations=citations,
            query_trace=query_trace,
            query_slots=query_trace.slots,
            user_query=user_message.content,
            answer=content,
        )
    if intent_result.intent != Intent.QUERY and not data.attachment_file_ids:
        fixed_content, model_tag = await _compose_non_query_reply(
            intent_result.intent, intent_result.reason, user_message.content
        )
        LOGGER.info("AI 非查询回复 user_id=%s intent=%s reason=%s model=%s answer_length=%s", user.id, intent_result.intent, intent_result.reason, model_tag, len(fixed_content))
        conversation_store.save_chat_turn(db, conversation, user_message.content, fixed_content)
        return AIChatResponse(message=AIChatMessage(role="assistant", content=fixed_content), conversation_id=conversation.id, model=model_tag, provider="chemicalops", citations=None, user_query=user_message.content, answer=fixed_content)

    runtime = get_settings()
    combined_context, native_image_parts, combined_citations = await _prepare_attachments(db, user, data, runtime)
    conversation_store.append_message(db, conversation, "USER", user_message.content, citations=combined_citations or None)
    db.commit()
    result = await chat(data, runtime, attachment_context=combined_context or None, image_parts=native_image_parts or None)
    conversation_store.append_message(db, conversation, "ASSISTANT", result.message.content, citations=combined_citations or None)
    db.commit()
    result.conversation_id = conversation.id
    result.citations = combined_citations or None
    result.user_query = user_message.content
    result.answer = result.message.content
    return result


async def stream_chat_for_user(db: Session, user: User, data: AIChatRequest) -> AsyncIterator[str]:
    """绑定用户并转发 SSE；取消生成器时恢复调用方上下文。"""

    token = bind_user(user.id)
    stream = _stream_chat_for_user_impl(db, user, data)
    try:
        async for event in stream:
            yield event
    finally:
        try:
            await stream.aclose()
        finally:
            reset_user(token)


async def _stream_chat_for_user_impl(db: Session, user: User, data: AIChatRequest) -> AsyncIterator[str]:
    """通过 SSE 转发 OpenAI 兼容接口的增量内容，并在结束时持久化。"""


    conversation = conversation_store.ensure_conversation(db, user, data)
    db.commit()
    user_message = next((message for message in reversed(data.messages) if message.role == "user"), None)
    if user_message is None:
        yield f"event: error\ndata: {json.dumps({'message': '至少需要一条用户消息'}, ensure_ascii=False)}\n\n"
        return
    LOGGER.info("AI 请求进入 mode=stream %s", _query_log_fields(user, user_message.content))
    try:
        stream_intent_result = await _classify_chat_intent(db, user_message.content, user=user, data=data)
    except BusinessValidationError as exc:
        yield "event: error\ndata: " + json.dumps({"message": str(exc)}, ensure_ascii=False) + "\n\n"
        return
    LOGGER.info("AI 意图识别 mode=stream user_id=%s intent=%s reason=%s", user.id, stream_intent_result.intent, stream_intent_result.reason)
    if stream_intent_result.intent is Intent.MULTI and not data.attachment_file_ids:
        from app.modules.ai import routing, multi_intent
        # 首次进度即暴露会话 ID；先保存会话，取消后的历史读取才能立即访问。
        db.commit()
        queue = asyncio.Queue()
        async def progress(snapshot):
            await queue.put({"conversation_id": conversation.id, **snapshot})
        execution = asyncio.create_task(multi_intent.reply_for_user(db, user, data, conversation,
                            Understanding.model_validate(stream_intent_result.understanding), on_progress=progress))
        receive = None
        try:
            while True:
                if not queue.empty():
                    yield "event: progress\ndata: " + json.dumps(queue.get_nowait(), ensure_ascii=False) + "\n\n"
                    continue
                if execution.done():
                    break
                receive = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({execution, receive}, return_when=asyncio.FIRST_COMPLETED)
                if receive in done:
                    yield "event: progress\ndata: " + json.dumps(receive.result(), ensure_ascii=False) + "\n\n"
                else:
                    receive.cancel()
                    await asyncio.gather(receive, return_exceptions=True)
                receive = None
            result = execution.result()
        except BusinessValidationError as exc:
            yield "event: error\ndata: " + json.dumps({"message": str(exc)}, ensure_ascii=False) + "\n\n"
            return
        finally:
            if receive is not None:
                receive.cancel()
            if not execution.done():
                execution.cancel()
            # 断开连接会取消执行；等待它保存部分结果和取消终态后再释放请求会话。
            await asyncio.shield(asyncio.gather(execution, return_exceptions=True))
        async for chunk in _stream_text_chunks(result.answer):
            yield "event: delta\ndata: " + json.dumps({"content": chunk}, ensure_ascii=False) + "\n\n"
        yield "event: done\ndata: " + json.dumps(result.model_dump(mode="json", exclude={"message"}), ensure_ascii=False) + "\n\n"
        return
    if stream_intent_result.intent is Intent.DOC and not data.attachment_file_ids:
        from app.modules.doc_kb.retrieve import build_doc_context, no_doc_hits_reply, retrieve_sections

        hits = await retrieve_sections(db, user_message.content)
        doc_citations: list | None = None
        doc_model = "rule-based"
        if hits:
            context, doc_citations = build_doc_context(hits)
            runtime = get_settings()
            try:
                db.commit()
                result = await chat(data, runtime, attachment_context=[context])
            except BusinessValidationError as exc:
                LOGGER.warning("AI 流式文档问答失败 user_id=%s error_type=%s", user.id, exc.__class__.__name__)
                yield f"event: error\ndata: {json.dumps({'message': str(exc)}, ensure_ascii=False)}\n\n"
                return
            except Exception:
                LOGGER.exception("AI 流式文档问答异常 user_id=%s", user.id)
                yield f"event: error\ndata: {json.dumps({'message': '文档问答暂时失败，请稍后重试'}, ensure_ascii=False)}\n\n"
                return
            doc_content = result.answer or result.message.content
            doc_model = result.model
            LOGGER.info("AI 流式文档问答完成 user_id=%s hits=%s answer_length=%s", user.id, len(hits), len(doc_content))
        else:
            doc_content = no_doc_hits_reply(user_message.content)
            LOGGER.info("AI 流式文档检索为空 user_id=%s", user.id)
        chunk_count = 0
        async for chunk in _stream_text_chunks(doc_content):
            chunk_count += 1
            yield "event: delta\ndata: " + json.dumps({"content": chunk}, ensure_ascii=False) + "\n\n"
        conversation_store.save_chat_turn(db, conversation, user_message.content, doc_content, citations=doc_citations)
        yield "event: done\ndata: " + json.dumps(
            {
                "conversation_id": conversation.id,
                "model": doc_model,
                "provider": "chemicalops",
                "citations": doc_citations,
                "user_query": user_message.content,
                "answer": doc_content,
            },
            ensure_ascii=False,
        ) + "\n\n"
        return
    if stream_intent_result.intent is Intent.QUERY and not data.attachment_file_ids:
        runtime = get_settings()
        previous_plan = conversation_store.previous_query_plan(db, conversation)
        thread_id = f"ai:{user.id}:{conversation.id}"
        try:
            content, citation, query_trace = await _run_text2sql_for_chat(
                db, user, _resolved_query_question(user_message.content, stream_intent_result), runtime, previous_plan=previous_plan, thread_id=thread_id
            )
        except BusinessValidationError as exc:
            LOGGER.warning("AI 流式查询业务失败 user_id=%s query_hash=%s error_type=%s", user.id, _text_fingerprint(user_message.content), exc.__class__.__name__)
            yield f"event: error\ndata: {json.dumps({'message': str(exc)}, ensure_ascii=False)}\n\n"
            return
        except Exception:
            LOGGER.exception("AI 流式查询异常 user_id=%s query_hash=%s", user.id, _text_fingerprint(user_message.content))
            yield f"event: error\ndata: {json.dumps({'message': f'查询暂时失败，请稍后重试'}, ensure_ascii=False)}\n\n"
            return
        citations = [citation]
        chunk_count = 0
        async for chunk in _stream_text_chunks(content):
            chunk_count += 1
            yield f"event: delta\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
        from app.modules.ai.text2sql import QueryPlan

        plan_payload = citation.get("query_plan") if isinstance(citation, dict) else None
        if isinstance(plan_payload, dict):
            conversation_store.save_query_state(db, user, conversation, plan=QueryPlan.model_validate(plan_payload), trace=query_trace, citations=citations)
        conversation_store.append_query_log(db, conversation, query_trace)
        conversation_store.save_chat_turn(db, conversation, user_message.content, content, citations=citations)
        LOGGER.info("AI 流式回复完成 user_id=%s mode=query chunks=%s", user.id, chunk_count)
        trace_payload = query_trace.model_dump(mode="json")
        yield f"event: done\ndata: {json.dumps({'conversation_id': conversation.id, 'model': 'text2sql', 'provider': 'chemicalops', 'citations': citations, 'query_trace': trace_payload, 'query_slots': trace_payload['slots'], 'user_query': user_message.content, 'answer': content}, ensure_ascii=False)}\n\n"
        return
    if stream_intent_result.intent != Intent.QUERY and not data.attachment_file_ids:
        fixed_content, model_tag = await _compose_non_query_reply(
            stream_intent_result.intent, stream_intent_result.reason, user_message.content
        )
        LOGGER.info("AI 流式非查询回复开始 user_id=%s intent=%s reason=%s model=%s query_hash=%s", user.id, stream_intent_result.intent, stream_intent_result.reason, model_tag, _text_fingerprint(user_message.content))
        chunk_count = 0
        async for chunk in _stream_text_chunks(fixed_content):
            chunk_count += 1
            yield "event: delta\ndata: " + json.dumps({"content": chunk}, ensure_ascii=False) + "\n\n"
        conversation_store.save_chat_turn(db, conversation, user_message.content, fixed_content)
        LOGGER.info("AI 流式回复完成 user_id=%s mode=%s chunks=%s answer_length=%s answer_hash=%s", user.id, model_tag, chunk_count, len(fixed_content), _text_fingerprint(fixed_content))
        yield "event: done\ndata: " + json.dumps({"conversation_id": conversation.id, "model": model_tag, "provider": "chemicalops", "citations": None, "user_query": user_message.content, "answer": fixed_content}, ensure_ascii=False) + "\n\n"
        return

    runtime = get_settings()
    try:
        combined_context, native_image_parts, citations = await _prepare_attachments(db, user, data, runtime)
    except BusinessValidationError as exc:
        yield f"event: error\ndata: {json.dumps({'message': str(exc)}, ensure_ascii=False)}\n\n"
        return
    except Exception:
        LOGGER.exception("AI 流式附件准备失败 user_id=%s", user.id)
        yield f"event: error\ndata: {json.dumps({'message': '附件暂时无法读取，请检查文件权限或重新上传'}, ensure_ascii=False)}\n\n"
        return
    conversation_store.append_message(db, conversation, "USER", user_message.content, citations=citations or None)
    db.commit()

    full_content = ""
    try:
        async for delta in stream_chat(data, runtime, attachment_context=combined_context or None, image_parts=native_image_parts or None):
            full_content += delta
            yield f"event: delta\ndata: {json.dumps({'content': delta}, ensure_ascii=False)}\n\n"
    except BusinessValidationError as exc:
        yield f"event: error\ndata: {json.dumps({'message': str(exc)}, ensure_ascii=False)}\n\n"
        return
    conversation_store.append_message(db, conversation, "ASSISTANT", full_content.strip(), citations=citations or None)
    db.commit()
    LOGGER.info("AI 流式回复完成 user_id=%s mode=llm answer_length=%s answer_hash=%s", user.id, len(full_content.strip()), _text_fingerprint(full_content.strip()))
    done = {"conversation_id": conversation.id, "model": runtime.llm_model, "provider": runtime.llm_provider, "citations": citations or None, "user_query": user_message.content, "answer": full_content.strip()}
    yield f"event: done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"
