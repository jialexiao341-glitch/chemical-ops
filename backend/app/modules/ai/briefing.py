"""AI 运营晨报：聚合现有统计 → LLM 生成中文简报 → 可选站内通知。

只读设计：快照来自 dashboard 的既有聚合查询，LLM 只负责把数字写成
人话；push=True 时按角色发送站内通知（notify_users 不提交事务，
由这里统一 commit 并写审计）。
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError
from app.modules.ai.schema import (
    AIChatMessage,
    AIChatRequest,
    BriefingRequest,
    BriefingResponse,
)
from app.modules.ai.llm import chat
from app.modules.ai.numeric_fidelity import faithful_numbers
from app.modules.dashboard.service import get_overview, get_report
from app.modules.notifications.service import notify_users
from app.modules.system.audit import add_audit_log
from app.modules.system.model import User
from app.modules.system.crud import get_user_role_codes

DEFAULT_NOTIFY_ROLES = ("SYS_ADMIN", "PROCUREMENT_MANAGER")


def json_safe(value: Any) -> Any:
    """把 Decimal/date/datetime 递归转成 JSON 可序列化的值。"""

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def build_snapshot(db: Session, *, user: User | None = None) -> dict[str, Any]:
    """聚合晨报需要的指标快照（全部来自 dashboard 既有查询）。"""

    from app.modules.system.data_scope import is_department_restricted
    if user is not None and is_department_restricted(db, user):
        from app.modules.dashboard.service import get_department_overview, get_department_report
        overview = get_department_overview(db, user)
        report = get_department_report(db, user, date_from=None, date_to=None)
    else:
        overview = get_overview(db)
        report = get_report(db, date_from=None, date_to=None)
    trend = report.get("order_trend") or []
    return json_safe(
        {
            "date": date.today().isoformat(),
            "overview": overview,
            "pending_tasks": report.get("pending_tasks") or [],
            # 最近 7 天的采购趋势（order_trend 默认 30 天）
            "order_trend_last_7_days": trend[-7:],
            "top_suppliers": (report.get("supplier_performance") or [])[:5],
            "expiry_alerts": (report.get("inventory_alerts") or [])[:5],
        }
    )


def build_prompt(snapshot: dict[str, Any]) -> str:
    """生成晨报提示词；只允许基于给定快照，禁止编造数字。"""

    return (
        "你是 ChemicalOps 化工采购运营平台的运营助理。"
        "请根据下面的「数据快照」生成一份中文运营晨报，要求：\n"
        "1. 全文不超过 300 字；\n"
        "2. 使用三段结构：【概览】【需关注】【建议】；\n"
        "3. 只引用快照中出现的数字与名称，禁止编造；"
        "没有值得关注的内容时如实说「今日无异常」；\n"
        "4. 数值逐值复制为阿拉伯数字，不换算单位，不写中文数字或万/亿，不用数字序号。语言口语化、可直接发给管理层阅读。\n\n"
        f"数据快照：\n{json.dumps(snapshot, ensure_ascii=False)}"
    )


async def generate_briefing(
    db: Session, user: User, request: BriefingRequest
) -> BriefingResponse:
    """生成运营晨报；request.push=True 时同时发送站内通知。"""
    from app.modules.system.data_scope import is_department_restricted
    restricted = is_department_restricted(db, user)

    can_push = {"SYS_ADMIN", "PROCUREMENT_MANAGER"} & set(
        get_user_role_codes(db, user.id)
    )
    if request.push and not can_push:
        raise AuthorizationError("只有系统管理员或采购经理可以推送运营晨报")
    if request.push and restricted:
        raise AuthorizationError("部门范围晨报暂不支持跨用户推送")

    snapshot = build_snapshot(db, user=user)
    result = await chat(
        AIChatRequest(
            messages=[AIChatMessage(role="user", content=build_prompt(snapshot))],
        )
    )
    content = result.answer or result.message.content
    if not faithful_numbers(content, snapshot):
        overview = snapshot.get("overview", {})
        labels = {"purchase_orders_total": "采购订单总数", "purchase_orders_in_progress": "进行中订单",
                  "deliveries_overdue": "逾期到货", "open_exceptions": "未关闭异常", "expiry_alerts": "效期预警"}
        facts = "；".join(f"{label}：{overview[key]}" for key, label in labels.items() if overview.get(key) is not None)
        content = f"【概览】{facts or '暂无汇总指标'}。\n【需关注】请按快照核对逾期、异常与效期明细。\n【建议】结合单据明细安排处理。"

    pushed = False
    notified_count = 0
    if request.push:
        role_codes = request.notify_role_codes or list(DEFAULT_NOTIFY_ROLES)
        notifications = notify_users(
            db,
            role_codes=role_codes,
            exclude_scoped=True,
            notification_type="AI_BRIEFING",
            title=f"AI 运营晨报 {snapshot['date']}",
            content=content,
        )
        notified_count = len(notifications)
        add_audit_log(
            db,
            actor_id=user.id,
            action_type="BRIEFING",
            resource_type="AI_BRIEFING",
            resource_id=None,
            request_summary=f"生成并推送 AI 晨报（角色 {','.join(role_codes)}，{notified_count} 人）",
            result_status="SUCCESS",
        )
        db.commit()
        pushed = True

    return BriefingResponse(
        content=content,
        snapshot=snapshot,
        model=result.model,
        provider=result.provider,
        generated_at=datetime.now(),
        pushed=pushed,
        notified_count=notified_count,
    )
