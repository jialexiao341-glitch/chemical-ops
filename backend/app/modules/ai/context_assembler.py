"""按 token 与字符预算装配只读规划上下文。"""

import copy
import json
from dataclasses import dataclass

from app.core.errors import BusinessValidationError

PLANNER_RESULT_ROW_LIMIT = 10


def _clip_planner_text(value: str, limit: int) -> str:
    """压缩规划输入文本并保留首尾，尽量保住实体名、条件和末尾补充。"""
    if len(value) <= limit:
        return value
    marker = "…[上下文已裁剪]…"
    available = max(0, limit - len(marker))
    head = available // 2
    return value[:head] + marker + value[-(available - head):]


def _compact_planner_step(step: dict, *, keep_rows: int, text_limit: int) -> dict:
    """保留证据步骤及摘要字段，缩减该步骤对规划上下文的占用。"""
    compact = {key: value for key, value in step.items() if key != "result"}
    for key in ("tool", "status", "step", "action"):
        if key in step:
            compact[key] = step[key]
    arguments = step.get("arguments")
    if isinstance(arguments, dict):
        compact["arguments"] = arguments
    result = step.get("result")
    if not isinstance(result, dict):
        if result is not None:
            compact["result"] = _clip_planner_text(str(result), text_limit)
        return compact
    keys = (
        "tool", "product_id", "product_name", "keyword", "rfq_item_id", "rfq_no",
        "total_rows", "truncated", "totals", "planner_truncated", "planner_note",
        "planner_sources_truncated", "scope", "warnings", "rows", "sources",
        "request_no", "po_no", "purpose", "status", "items", "answer", "stages",
        "conclusion", "unavailable_stages", "source_records", "recommendation",
    )
    compact_result = {key: result[key] for key in keys if key in result}
    for key in ("rows", "sources", "warnings"):
        values = compact_result.get(key)
        if isinstance(values, list):
            compact_result[key] = values[:keep_rows]
    compact_result = _clip_planner_tree(compact_result, text_limit)
    if isinstance(result.get("rows"), list) and len(result["rows"]) > len(compact_result.get("rows", [])):
        compact_result["planner_truncated"] = True
        compact_result.setdefault("planner_note", "规划上下文已压缩明细；完整结果仍保存在任务证据中。")
    if isinstance(result.get("sources"), list) and len(result["sources"]) > len(compact_result.get("sources", [])):
        compact_result["planner_sources_truncated"] = True
    compact["result"] = compact_result
    return compact


def _clip_planner_tree(value, text_limit: int):
    """递归限制非关键说明和数组，避免单个字段绕过行数限制。"""
    if isinstance(value, str):
        return _clip_planner_text(value, text_limit)
    if isinstance(value, list):
        return [_clip_planner_tree(item, text_limit) for item in value]
    if isinstance(value, dict):
        return {key: _clip_planner_tree(item, text_limit) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class ContextStats:
    estimated_tokens: int
    max_tokens: int
    truncated_sections: list[str]


def estimate_tokens(text: str) -> int:
    """按非 ASCII 字符和四个 ASCII 字符估算输入 token。"""
    non_ascii = sum(1 for char in text if ord(char) > 127)
    return non_ascii + (len(text) - non_ascii + 3) // 4


def assemble_planner_context(payload: dict, *, max_tokens: int, max_chars: int) -> tuple[str, ContextStats]:
    """保留任务目标、已核验对象及证据步骤，逐级压缩规划输入副本。"""
    if max_tokens < 1 or max_chars < 1:
        raise BusinessValidationError("CONTEXT_LIMIT")
    fitted = copy.deepcopy(payload)
    truncated: list[str] = []

    def mark(section: str) -> None:
        if section not in truncated:
            truncated.append(section)

    def serialize() -> str:
        return json.dumps(fitted, ensure_ascii=False)

    def fits(text: str) -> bool:
        return len(text) <= max_chars and estimate_tokens(text) <= max_tokens

    def finish(text: str) -> tuple[str, ContextStats]:
        return text, ContextStats(estimate_tokens(text), max_tokens, truncated)

    steps = fitted.get("current_turn_steps")
    if isinstance(steps, list):
        quota = max(128, max_tokens // max(4, len(steps)))
        for index, step in enumerate(steps):
            if isinstance(step, dict) and isinstance(step.get("result"), dict):
                if step["result"].get("planner_truncated") or step["result"].get("planner_sources_truncated"):
                    mark("tool_results")
                if estimate_tokens(json.dumps(step["result"], ensure_ascii=False)) > quota:
                    compact = _compact_planner_step(step, keep_rows=3, text_limit=500)
                    if estimate_tokens(json.dumps(compact["result"], ensure_ascii=False)) > quota:
                        compact = _compact_planner_step(step, keep_rows=0, text_limit=180)
                    if estimate_tokens(json.dumps(compact["result"], ensure_ascii=False)) > quota:
                        raise BusinessValidationError("CONTEXT_LIMIT")
                    steps[index] = compact
                    mark("tool_results")

    context = serialize()
    if fits(context):
        return finish(context)

    messages = fitted.get("messages")
    if isinstance(messages, list) and messages:
        fitted["messages"] = [*(_clip_planner_text(str(item), 320) for item in messages[-3:-1]),
                               _clip_planner_text(str(messages[-1]), 1800)]
        if fitted["messages"] != messages:
            mark("messages")
    memory = fitted.get("recent_task_memory")
    if isinstance(memory, dict):
        original_memory = copy.deepcopy(memory)
        recent = memory.get("recent_context")
        if isinstance(recent, list):
            memory["recent_context"] = [
                {**item, "text": _clip_planner_text(str(item.get("text", "")), 320)}
                if isinstance(item, dict) else _clip_planner_text(str(item), 320)
                for item in recent[-3:]]
        goal = memory.get("goal")
        if isinstance(goal, dict):
            for key in ("description", "last_user_input"):
                if isinstance(goal.get(key), str):
                    goal[key] = _clip_planner_text(goal[key], 700)
        for key in ("focus", "pending"):
            section = memory.get(key)
            if isinstance(section, dict) and isinstance(section.get("candidates"), list):
                section["candidates"] = section["candidates"][:PLANNER_RESULT_ROW_LIMIT]
        if memory != original_memory:
            mark("memory")
    context = serialize()
    if fits(context):
        return finish(context)

    if isinstance(steps, list):
        compact = [_compact_planner_step(step, keep_rows=3, text_limit=500) if isinstance(step, dict) else step for step in steps]
        if compact != steps:
            mark("tool_results")
        fitted["current_turn_steps"] = compact
        steps = compact
    context = serialize()
    if fits(context):
        return finish(context)

    if isinstance(messages, list) and messages:
        fitted["messages"] = [_clip_planner_text(str(messages[-1]), 1200)]
        mark("messages")
    if isinstance(memory, dict):
        summary = {key: memory[key] for key in ("goal", "focus", "slots", "pending", "evidence_ref", "recent_context") if key in memory}
        fitted["recent_task_memory"] = summary
        mark("memory")
    if isinstance(steps, list):
        fitted["current_turn_steps"] = [_compact_planner_step(step, keep_rows=0, text_limit=180) if isinstance(step, dict) else step for step in steps]
        mark("tool_results")
    context = serialize()
    if not fits(context):
        raise BusinessValidationError("CONTEXT_LIMIT")
    return finish(context)


