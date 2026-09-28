"""AI 助手调用服务。"""

import asyncio
import base64
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from time import perf_counter

import httpx
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import BusinessValidationError
from app.core.observability import get_request_id, metrics
from app.modules.ai.agent_prompt import (
    SYSTEM_PROMPT as AGENT_SYSTEM_PROMPT,
    UNSUPPORTED_REPLY,
    build_project_reply,
    fallback_guidance_prompt,
    greeting_reply,
    result_rewrite_prompt,
)
from app.modules.ai.intent import Intent, IntentResult, classify_intent
from app.modules.ai.model import AIConversation, AIConversationState, AIMessage, AIQueryLog
from app.modules.ai.schema import AIChatMessage, AIChatRequest, AIChatResponse, AIQueryTrace
from app.modules.files import service as file_service
from app.modules.files import mineru
from app.modules.files.parser import parse_file_content
from app.modules.files.scanner import scan_content
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


LOGGER = logging.getLogger("chemicalops.ai")
SYSTEM_PROMPT = AGENT_SYSTEM_PROMPT
STREAM_CHUNK_SIZE = 4
STREAM_CHUNK_DELAY_SECONDS = 0.03
MAX_ATTACHMENT_CONTEXT_CHARS = 48_000
MAX_ATTACHMENT_IMAGE_BYTES = 8 * 1024 * 1024
UNRESOLVED_CHEMICAL_REPLY = "我没有匹配到已登记化学品的名称或有效 CAS 号，因此无法核对对应资料。请补充准确名称或 CAS 号后再问。"
READ_ONLY_WRITE_MARKERS = (
    "帮我创建", "帮我修改", "帮我删除", "帮我提交", "帮我审批", "帮我驳回",
    "帮我下单", "帮我入库", "帮我出库", "帮我付款", "帮我执行",
    "请创建", "请修改", "请删除", "请提交", "请审批", "请驳回",
    "请下单", "请入库", "请出库", "请付款", "请执行",
    "直接创建", "直接修改", "直接提交", "直接审批", "直接下单",
    "直接入库", "直接出库", "直接付款", "直接执行",
)


def _build_llm_payload(runtime: Settings, messages: list[dict[str, object]], *, stream: bool = False, response_format: dict[str, str] | None = None) -> dict[str, object]:
    """组装 OpenAI 兼容请求；DeepSeek Flash 默认支持思考模式，显式开启以获得完整回答。"""

    payload: dict[str, object] = {
        "model": runtime.llm_model,
        "messages": messages,
        "temperature": runtime.llm_temperature,
        "max_tokens": runtime.llm_max_tokens,
    }
    if runtime.llm_model.lower() == "deepseek-flash":
        payload["thinking"] = {"type": "enabled"}
    if stream:
        payload["stream"] = True
    if response_format is not None:
        payload["response_format"] = response_format
    return payload


async def _stream_text_chunks(content: str) -> AsyncIterator[str]:
    """把已经生成的安全文本分成小段输出，避免前端一次性出现整段内容。"""

    for index in range(0, len(content), STREAM_CHUNK_SIZE):
        yield content[index : index + STREAM_CHUNK_SIZE]
        await asyncio.sleep(STREAM_CHUNK_DELAY_SECONDS)


def _validate_read_only_request(data: AIChatRequest) -> None:
    """拒绝明确要求 AI 执行业务写操作的请求。"""

    user_text = " ".join(message.content for message in data.messages if message.role == "user")
    if any(marker in user_text for marker in READ_ONLY_WRITE_MARKERS):
        raise BusinessValidationError("AI 仅支持查询和分析，不支持创建、修改、审批、提交、下单、入库、出库或付款等业务操作。")


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


CHEMICAL_REFERENCE_MARKERS = (
    "产品",
    "化学品",
    "化合物",
    "了解",
    "介绍",
    "什么是",
    "是什么",
    "基本信息",
    "用途",
    "特性",
    "性质",
    "物性",
    "特点",
    "溶解度",
    "蒸气压",
    "自燃温度",
    "密度",
    "外观",
    "粘度",
    "黏度",
)
CHEMICAL_SPECIFIC_DOC_MARKERS = (
    "特性",
    "性质",
    "物性",
    "特点",
    "溶解度",
    "蒸气压",
    "自燃温度",
    "密度",
    "外观",
    "粘度",
    "黏度",
    "闪点",
    "沸点",
    "熔点",
    "分子式",
    "分子量",
    "危险性",
    "危险类别",
    "危险声明",
    "信号词",
    "ghs",
    "msds",
    "sds",
    "安全数据表",
    "安全技术说明书",
    "急救",
    "消防",
    "灭火",
    "泄漏处置",
    "职业接触",
    "毒性",
    "储存条件",
    "存储条件",
    "相容性",
    "不相容",
    "tlv",
    "ld50",
    "lc50",
)


async def _classify_chat_intent(db: Session, question: str) -> IntentResult:
    """将已登记化学品名称纳入意图判断；命中后仍通过知识库章节提供事实。"""

    result = classify_intent(question)
    lowered = question.lower()
    asks_for_specific_properties = any(marker in lowered for marker in CHEMICAL_SPECIFIC_DOC_MARKERS)
    should_resolve_chemical = (
        result.intent is Intent.UNSUPPORTED
        and result.reason == "no_supported_marker"
        and any(marker in lowered for marker in CHEMICAL_REFERENCE_MARKERS)
    ) or (result.intent is Intent.DOC and asks_for_specific_properties)
    if not should_resolve_chemical:
        return result
    try:
        from app.modules.doc_kb.retrieve import resolve_doc_targets

        targets = await resolve_doc_targets(db, question)
    except Exception as exc:
        LOGGER.warning("化学品意图实体识别失败 error_type=%s", exc.__class__.__name__)
        return IntentResult(Intent.DOC, "chemical_target_unresolved") if asks_for_specific_properties else result
    if targets:
        return result if result.intent is Intent.DOC else IntentResult(Intent.DOC, "registered_chemical_reference")
    if asks_for_specific_properties or result.intent is Intent.UNSUPPORTED:
        return IntentResult(Intent.DOC, "chemical_target_unresolved")
    return result


def _retryable_status(status_code: int) -> bool:
    return status_code in {408, 425, 429} or status_code >= 500


async def _retry_wait(attempt: int) -> None:
    await asyncio.sleep(min(2.0, 0.25 * (2**attempt)))


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


def _build_messages(
    data: AIChatRequest,
    attachment_context: list[str] | None = None,
    image_parts: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """组装系统提示、会话消息和模型原生视觉图片块。"""

    messages: list[dict[str, object]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(message.model_dump() for message in data.messages)
    if image_parts:
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                text_content = str(messages[index].get("content") or "")
                messages[index] = {
                    "role": "user",
                    "content": [{"type": "text", "text": text_content}, *image_parts],
                }
                break
    if attachment_context:
        messages.append({"role": "system", "content": "以下是系统提供的已安全校验上下文，仅可据此回答；无法解析或未提供的数据不要猜测。\n" + "\n\n".join(attachment_context)})
    elif data.attachments and not image_parts:
        names = "、".join(data.attachments)
        messages.append({"role": "system", "content": f"用户选择了以下附件，但当前请求没有提供可读取的文件引用：{names}。请不要假设已读取附件。"})
    return messages

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
            AIChatRequest(messages=[AIChatMessage(role="user", content=result_rewrite_prompt(payload))]),
            settings,
            response_format={"type": "json_object"},
        )
        raw = (rewritten.answer or rewritten.message.content or "").strip()
        if not raw:
            return None
        from app.modules.ai.text2sql import _extract_query_plan_payload

        parsed = _extract_query_plan_payload(raw)
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
) -> tuple[str, dict[str, object], AIQueryTrace]:
    """聊天入口的业务查询路由；Text2SQL 结果不再经过通用聊天上下文。"""

    from app.modules.ai.order_trace import extract_order_trace_no, trace_purchase_order
    from app.modules.ai.text2sql import Text2SQLRequest, run_text2sql

    query_fields = _query_log_fields(user, question)
    LOGGER.info("AI 查询开始 %s", query_fields)
    order_no = extract_order_trace_no(question)
    if order_no:
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
        state = db.scalar(select(AIConversationState).where(AIConversationState.thread_id == thread_id)) if thread_id else None
        if state is not None:
            state.query_plan = None
            state.query_trace = trace.model_dump(mode="json", exclude={"sql", "parameterized_sql", "rows"})
            state.permission_snapshot = _permission_snapshot(db, user)
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

    result = await run_text2sql(db, user, Text2SQLRequest(question=question), settings, previous_plan=previous_plan, thread_id=thread_id)
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


async def chat(data: AIChatRequest, settings: Settings | None = None, attachment_context: list[str] | None = None, response_format: dict[str, str] | None = None, image_parts: list[dict[str, object]] | None = None) -> AIChatResponse:
    """调用配置的 OpenAI 兼容模型。"""

    _validate_read_only_request(data)
    runtime = settings or get_settings()
    if not runtime.agent_enabled:
        raise BusinessValidationError("AI 助手当前未启用")
    if not runtime.openai_api_key.strip():
        raise BusinessValidationError("AI API key 尚未配置，请先填写 .env")
    if runtime.llm_provider != "openai_compatible":
        raise BusinessValidationError(f"暂不支持的 AI 服务商：{runtime.llm_provider}")

    url = f"{runtime.openai_base_url.rstrip('/')}/chat/completions"
    payload = _build_llm_payload(runtime, _build_messages(data, attachment_context, image_parts), response_format=response_format)
    headers = {"Authorization": f"Bearer {runtime.openai_api_key}", "Content-Type": "application/json"}
    attempts = max(0, runtime.llm_max_retries) + 1
    response: httpx.Response | None = None
    started = perf_counter()
    metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "started"})
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=runtime.llm_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "success"})
            break
        except httpx.TimeoutException as exc:
            if attempt == attempts - 1:
                metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "timeout"})
                LOGGER.warning("AI 服务请求超时 retries=%s", attempt)
                raise BusinessValidationError("AI 服务响应超时，请稍后重试") from exc
            metrics.increment("ai_external_retries", labels={"mode": "sync", "reason": "timeout"})
            await _retry_wait(attempt)
        except httpx.RequestError as exc:
            if attempt == attempts - 1:
                metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "network_error"})
                LOGGER.warning("AI 服务网络请求失败 error_type=%s retries=%s", exc.__class__.__name__, attempt)
                raise BusinessValidationError("AI 服务暂时不可用，请检查网络或稍后重试") from exc
            metrics.increment("ai_external_retries", labels={"mode": "sync", "reason": "network_error"})
            await _retry_wait(attempt)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if _retryable_status(status_code) and attempt < attempts - 1:
                metrics.increment("ai_external_retries", labels={"mode": "sync", "reason": f"http_{status_code}"})
                await _retry_wait(attempt)
                continue
            metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": f"http_{status_code}"})
            LOGGER.warning("AI 服务返回 HTTP status=%s retries=%s", status_code, attempt)
            if _retryable_status(status_code):
                raise BusinessValidationError("AI 服务暂时不可用，请稍后重试") from exc
            raise BusinessValidationError("AI 服务拒绝了请求，请检查 API key、模型和额度配置") from exc

    if response is None:
        metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "empty"})
        raise BusinessValidationError("AI 服务没有返回结果")
    try:
        result = response.json()
        raw_message = result["choices"][0]["message"]
        content = str(raw_message.get("content") or "").strip()
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "invalid_response"})
        raise BusinessValidationError("AI 服务返回了无法识别的结果") from exc
    if not content:
        metrics.increment("ai_external_requests", labels={"mode": "sync", "provider": runtime.llm_provider, "status": "empty_answer"})
        raise BusinessValidationError("AI 服务返回了空答案")

    metrics.observe("ai_external_duration_seconds", perf_counter() - started, labels={"mode": "sync", "provider": runtime.llm_provider})

    usage = result.get("usage")
    normalized_usage = usage if isinstance(usage, dict) and all(isinstance(value, int) for value in usage.values()) else None
    return AIChatResponse(
        message=AIChatMessage(role="assistant", content=content),
        conversation_id=data.conversation_id or 0,
        model=runtime.llm_model,
        provider=runtime.llm_provider,
        usage=normalized_usage,
        user_query=next((message.content for message in reversed(data.messages) if message.role == "user"), None),
        answer=content,
    )


def _get_owned_conversation(db: Session, user: User, conversation_id: int) -> AIConversation:
    """读取当前用户自己的会话，其他用户的会话按不存在处理。"""

    conversation = db.scalar(select(AIConversation).where(AIConversation.id == conversation_id, AIConversation.user_id == user.id))
    if conversation is None:
        raise BusinessValidationError("AI 会话不存在或无权访问")
    return conversation


def _conversation_state_enabled(db: Session) -> bool:
    """迁移尚未执行时保持旧版本可用；完成 017 后自动启用持久化上下文。"""

    try:
        bind = db.get_bind()
        return bool(bind is not None and inspect(bind).has_table(AIConversationState.__tablename__))
    except Exception as exc:
        LOGGER.warning("AI 会话状态表检查失败 error_type=%s", exc.__class__.__name__)
        return False


def _permission_snapshot(db: Session, user: User) -> dict[str, list[str]]:
    return {"roles": get_user_role_codes(db, user.id), "permissions": get_user_permission_codes(db, user.id)}


def _load_conversation_state(db: Session, conversation: AIConversation) -> AIConversationState | None:
    if not _conversation_state_enabled(db):
        return None
    return db.scalar(select(AIConversationState).where(AIConversationState.conversation_id == conversation.id))


def _query_log_enabled(db: Session) -> bool:
    """迁移 020 尚未执行时跳过留档，保持旧环境可用。"""

    try:
        bind = db.get_bind()
        return bool(bind is not None and inspect(bind).has_table(AIQueryLog.__tablename__))
    except Exception as exc:
        LOGGER.warning("AI 查询留档表检查失败 error_type=%s", exc.__class__.__name__)
        return False


def _append_query_log(db: Session, conversation: AIConversation, trace: AIQueryTrace) -> None:
    """每轮 Text2SQL 追加一条留档，与会话级“最近一次”状态互补保留历史轨迹。"""

    if not _query_log_enabled(db):
        return
    db.add(
        AIQueryLog(
            conversation_id=conversation.id,
            thread_id=trace.thread_id,
            question=trace.query,
            question_hash=_text_fingerprint(trace.query),
            dataset=trace.dataset or "unknown",
            dataset_label=trace.dataset_label,
            slots=trace.model_dump(mode="json", include={"slots"})["slots"],
            template=trace.template,
            sql_text=trace.sql,
            row_count=trace.row_count,
            truncated=trace.truncated,
            unit=trace.unit,
            executed_at=trace.executed_at,
        )
    )


def _save_query_state(
    db: Session,
    user: User,
    conversation: AIConversation,
    *,
    plan: object,
    trace: AIQueryTrace,
    citations: list[dict[str, object]],
) -> None:
    if not _conversation_state_enabled(db):
        return
    existing = _load_conversation_state(db, conversation)
    state = existing or AIConversationState(
        conversation_id=conversation.id,
        thread_id=f"ai:{user.id}:{conversation.id}",
        state_version=1,
    )
    state.query_plan = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else None
    state.query_trace = trace.model_dump(mode="json", exclude={"sql", "parameterized_sql", "rows"})
    state.permission_snapshot = _permission_snapshot(db, user)
    state.attachment_refs = [
        {key: item.get(key) for key in ("file_id", "file_name", "parse_status", "parser", "object_key") if key in item}
        for item in citations
        if isinstance(item, dict) and item.get("file_id")
    ] or None
    if existing is None:
        db.add(state)


def delete_conversation(db: Session, user: User, conversation_id: int) -> None:
    """删除当前用户自己的会话及其消息。"""
    conversation = _get_owned_conversation(db, user, conversation_id)
    if _conversation_state_enabled(db):
        db.execute(delete(AIConversationState).where(AIConversationState.conversation_id == conversation.id))
    if _query_log_enabled(db):
        db.execute(delete(AIQueryLog).where(AIQueryLog.conversation_id == conversation.id))
    db.execute(delete(AIMessage).where(AIMessage.conversation_id == conversation.id))
    db.delete(conversation)
    db.commit()


def clear_query_context(db: Session, user: User, conversation_id: int) -> None:
    """清除结构化 QueryPlan，不删除用户可见聊天记录。"""

    conversation = _get_owned_conversation(db, user, conversation_id)
    if _conversation_state_enabled(db):
        db.execute(delete(AIConversationState).where(AIConversationState.conversation_id == conversation.id))
        db.commit()

def list_conversations(db: Session, user: User, *, limit: int = 50) -> tuple[list[AIConversation], int]:
    """按最近消息时间返回当前用户会话。"""

    condition = AIConversation.user_id == user.id
    total = db.scalar(select(func.count(AIConversation.id)).where(condition)) or 0
    items = list(db.scalars(select(AIConversation).where(condition).order_by(AIConversation.last_message_at.desc(), AIConversation.id.desc()).limit(limit)).all())
    return items, total


def list_messages(db: Session, user: User, conversation_id: int, *, limit: int = 100) -> tuple[list[AIMessage], int]:
    """读取当前用户会话消息。"""

    _get_owned_conversation(db, user, conversation_id)
    condition = AIMessage.conversation_id == conversation_id
    total = db.scalar(select(func.count(AIMessage.id)).where(condition)) or 0
    items = list(db.scalars(select(AIMessage).where(condition).order_by(AIMessage.created_at.asc(), AIMessage.id.asc()).limit(limit)).all())
    return items, total


def _ensure_conversation(db: Session, user: User, data: AIChatRequest) -> AIConversation:
    """获取或创建会话，并保存权限快照。"""

    if data.conversation_id:
        conversation = _get_owned_conversation(db, user, data.conversation_id)
        conversation.permission_snapshot = _permission_snapshot(db, user)
        return conversation
    first_user = next((message.content.strip() for message in data.messages if message.role == "user" and message.content.strip()), "新建对话")
    conversation = AIConversation(
        user_id=user.id,
        title=first_user[:80],
        business_scene="GENERAL",
        permission_snapshot=_permission_snapshot(db, user),
        status="ACTIVE",
        last_message_at=datetime.now(),
    )
    db.add(conversation)
    db.flush()
    return conversation


async def chat_for_user(db: Session, user: User, data: AIChatRequest) -> AIChatResponse:
    """持久化用户消息并调用模型，再持久化助手回复。"""

    _validate_read_only_request(data)

    conversation = _ensure_conversation(db, user, data)
    user_message = next((message for message in reversed(data.messages) if message.role == "user"), None)
    if user_message is None:
        raise BusinessValidationError("至少需要一条用户消息")
    LOGGER.info("AI 请求进入 mode=sync user_id=%s query_length=%s", user.id, len(user_message.content))
    intent_result = await _classify_chat_intent(db, user_message.content)
    LOGGER.info("AI 意图识别 mode=sync user_id=%s intent=%s reason=%s", user.id, intent_result.intent, intent_result.reason)
    if intent_result.intent is Intent.DOC and not data.attachment_file_ids:
        from app.modules.doc_kb.retrieve import build_doc_context, no_doc_hits_reply, retrieve_sections

        hits = [] if intent_result.reason == "chemical_target_unresolved" else await retrieve_sections(db, user_message.content)
        if not hits:
            fixed_content = UNRESOLVED_CHEMICAL_REPLY if intent_result.reason == "chemical_target_unresolved" else no_doc_hits_reply(user_message.content)
            LOGGER.info("AI 文档检索为空 user_id=%s question_hash=%s", user.id, _text_fingerprint(user_message.content))
            db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content))
            db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=fixed_content))
            conversation.last_message_at = datetime.now()
            db.commit()
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
        result = await chat(data, runtime, attachment_context=[context])
        db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=citations))
        db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=result.message.content, citations=citations))
        conversation.last_message_at = datetime.now()
        db.commit()
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
        conversation_state = _load_conversation_state(db, conversation)
        previous_plan = None
        if conversation_state and conversation_state.query_plan:
            from app.modules.ai.text2sql import QueryPlan

            try:
                previous_plan = QueryPlan.model_validate(conversation_state.query_plan)
            except (TypeError, ValueError):
                LOGGER.warning("AI 会话 QueryPlan 状态无效 conversation_id=%s", conversation.id)
        thread_id = f"ai:{user.id}:{conversation.id}"
        content, citation, query_trace = await _run_text2sql_for_chat(
            db, user, user_message.content, runtime, previous_plan=previous_plan, thread_id=thread_id
        )
        citations = [citation]
        from app.modules.ai.text2sql import QueryPlan

        plan_payload = citation.get("query_plan") if isinstance(citation, dict) else None
        if isinstance(plan_payload, dict):
            _save_query_state(db, user, conversation, plan=QueryPlan.model_validate(plan_payload), trace=query_trace, citations=citations)
        _append_query_log(db, conversation, query_trace)
        db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=citations))
        db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=content, citations=citations))
        conversation.last_message_at = datetime.now()
        db.commit()
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
        db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content))
        db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=fixed_content))
        conversation.last_message_at = datetime.now()
        db.commit()
        return AIChatResponse(message=AIChatMessage(role="assistant", content=fixed_content), conversation_id=conversation.id, model=model_tag, provider="chemicalops", citations=None, user_query=user_message.content, answer=fixed_content)

    runtime = get_settings()
    combined_context, native_image_parts, combined_citations = await _prepare_attachments(db, user, data, runtime)
    db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=combined_citations or None))
    conversation.last_message_at = datetime.now()
    db.commit()
    try:
        result = await chat(data, runtime, attachment_context=combined_context or None, image_parts=native_image_parts or None)
    except Exception:
        raise
    assistant_message = AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=result.message.content, citations=combined_citations or None)
    db.add(assistant_message)
    conversation.last_message_at = datetime.now()
    db.commit()
    result.conversation_id = conversation.id
    result.citations = combined_citations or None
    result.user_query = user_message.content
    result.answer = result.message.content
    return result


async def stream_chat_for_user(db: Session, user: User, data: AIChatRequest) -> AsyncIterator[str]:
    """通过 SSE 转发 OpenAI 兼容接口的增量内容，并在结束时持久化。"""

    _validate_read_only_request(data)

    conversation = _ensure_conversation(db, user, data)
    user_message = next((message for message in reversed(data.messages) if message.role == "user"), None)
    if user_message is None:
        yield f"event: error\ndata: {json.dumps({'message': '至少需要一条用户消息'}, ensure_ascii=False)}\n\n"
        return
    LOGGER.info("AI 请求进入 mode=stream %s", _query_log_fields(user, user_message.content))
    stream_intent_result = await _classify_chat_intent(db, user_message.content)
    LOGGER.info("AI 意图识别 mode=stream user_id=%s intent=%s reason=%s", user.id, stream_intent_result.intent, stream_intent_result.reason)
    if stream_intent_result.intent is Intent.DOC and not data.attachment_file_ids:
        from app.modules.doc_kb.retrieve import build_doc_context, no_doc_hits_reply, retrieve_sections

        hits = [] if stream_intent_result.reason == "chemical_target_unresolved" else await retrieve_sections(db, user_message.content)
        doc_citations: list | None = None
        doc_model = "rule-based"
        if hits:
            context, doc_citations = build_doc_context(hits)
            runtime = get_settings()
            try:
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
            doc_content = UNRESOLVED_CHEMICAL_REPLY if stream_intent_result.reason == "chemical_target_unresolved" else no_doc_hits_reply(user_message.content)
            LOGGER.info("AI 流式文档检索为空 user_id=%s", user.id)
        chunk_count = 0
        async for chunk in _stream_text_chunks(doc_content):
            chunk_count += 1
            yield "event: delta\ndata: " + json.dumps({"content": chunk}, ensure_ascii=False) + "\n\n"
        db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=doc_citations))
        db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=doc_content, citations=doc_citations))
        conversation.last_message_at = datetime.now()
        db.commit()
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
        conversation_state = _load_conversation_state(db, conversation)
        previous_plan = None
        if conversation_state and conversation_state.query_plan:
            from app.modules.ai.text2sql import QueryPlan

            try:
                previous_plan = QueryPlan.model_validate(conversation_state.query_plan)
            except (TypeError, ValueError):
                LOGGER.warning("AI 流式会话 QueryPlan 状态无效 conversation_id=%s", conversation.id)
        thread_id = f"ai:{user.id}:{conversation.id}"
        try:
            content, citation, query_trace = await _run_text2sql_for_chat(
                db, user, user_message.content, runtime, previous_plan=previous_plan, thread_id=thread_id
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
            _save_query_state(db, user, conversation, plan=QueryPlan.model_validate(plan_payload), trace=query_trace, citations=citations)
        _append_query_log(db, conversation, query_trace)
        db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=citations))
        db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=content, citations=citations))
        conversation.last_message_at = datetime.now()
        db.commit()
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
        db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content))
        db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=fixed_content))
        conversation.last_message_at = datetime.now()
        db.commit()
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
    db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=citations or None))
    conversation.last_message_at = datetime.now()
    db.commit()

    if not runtime.agent_enabled or not runtime.openai_api_key.strip() or runtime.llm_provider != "openai_compatible":
        yield f"event: error\ndata: {json.dumps({'message': 'AI 服务配置不可用，请检查服务开关、API key 和服务商配置'}, ensure_ascii=False)}\n\n"
        return
    url = f"{runtime.openai_base_url.rstrip('/')}/chat/completions"
    payload = _build_llm_payload(runtime, _build_messages(data, combined_context or None, native_image_parts or None), stream=True)
    headers = {"Authorization": f"Bearer {runtime.openai_api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    full_content = ""
    first_token_at: float | None = None
    stream_error: Exception | None = None
    started = perf_counter()
    attempts = max(0, runtime.llm_max_retries) + 1
    metrics.increment("ai_external_requests", labels={"mode": "stream", "provider": runtime.llm_provider, "status": "started"})
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=runtime.llm_timeout_seconds) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                        except (ValueError, TypeError, IndexError, KeyError):
                            continue
                        if delta:
                            if first_token_at is None:
                                first_token_at = perf_counter()
                                metrics.observe("ai_first_token_seconds", first_token_at - started, labels={"mode": "stream", "provider": runtime.llm_provider})
                            full_content += delta
                            yield f"event: delta\ndata: {json.dumps({'content': delta}, ensure_ascii=False)}\n\n"
            stream_error = None
            metrics.increment("ai_external_requests", labels={"mode": "stream", "provider": runtime.llm_provider, "status": "success"})
            break
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            stream_error = exc
            # 已经向客户端发送过内容时不能重试，否则会重复输出；同时绝不保存半截答案。
            retryable = not isinstance(exc, httpx.HTTPStatusError) or _retryable_status(exc.response.status_code if exc.response is not None else 0)
            if full_content or attempt == attempts - 1 or not retryable:
                break
            metrics.increment("ai_external_retries", labels={"mode": "stream", "reason": exc.__class__.__name__})
            await _retry_wait(attempt)
    metrics.observe("ai_external_duration_seconds", perf_counter() - started, labels={"mode": "stream", "provider": runtime.llm_provider})
    if stream_error is not None:
        metrics.increment("ai_external_requests", labels={"mode": "stream", "provider": runtime.llm_provider, "status": "failure"})
        LOGGER.warning("AI SSE 请求失败 error_type=%s retries=%s partial=%s", stream_error.__class__.__name__, attempt, bool(full_content))
        yield f"event: error\ndata: {json.dumps({'message': 'AI 服务暂时不可用，请稍后重试'}, ensure_ascii=False)}\n\n"
        return
    if not full_content.strip():
        yield f"event: error\ndata: {json.dumps({'message': 'AI 服务返回了空答案'}, ensure_ascii=False)}\n\n"
        return
    db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=full_content.strip(), citations=citations or None))
    conversation.last_message_at = datetime.now()
    db.commit()
    LOGGER.info("AI 流式回复完成 user_id=%s mode=llm answer_length=%s answer_hash=%s", user.id, len(full_content.strip()), _text_fingerprint(full_content.strip()))
    done = {"conversation_id": conversation.id, "model": runtime.llm_model, "provider": runtime.llm_provider, "citations": citations or None, "user_query": user_message.content, "answer": full_content.strip()}
    yield f"event: done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"
