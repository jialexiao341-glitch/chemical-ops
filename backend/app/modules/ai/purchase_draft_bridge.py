"""把已完成的查询结果衔接为采购申请草稿来源。

只读事实统一由当前身份重新查询；会话、消息、任务与批次引用仅用于定位，
不接受客户端提交的证据快照。模型与用户文本都不能决定来源产品。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai import agent_tools, conversation_store
from app.modules.ai.model import AIAgentTask, AIMessage
from app.modules.ai.schema import ToolCall
from app.modules.products.model import Product
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


# 结果指纹排除每次查询必变的元数据，保留会改变参考判断的事实。
FINGERPRINT_EXCLUDED_KEYS = frozenset({"observed_at", "as_of"})

EVIDENCE_TOOL_PERMISSIONS = {
    "catalog.search_products": "master.products.read",
    "inventory.query_available": "warehouse.inventory.read",
    "supplier_quotes.find_rfq_items": "procurement.rfqs.read",
    "supplier_quotes.compare": "procurement.rfqs.read",
}

PRODUCT_TOOL_NAMES = frozenset({
    "inventory.query_available",
    "supplier_quotes.find_rfq_items",
    "supplier_quotes.compare",
})


@dataclass(frozen=True)
class DraftSource:
    """服务端已核验的产品来源；message/task 引用用于回看与重新核验。"""

    kind: str
    message_id: int
    product_id: int
    unit_id: int | None = None
    product_name: str | None = None
    rfq_item_id: int | None = None
    task_id: str | None = None
    revision: int | None = None
    subtask_id: str | None = None
    anchors: tuple[dict, ...] = ()

    def reference(self) -> dict:
        return {
            "type": "query",
            "kind": self.kind,
            "message_id": self.message_id,
            "task_id": self.task_id,
            "revision": self.revision,
            "subtask_id": self.subtask_id,
            "product_id": self.product_id,
            "rfq_item_id": self.rfq_item_id,
        }


@dataclass(frozen=True)
class SourceResolution:
    source: DraftSource | None = None
    reason: str | None = None


def digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def result_fingerprint(result: dict) -> str:
    """结果指纹：排除观察时间，保留来源、范围、截断与业务值。"""

    return digest({key: value for key, value in result.items() if key not in FINGERPRINT_EXCLUDED_KEYS})


def tool_evidence(label: str, call: ToolCall, result, *, source: DraftSource | None = None) -> dict:
    """生成可展示、可复核的只读证据；不保存模型文本。"""

    dumped = result.model_dump(mode="json")
    entry: dict = {
        "type": "tool",
        "label": label,
        "tool": call.tool,
        "arguments": dict(call.arguments),
        "observed_at": dumped.get("observed_at"),
        "fingerprint": result_fingerprint(dumped),
    }
    for key in ("rows", "totals", "sources", "scope", "comparison_basis", "total_rows",
                "truncated", "warnings", "keyword", "product_name"):
        if key in dumped:
            entry[key] = dumped[key]
    if source is not None:
        entry["source"] = source.reference()
    return entry


def evidence_permissions(entry: object) -> set[str]:
    if not isinstance(entry, dict) or entry.get("type") != "tool":
        return set()
    permission = EVIDENCE_TOOL_PERMISSIONS.get(str(entry.get("tool") or ""))
    return {permission} if permission else set()


def evidence_readable(entry: object, permission_codes: set[str], roles: set[str]) -> bool:
    if "SYS_ADMIN" in roles:
        return True
    return evidence_permissions(entry) <= permission_codes


def _trace_entries(payload: dict) -> list[dict]:
    return [
        entry for entry in payload.get("trace") or []
        if isinstance(entry, dict) and entry.get("action") == "call_tool"
        and entry.get("status") == "SUCCEEDED" and isinstance(entry.get("result"), dict)
        and isinstance(entry.get("arguments"), dict)
    ]


def _catalog_unit(trace: list[dict], product_id: int) -> tuple[int | None, str | None]:
    for entry in trace:
        if entry.get("tool") != "catalog.search_products":
            continue
        for row in (entry.get("result") or {}).get("rows") or []:
            if isinstance(row, dict) and row.get("product_id") == product_id:
                return row.get("unit_id"), row.get("product_name")
    return None, None


def _agent_candidates(db: Session, user: User, conversation_id: int, message_id: int,
                      task_id: str) -> tuple[list[DraftSource], str | None]:
    task = db.scalar(select(AIAgentTask).where(
        AIAgentTask.id == task_id, AIAgentTask.user_id == user.id))
    if task is None:
        return [], "SKIP"
    chat = (task.payload or {}).get("chat") or {}
    if chat.get("conversation_id") != conversation_id:
        return [], "SKIP"
    if task.status != "SUCCEEDED":
        return [], "INCOMPLETE"
    payload = task.payload or {}
    trace = _trace_entries(payload)
    product_id = payload.get("selected_product")
    product_tool_entries = [entry for entry in trace if entry.get("tool") in PRODUCT_TOOL_NAMES]
    if product_id is None:
        found_ids = {
            entry["arguments"].get("product_id") for entry in product_tool_entries
            if isinstance(entry["arguments"].get("product_id"), int)
        }
        if len(found_ids) != 1:
            return [], ("AMBIGUOUS" if found_ids else "SKIP")
        product_id = found_ids.pop()
    if not isinstance(product_id, int) or isinstance(product_id, bool):
        return [], "SKIP"
    facts = [entry for entry in product_tool_entries if entry["arguments"].get("product_id") == product_id]
    if not facts:
        return [], "SKIP"
    unit_id, product_name = _catalog_unit(trace, product_id)
    rfq_item_id = payload.get("selected_rfq_item")
    if not isinstance(rfq_item_id, int):
        candidates = {
            entry["arguments"].get("rfq_item_id") for entry in facts
            if entry.get("tool") == "supplier_quotes.compare" and isinstance(entry["arguments"].get("rfq_item_id"), int)
        }
        rfq_item_id = candidates.pop() if len(candidates) == 1 else None
    anchors = tuple(
        {"tool": entry["tool"], "arguments": entry["arguments"],
         "fingerprint": result_fingerprint(entry["result"]), "step": entry.get("step")}
        for entry in facts
    )
    return [DraftSource(kind="agent", message_id=message_id, task_id=task_id, revision=task.revision,
                        product_id=product_id, unit_id=unit_id, product_name=product_name,
                        rfq_item_id=rfq_item_id, anchors=anchors)], None


def _batch_candidates(message: AIMessage) -> tuple[list[DraftSource], str | None]:
    sources: list[DraftSource] = []
    incomplete = False
    for citation in message.citations or []:
        if not isinstance(citation, dict) or citation.get("type") != "multi_intent":
            continue
        report = citation.get("batch")
        if not isinstance(report, dict):
            continue
        for task in report.get("tasks") or []:
            if not isinstance(task, dict) or task.get("kind") not in {"inventory", "quotes"}:
                continue
            if task.get("status") != "SUCCEEDED":
                incomplete = True
                continue
            calls = [call for call in task.get("tool_calls") or []
                     if isinstance(call, dict) and isinstance(call.get("arguments"), dict)]
            product_ids = {
                call["arguments"].get("product_id") for call in calls
                if call.get("tool") in PRODUCT_TOOL_NAMES
                and isinstance(call["arguments"].get("product_id"), int)
            }
            if len(product_ids) != 1:
                if product_ids:
                    return [], "AMBIGUOUS"
                continue
            product_id = product_ids.pop()
            # 批次执行按顺序同时追加 tool_calls 与 evidence，可用同一位置对应。
            evidence = [item for item in task.get("evidence") or [] if isinstance(item, dict)]
            anchors = []
            for index, call in enumerate(calls):
                if call.get("tool") not in PRODUCT_TOOL_NAMES or index >= len(evidence):
                    continue
                anchors.append({"tool": call["tool"], "arguments": call["arguments"],
                                "fingerprint": result_fingerprint(evidence[index])})
            unit_id, product_name = None, None
            for item in task.get("evidence") or []:
                if not isinstance(item, dict) or item.get("tool") != "catalog.search_products":
                    continue
                for row in item.get("rows") or []:
                    if isinstance(row, dict) and row.get("product_id") == product_id:
                        unit_id, product_name = row.get("unit_id"), row.get("product_name")
            rfq_item_id = None
            rfq_candidates = {
                call["arguments"].get("rfq_item_id") for call in calls
                if call.get("tool") == "supplier_quotes.compare"
                and isinstance(call["arguments"].get("rfq_item_id"), int)
            }
            if len(rfq_candidates) == 1:
                rfq_item_id = rfq_candidates.pop()
            sources.append(DraftSource(
                kind="batch", message_id=message.id, product_id=product_id, unit_id=unit_id,
                product_name=product_name, rfq_item_id=rfq_item_id,
                subtask_id=task.get("id"), anchors=tuple(anchors)))
    if not sources and incomplete:
        return [], "INCOMPLETE"
    return sources, None


def _message_sources(db: Session, user: User, conversation_id: int,
                     message: AIMessage) -> tuple[list[DraftSource], str | None]:
    sources: list[DraftSource] = []
    for citation in message.citations or []:
        if not isinstance(citation, dict):
            continue
        if citation.get("type") == "agent_task" and citation.get("task_id"):
            found, status = _agent_candidates(db, user, conversation_id, message.id, str(citation["task_id"]))
            if status is not None and status != "SKIP":
                return [], status
            sources.extend(found)
    batch_sources, batch_status = _batch_candidates(message)
    if batch_status is not None:
        return [], batch_status
    sources.extend(batch_sources)
    return sources, None


def resolve_draft_source(
    db: Session, user: User, conversation_id: int,
) -> SourceResolution:
    """按会话消息顺序定位最近一次相关查询；多对象或未完成时追问，不回退旧任务。"""

    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    if "SYS_ADMIN" not in roles and "master.products.read" not in permissions:
        return SourceResolution(reason="PERMISSION")

    conversation = conversation_store.get_owned_conversation(db, user, conversation_id)
    messages = list(db.scalars(
        select(AIMessage)
        .where(AIMessage.conversation_id == conversation.id)
        .order_by(AIMessage.id.desc())
        .limit(20)
    ).all())
    for message in messages:
        found, status = _message_sources(db, user, conversation.id, message)
        if status == "INCOMPLETE":
            return SourceResolution(reason="INCOMPLETE")
        if status == "AMBIGUOUS" or len(found) > 1:
            return SourceResolution(reason="AMBIGUOUS")
        if len(found) == 1:
            validated = _validated_source(db, found[0])
            return SourceResolution(source=validated) if validated else SourceResolution(reason="STALE")
    return SourceResolution(reason="NO_SOURCE")


def _validated_source(db: Session, source: DraftSource) -> DraftSource | None:
    product = db.scalar(select(Product).where(Product.id == source.product_id))
    if product is None or product.status != "ACTIVE":
        return None
    return replace(source, unit_id=product.unit_id, product_name=product.product_name)


def restore_bridge_source(
    db: Session, user: User, conversation_id: int, bridge: dict,
) -> DraftSource | None:
    """按已固定的锚点重新核验来源，避免另一轮查询静默替换当前缺项草稿。"""

    raw_source = bridge.get("source")
    if not isinstance(raw_source, dict):
        return None
    message_id = raw_source.get("message_id")
    product_id = raw_source.get("product_id")
    if not isinstance(message_id, int) or not isinstance(product_id, int):
        return None
    message = db.scalar(select(AIMessage).where(
        AIMessage.id == message_id, AIMessage.conversation_id == conversation_id))
    if message is None:
        return None
    if raw_source.get("kind") == "agent":
        task_id = raw_source.get("task_id")
        if not isinstance(task_id, str):
            return None
        found, status = _agent_candidates(db, user, conversation_id, message.id, task_id)
        if status is not None or len(found) != 1:
            return None
        source = found[0]
        if source.product_id != product_id or source.revision != raw_source.get("revision"):
            return None
        return _validated_source(db, source)
    if raw_source.get("kind") == "batch":
        found, status = _batch_candidates(message)
        if status is not None:
            return None
        for source in found:
            if source.product_id == product_id and source.subtask_id == raw_source.get("subtask_id"):
                return _validated_source(db, source)
    return None


def collect_reference_facts(
    db: Session, user: User, source: DraftSource, product: Product,
) -> tuple[list[dict], dict, list[str]]:
    """按当前权限重新查询来源产品的库存与报价事实，返回证据、提示与摘要。"""

    evidence: list[dict] = []
    warnings: list[str] = []
    facts: dict = {
        "product": {"product_id": product.id, "product_name": product.product_name,
                    "unit_id": product.unit_id},
    }
    inventory_call = ToolCall(tool="inventory.query_available", arguments={"product_id": product.id})
    try:
        inventory = agent_tools.execute_tool(db, user, inventory_call)
        evidence.append(tool_evidence("授权库存", inventory_call, inventory, source=source))
        dumped = inventory.model_dump(mode="json")
        facts["inventory"] = {"scope": dumped.get("scope"), "totals": dumped.get("totals") or []}
    except AuthorizationError:
        warnings.append("当前账号无授权库存读取权限，未查询该项来源。")
    except (BusinessValidationError, ResourceNotFoundError):
        warnings.append("来源产品的库存事实暂时无法读取，请稍后重试。")

    rfq_call = ToolCall(tool="supplier_quotes.find_rfq_items", arguments={"product_id": product.id, "limit": 10})
    try:
        rfqs = agent_tools.execute_tool(db, user, rfq_call)
        evidence.append(tool_evidence("可见询价明细", rfq_call, rfqs, source=source))
        rows = rfqs.model_dump(mode="json").get("rows") or []
        if rfqs.total_rows > 1 or rfqs.truncated:
            warnings.append("该产品有多个可见询价明细；未自动选择其中任一项。")
        elif rfqs.total_rows == 1:
            rfq_item_id = rows[0]["rfq_item_id"]
            if source.rfq_item_id is not None and source.rfq_item_id != rfq_item_id:
                warnings.append("来源询价明细已变化；未沿用原询价事实。")
            else:
                compare_call = ToolCall(tool="supplier_quotes.compare",
                                        arguments={"product_id": product.id, "rfq_item_id": rfq_item_id})
                comparison = agent_tools.execute_tool(db, user, compare_call)
                evidence.append(tool_evidence("有效报价", compare_call, comparison, source=source))
                dumped = comparison.model_dump(mode="json")
                facts["quotes"] = {"rfq_no": dumped.get("rfq_no"), "rfq_item_id": rfq_item_id,
                                   "rows": (dumped.get("rows") or [])[:10]}
    except AuthorizationError:
        warnings.append("当前账号无询价报价读取权限，未查询该项来源。")
    except (BusinessValidationError, ResourceNotFoundError):
        warnings.append("来源产品的报价事实暂时无法读取，请稍后重试。")
    return evidence, facts, warnings


def bridge_requirements(draft: dict) -> dict:
    """只保存用户已提供的字段，不把目录注释或来源事实写进需求。"""

    return {
        "purpose": draft.get("purpose") or "",
        "priority": draft.get("priority") or "NORMAL",
        "budget_amount": draft.get("budget_amount"),
        "currency_code": draft.get("currency_code") or "CNY",
        "expected_date": draft.get("expected_date"),
        "items": [
            {key: item.get(key) for key in
             ("requested_name", "quantity", "unit_id", "technical_requirements", "budget_price", "expected_date")}
            for item in draft.get("items") or []
            if isinstance(item, dict)
        ],
    }


def build_bridge(source: DraftSource, requirements: dict, missing_fields: list[str],
                 *, question: str | None) -> dict:
    bridge = {
        "source": source.reference(),
        "requirements": requirements,
        "missing_fields": list(dict.fromkeys(missing_fields))[:8],
    }
    if question:
        bridge["user_message_hash"] = hashlib.sha256(question.encode("utf-8")).hexdigest()
    return bridge
