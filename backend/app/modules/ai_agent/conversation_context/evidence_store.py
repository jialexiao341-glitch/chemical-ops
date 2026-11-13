"""任务轨迹的受控续读。

工具结果保存的是执行时快照；这里按稳定引用分页返回，并在每次读取时
重新校验任务归属、当前权限和数据范围。引用本身不授予任何新权限。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai_agent.model import AIAgentTask
from app.modules.ai_agent.schema import EvidencePage, EvidenceReadInput
from app.modules.system_management.model import User


REF_PATTERN = re.compile(r"^task:([0-9a-f]{32})/step:(\d{1,6})$")
# 库存、报价和补货缺口会随业务变化，历史快照不能当作当前事实。
VOLATILE_TOOLS = frozenset({
    "inventory.query_available",
    "inventory.replenishment_plan",
    "supplier_quotes.find_rfq_items",
    "supplier_quotes.compare",
})
LIST_FIELDS = ("rows", "sources", "sections", "items", "stages", "reviews", "documents", "lines")


def make_ref(task_id: str, step: int) -> str:
    """生成任务轨迹步骤的稳定引用。"""
    return f"task:{task_id}/step:{int(step)}"


def parse_ref(ref: str) -> tuple[str, int]:
    match = REF_PATTERN.fullmatch(ref)
    if match is None:
        raise BusinessValidationError("证据引用格式无效")
    return match.group(1), int(match.group(2))


def _list_field(payload: dict[str, Any]) -> str | None:
    return next((key for key in LIST_FIELDS if isinstance(payload.get(key), list)), None)


def read_evidence(db: Session, user: User, arguments: EvidenceReadInput) -> EvidencePage:
    """读取当前用户本人任务中的一页工具结果；不返回其他任务或未成功步骤。"""
    task_id, step = parse_ref(arguments.ref)
    task = db.scalar(select(AIAgentTask).where(AIAgentTask.id == task_id))
    if task is None or task.user_id != user.id:
        raise ResourceNotFoundError("证据引用不存在")
    if str(getattr(user, "status", "ACTIVE")) != "ACTIVE":
        raise AuthorizationError("用户已停用，不能读取历史证据")
    trace = (task.payload or {}).get("trace") or []
    entry = next((item for item in trace if item.get("step") == step), None)
    if entry is None or entry.get("action") != "call_tool" or entry.get("status") != "SUCCEEDED":
        raise BusinessValidationError("证据引用不存在或该步骤未成功")
    result = entry.get("result")
    if not isinstance(result, dict):
        raise BusinessValidationError("该步骤没有可续读的结构化结果")

    # 读取时按当前权限重验原始工具的数据范围；授权变化后旧结果不可继续读取。
    from app.modules.ai_agent.agent_execution import agent_runtime
    agent_runtime._check_trace_access(db, user, [entry])

    volatile = entry["tool"] in VOLATILE_TOOLS
    captured_at = entry.get("captured_at") or (
        task.updated_at.isoformat() if task.updated_at is not None else None
    )
    note = (
        "该结果是任务执行时的历史快照，不代表当前库存、报价或补货缺口；需要当前值请重新调用对应业务工具。"
        if volatile else
        "该结果是任务执行时的历史快照，后续业务变化不会自动更新；引用只用于追溯已展示过的内容。"
    )
    field = _list_field(result)
    settings = get_settings()
    budget = settings.agent_evidence_page_chars

    if field is None:
        text = json.dumps(result, ensure_ascii=False, default=str)
        start = arguments.offset
        end = min(len(text), start + budget)
        return EvidencePage(
            ref=arguments.ref, tool=entry["tool"], captured_at=captured_at,
            volatile=volatile, note=note, list_field=None, total_rows=None,
            offset=start, returned=end - start if end > start else 0,
            next_offset=end if end < len(text) else None,
            fragment=text[start:end] if end > start else "",
        )

    rows = result[field]
    total = len(rows)
    if arguments.offset >= total:
        return EvidencePage(
            ref=arguments.ref, tool=entry["tool"], captured_at=captured_at,
            volatile=volatile, note=note, list_field=field, total_rows=total,
            offset=arguments.offset, returned=0, next_offset=None, rows=[],
        )
    page = [row if isinstance(row, dict) else {"value": row}
            for row in rows[arguments.offset: arguments.offset + arguments.limit]]
    # 单页序列化后不得超过预算；只缩减本页，不改变原始结果。
    while len(page) > 1 and len(json.dumps(page, ensure_ascii=False, default=str)) > budget:
        page.pop()
    if page and len(json.dumps(page, ensure_ascii=False, default=str)) > budget:
        # 单条记录本身超预算时退化为片段，避免返回无法校验的超大对象。
        text = json.dumps(page[0], ensure_ascii=False, default=str)
        return EvidencePage(
            ref=arguments.ref, tool=entry["tool"], captured_at=captured_at,
            volatile=volatile, note=note, list_field=field, total_rows=total,
            offset=arguments.offset, returned=1,
            next_offset=arguments.offset + 1 if arguments.offset + 1 < total else None,
            fragment=text[:budget],
        )
    start = arguments.offset
    returned = len(page)
    return EvidencePage(
        ref=arguments.ref, tool=entry["tool"], captured_at=captured_at,
        volatile=volatile, note=note, list_field=field, total_rows=total,
        offset=start, returned=returned,
        next_offset=start + returned if start + returned < total else None,
        rows=page,
    )