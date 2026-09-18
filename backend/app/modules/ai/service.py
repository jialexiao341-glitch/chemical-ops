"""AI 助手调用服务。"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import BusinessValidationError
from app.modules.ai.model import AIConversation, AIMessage
from app.modules.ai.schema import AIChatMessage, AIChatRequest, AIChatResponse
from app.modules.files import service as file_service
from app.modules.files import mineru
from app.modules.files.parser import parse_file_content
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


LOGGER = logging.getLogger("chemicalops.ai")
SYSTEM_PROMPT = """你是 ChemicalOps 化学品运营助手。
请优先使用清晰、简洁、可执行的中文回答采购、到货、质量、库存和供应商问题。
当前阶段你只能提供查询分析和业务草稿建议，不能声称已经修改数据库、提交订单或执行入库。
如果缺少真实业务数据，请明确说明需要用户提供信息，不要编造数量、订单、供应商或库存结果。"""
BUSINESS_KEYWORDS = ("采购", "订单", "库存", "到货", "收货", "质量", "验收", "异常", "财务", "供应商")


def _build_messages(data: AIChatRequest, attachment_context: list[str] | None = None) -> list[dict[str, str]]:
    """组装系统提示和用户会话消息。"""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(message.model_dump() for message in data.messages)
    if attachment_context:
        messages.append({"role": "system", "content": "以下是系统提供的已安全校验上下文，仅可据此回答；无法解析或未提供的数据不要猜测。\n" + "\n\n".join(attachment_context)})
    elif data.attachments:
        names = "、".join(data.attachments)
        messages.append({"role": "system", "content": f"用户选择了以下附件，但当前请求没有提供可读取的文件引用：{names}。请不要假设已读取附件。"})
    return messages


def _build_business_context(db: Session, user: User, data: AIChatRequest) -> tuple[list[str], list[dict[str, object]]]:
    """按实时权限为业务问题加载聚合和限量明细，不让 AI 绕过数据权限。"""

    user_text = " ".join(message.content for message in data.messages if message.role == "user")
    if not any(keyword in user_text for keyword in BUSINESS_KEYWORDS):
        return [], []
    role_codes = get_user_role_codes(db, user.id)
    permission_codes = get_user_permission_codes(db, user.id)
    if "SYS_ADMIN" not in role_codes and "dashboard.read" not in permission_codes:
        return [], []
    try:
        from app.modules.dashboard.service import get_overview
        from app.modules.deliveries.model import Delivery
        from app.modules.finance.model import FinanceReconciliation
        from app.modules.inventory.model import InventoryBalance, InventoryBatch
        from app.modules.operation_exceptions.model import OperationException
        from app.modules.products.model import Product
        from app.modules.purchase_orders.model import PurchaseOrder
        from app.modules.purchase_requests.model import Unit
        from app.modules.quality_acceptances.model import QualityAcceptance
        from app.modules.suppliers.model import Supplier

        overview = get_overview(db)
        sections: dict[str, object] = {"dashboard_overview": overview}
        if "采购" in user_text or "订单" in user_text:
            if "SYS_ADMIN" in role_codes or "procurement.orders.read" in permission_codes:
                rows = db.execute(select(PurchaseOrder.po_no, PurchaseOrder.supplier_id, Supplier.supplier_name, PurchaseOrder.order_amount, PurchaseOrder.currency_code, PurchaseOrder.status, PurchaseOrder.expected_arrival_date).join(Supplier, Supplier.id == PurchaseOrder.supplier_id).order_by(PurchaseOrder.created_at.desc()).limit(8)).all()
                sections["recent_purchase_orders"] = [dict(row._mapping) for row in rows]
        if "到货" in user_text or "逾期" in user_text or "收货" in user_text:
            if "SYS_ADMIN" in role_codes or "warehouse.deliveries.read" in permission_codes:
                rows = db.execute(select(Delivery.delivery_no, Delivery.po_id, Supplier.supplier_name, Delivery.expected_arrival_date, Delivery.actual_arrival_date, Delivery.status, Delivery.tracking_no).join(Supplier, Supplier.id == Delivery.supplier_id).where(Delivery.status == "IN_TRANSIT").order_by(Delivery.expected_arrival_date).limit(8)).all()
                sections["in_transit_deliveries"] = [dict(row._mapping) for row in rows]
        if "库存" in user_text:
            if "SYS_ADMIN" in role_codes or "warehouse.inventory.read" in permission_codes:
                rows = db.execute(select(Product.product_name, InventoryBalance.quantity, Unit.unit_name, InventoryBatch.batch_no, InventoryBatch.expiry_date).join(Product, Product.id == InventoryBalance.product_id).join(Unit, Unit.id == InventoryBalance.unit_id).join(InventoryBatch, InventoryBatch.id == InventoryBalance.batch_id).where(InventoryBalance.quantity > 0).order_by(InventoryBatch.expiry_date, Product.id).limit(8)).all()
                sections["inventory_batches"] = [dict(row._mapping) for row in rows]
        if "质量" in user_text or "验收" in user_text:
            if "SYS_ADMIN" in role_codes or "quality.acceptances.read" in permission_codes:
                rows = db.execute(select(QualityAcceptance.acceptance_no, Delivery.delivery_no, QualityAcceptance.result, QualityAcceptance.inspection_time, QualityAcceptance.certificate_complete, QualityAcceptance.conclusion).join(Delivery, Delivery.id == QualityAcceptance.delivery_id).order_by(QualityAcceptance.created_at.desc()).limit(8)).all()
                sections["quality_acceptances"] = [dict(row._mapping) for row in rows]
        if "异常" in user_text:
            if "SYS_ADMIN" in role_codes or "operations.exceptions.read" in permission_codes:
                rows = db.execute(select(OperationException.exception_no, OperationException.exception_type, OperationException.severity, OperationException.description, OperationException.status, OperationException.due_at).order_by(OperationException.created_at.desc()).limit(8)).all()
                sections["operation_exceptions"] = [dict(row._mapping) for row in rows]
        if "财务" in user_text or "发票" in user_text or "付款" in user_text or "结算" in user_text:
            if "SYS_ADMIN" in role_codes or "finance.reconciliations.read" in permission_codes:
                rows = db.execute(select(FinanceReconciliation.reconciliation_no, Supplier.supplier_name, FinanceReconciliation.total_amount, FinanceReconciliation.currency_code, FinanceReconciliation.status).join(Supplier, Supplier.id == FinanceReconciliation.supplier_id).order_by(FinanceReconciliation.created_at.desc()).limit(8)).all()
                sections["finance_reconciliations"] = [dict(row._mapping) for row in rows]
        if "供应商" in user_text:
            if "SYS_ADMIN" in role_codes or "master.suppliers.read" in permission_codes:
                rows = db.execute(select(Supplier.supplier_code, Supplier.supplier_name, Supplier.region, Supplier.cooperation_level, Supplier.default_lead_days, Supplier.status).order_by(Supplier.created_at.desc()).limit(8)).all()
                sections["suppliers"] = [dict(row._mapping) for row in rows]
        context = "以下是按当前用户权限查询的实时业务数据，回答时只能引用其中已有数据，不要补造明细：\n" + json.dumps(sections, ensure_ascii=False, default=str)
        citation = {"type": "business_context", "source": "实时数据库业务明细", "sections": [key for key in sections]}
        return [context], [citation]
    except Exception as exc:
        LOGGER.warning("AI 实时业务数据读取失败 error=%s", exc.__class__.__name__)
        return ["当前实时业务数据读取失败，请明确告知用户暂时无法基于数据库给出数量或状态结论。"], [{"type": "dashboard_overview", "source": "实时数据库聚合", "status": "FAILED"}]


async def chat(data: AIChatRequest, settings: Settings | None = None, attachment_context: list[str] | None = None) -> AIChatResponse:
    """调用配置的 OpenAI 兼容模型。"""

    runtime = settings or get_settings()
    if not runtime.agent_enabled:
        raise BusinessValidationError("AI 助手当前未启用")
    if not runtime.openai_api_key.strip():
        raise BusinessValidationError("AI API key 尚未配置，请先填写 .env")
    if runtime.llm_provider != "openai_compatible":
        raise BusinessValidationError(f"暂不支持的 AI 服务商：{runtime.llm_provider}")

    url = f"{runtime.openai_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": runtime.llm_model,
        "messages": _build_messages(data, attachment_context),
        "temperature": runtime.llm_temperature,
        "max_tokens": runtime.llm_max_tokens,
    }
    headers = {"Authorization": f"Bearer {runtime.openai_api_key}", "Content-Type": "application/json"}
    attempts = max(0, runtime.llm_max_retries) + 1
    response: httpx.Response | None = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=runtime.llm_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            break
        except httpx.TimeoutException as exc:
            if attempt == attempts - 1:
                LOGGER.warning("AI 服务请求超时，已重试 %s 次", attempt)
                raise BusinessValidationError("AI 服务响应超时，请稍后重试") from exc
        except httpx.RequestError as exc:
            if attempt == attempts - 1:
                LOGGER.warning("AI 服务网络请求失败：%s", exc.__class__.__name__)
                raise BusinessValidationError("AI 服务暂时不可用，请检查网络或稍后重试") from exc
        except httpx.HTTPStatusError as exc:
            LOGGER.warning("AI 服务返回 HTTP %s", exc.response.status_code)
            raise BusinessValidationError("AI 服务拒绝了请求，请检查 API key、模型和额度配置") from exc

    if response is None:
        raise BusinessValidationError("AI 服务没有返回结果")
    try:
        result = response.json()
        raw_message = result["choices"][0]["message"]
        content = str(raw_message.get("content") or "").strip()
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise BusinessValidationError("AI 服务返回了无法识别的结果") from exc
    if not content:
        raise BusinessValidationError("AI 服务返回了空答案")

    usage = result.get("usage")
    normalized_usage = usage if isinstance(usage, dict) and all(isinstance(value, int) for value in usage.values()) else None
    return AIChatResponse(
        message=AIChatMessage(role="assistant", content=content),
        conversation_id=data.conversation_id or 0,
        model=runtime.llm_model,
        provider=runtime.llm_provider,
        usage=normalized_usage,
    )


def _get_owned_conversation(db: Session, user: User, conversation_id: int) -> AIConversation:
    """读取当前用户自己的会话，其他用户的会话按不存在处理。"""

    conversation = db.scalar(select(AIConversation).where(AIConversation.id == conversation_id, AIConversation.user_id == user.id))
    if conversation is None:
        raise BusinessValidationError("AI 会话不存在或无权访问")
    return conversation


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
        return _get_owned_conversation(db, user, data.conversation_id)
    first_user = next((message.content.strip() for message in data.messages if message.role == "user" and message.content.strip()), "新建对话")
    conversation = AIConversation(
        user_id=user.id,
        title=first_user[:80],
        business_scene="GENERAL",
        permission_snapshot={"roles": get_user_role_codes(db, user.id), "permissions": get_user_permission_codes(db, user.id)},
        status="ACTIVE",
        last_message_at=datetime.now(),
    )
    db.add(conversation)
    db.flush()
    return conversation


async def chat_for_user(db: Session, user: User, data: AIChatRequest) -> AIChatResponse:
    """持久化用户消息并调用模型，再持久化助手回复。"""

    conversation = _ensure_conversation(db, user, data)
    user_message = next((message for message in reversed(data.messages) if message.role == "user"), None)
    if user_message is None:
        raise BusinessValidationError("至少需要一条用户消息")
    attachment_context: list[str] = []
    attachment_citations: list[dict[str, object]] = []
    runtime = get_settings()
    for file_id in dict.fromkeys(data.attachment_file_ids):
        value = file_service.get_file(db, user, file_id)
        if value.uploader_id != user.id and "SYS_ADMIN" not in get_user_role_codes(db, user.id):
            raise BusinessValidationError("只能将自己上传的文件提交给 AI 分析")
        if len(attachment_context) >= 20:
            break
        try:
            _, content = file_service.read_file(db, user, file_id)
            extension = Path(value.file_name).suffix.lower()
            if runtime.mineru_enabled and extension in mineru.SUPPORTED_REMOTE_EXTENSIONS:
                value.parse_status = "PROCESSING"
                value.parse_error = None
                db.commit()
                try:
                    parsed = await asyncio.to_thread(mineru.parse_bytes, value.file_name, content, runtime)
                except mineru.MinerUParseError:
                    LOGGER.warning("MinerU 附件解析失败，回退本地解析 file_id=%s", file_id)
                    parsed = parse_file_content(value.file_name, value.mime_type, content)
            else:
                parsed = parse_file_content(value.file_name, value.mime_type, content)
            value.parse_status = parsed.status
            value.parse_error = parsed.error
            if parsed.text:
                attachment_context.append(f"附件：{value.file_name}\n{parsed.text[:12_000]}")
                try:
                    result_key = file_service.store_parse_result(value.id, parsed.text)
                    if result_key:
                        attachment_citations.append({"type": "parsed_result", "file_id": value.id, "object_key": result_key, "source": "解析结果 Markdown"})
                except Exception as exc:
                    LOGGER.warning("解析结果保存失败 file_id=%s error=%s", value.id, exc.__class__.__name__)
            else:
                attachment_context.append(f"附件：{value.file_name}\n{parsed.error or '文件没有可解析正文，请不要猜测其内容。'}")
            attachment_citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": parsed.status, "parser": parsed.parser, "references": parsed.references})
        except Exception as exc:
            LOGGER.warning("AI 附件读取失败 file_id=%s error=%s", file_id, exc.__class__.__name__)
            value.parse_status = "FAILED"
            value.parse_error = "文件解析失败，请检查文件格式或重新上传"
            attachment_context.append(f"附件：{value.file_name}\n文件读取失败，请不要基于该附件推断业务结论。")
            attachment_citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": "FAILED", "parser": "none", "references": []})
    business_context, business_citations = _build_business_context(db, user, data)
    combined_context = attachment_context + business_context
    combined_citations = attachment_citations + business_citations
    db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=combined_citations or None))
    conversation.last_message_at = datetime.now()
    db.commit()
    try:
        result = await chat(data, runtime, attachment_context=combined_context or None)
    except Exception:
        raise
    assistant_message = AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=result.message.content, citations=combined_citations or None)
    db.add(assistant_message)
    conversation.last_message_at = datetime.now()
    db.commit()
    result.conversation_id = conversation.id
    result.citations = combined_citations or None
    return result


async def stream_chat_for_user(db: Session, user: User, data: AIChatRequest) -> AsyncIterator[str]:
    """通过 SSE 转发 OpenAI 兼容接口的增量内容，并在结束时持久化。"""

    conversation = _ensure_conversation(db, user, data)
    user_message = next((message for message in reversed(data.messages) if message.role == "user"), None)
    if user_message is None:
        yield f"event: error\ndata: {json.dumps({'message': '至少需要一条用户消息'}, ensure_ascii=False)}\n\n"
        return
    runtime = get_settings()
    attachment_context: list[str] = []
    citations: list[dict[str, object]] = []
    for file_id in dict.fromkeys(data.attachment_file_ids):
        value = file_service.get_file(db, user, file_id)
        if value.uploader_id != user.id and "SYS_ADMIN" not in get_user_role_codes(db, user.id):
            yield f"event: error\ndata: {json.dumps({'message': '只能将自己上传的文件提交给 AI 分析'}, ensure_ascii=False)}\n\n"
            return
        try:
            _, content = file_service.read_file(db, user, file_id)
            extension = Path(value.file_name).suffix.lower()
            if runtime.mineru_enabled and extension in mineru.SUPPORTED_REMOTE_EXTENSIONS:
                value.parse_status = "PROCESSING"
                value.parse_error = None
                db.commit()
                try:
                    parsed = await asyncio.to_thread(mineru.parse_bytes, value.file_name, content, runtime)
                except mineru.MinerUParseError:
                    parsed = parse_file_content(value.file_name, value.mime_type, content)
            else:
                parsed = parse_file_content(value.file_name, value.mime_type, content)
            value.parse_status = parsed.status
            value.parse_error = parsed.error
            attachment_context.append(f"附件：{value.file_name}\n{(parsed.text or parsed.error or '文件没有可解析正文，请不要猜测其内容。')[:12_000]}")
            if parsed.text:
                try:
                    result_key = file_service.store_parse_result(value.id, parsed.text)
                    if result_key:
                        citations.append({"type": "parsed_result", "file_id": value.id, "object_key": result_key, "source": "解析结果 Markdown"})
                except Exception as exc:
                    LOGGER.warning("流式解析结果保存失败 file_id=%s error=%s", value.id, exc.__class__.__name__)
            citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": parsed.status, "parser": parsed.parser, "references": parsed.references})
        except Exception as exc:
            LOGGER.warning("AI 流式附件读取失败 file_id=%s error=%s", file_id, exc.__class__.__name__)
            attachment_context.append(f"附件：{value.file_name}\n文件读取失败，请不要基于该附件推断业务结论。")
            citations.append({"file_id": value.id, "file_name": value.file_name, "source": "用户上传附件", "parse_status": "FAILED", "parser": "none", "references": []})
    business_context, business_citations = _build_business_context(db, user, data)
    combined_context = attachment_context + business_context
    citations.extend(business_citations)
    db.add(AIMessage(conversation_id=conversation.id, message_role="USER", content=user_message.content, citations=citations or None))
    conversation.last_message_at = datetime.now()
    db.commit()

    if not runtime.agent_enabled or not runtime.openai_api_key.strip() or runtime.llm_provider != "openai_compatible":
        yield f"event: error\ndata: {json.dumps({'message': 'AI 服务配置不可用，请检查服务开关、API key 和服务商配置'}, ensure_ascii=False)}\n\n"
        return
    url = f"{runtime.openai_base_url.rstrip('/')}/chat/completions"
    payload = {"model": runtime.llm_model, "messages": _build_messages(data, combined_context or None), "temperature": runtime.llm_temperature, "max_tokens": runtime.llm_max_tokens, "stream": True}
    headers = {"Authorization": f"Bearer {runtime.openai_api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    full_content = ""
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
                        full_content += delta
                        yield f"event: delta\ndata: {json.dumps({'content': delta}, ensure_ascii=False)}\n\n"
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        LOGGER.warning("AI SSE 请求失败 error=%s", exc.__class__.__name__)
        yield f"event: error\ndata: {json.dumps({'message': 'AI 服务暂时不可用，请稍后重试'}, ensure_ascii=False)}\n\n"
        return
    if not full_content.strip():
        yield f"event: error\ndata: {json.dumps({'message': 'AI 服务返回了空答案'}, ensure_ascii=False)}\n\n"
        return
    db.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content=full_content.strip(), citations=citations or None))
    conversation.last_message_at = datetime.now()
    db.commit()
    done = {"conversation_id": conversation.id, "model": runtime.llm_model, "provider": runtime.llm_provider, "citations": citations or None}
    yield f"event: done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"
