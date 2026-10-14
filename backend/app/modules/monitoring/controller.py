"""向管理员提供经过裁剪的 Prometheus 告警与采集目标状态。"""

from datetime import datetime, timezone
import asyncio
import hashlib
import json
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AuthorizationError
from app.modules.system import crud
from app.modules.system.model import User


router = APIRouter(prefix="/system/monitoring", tags=["系统监控"])


class MonitoringAlert(BaseModel):
    id: str
    name: str
    severity: str
    state: str
    summary: str
    description: str
    active_at: str | None = None


class MonitoringTarget(BaseModel):
    job: str
    instance: str
    health: str
    last_scrape: str | None = None
    last_error: str = ""


class MonitoringRule(BaseModel):
    id: str
    name: str
    state: str
    health: str
    last_evaluation: str | None = None


class MonitoringOverview(BaseModel):
    checked_at: datetime
    firing_alerts: int
    pending_alerts: int
    healthy_targets: int
    target_count: int
    rule_count: int
    alerts: list[MonitoringAlert]
    targets: list[MonitoringTarget]
    rules: list[MonitoringRule]


def _require_admin(db: Session, user: User) -> None:
    if "SYS_ADMIN" not in crud.get_user_role_codes(db, user.id):
        raise AuthorizationError("仅系统管理员可以查看运行监控")


def _build_monitoring_overview(
    alerts_data: dict[str, Any],
    targets_data: dict[str, Any],
    rules_data: dict[str, Any],
) -> MonitoringOverview:
    """裁剪 Prometheus 原始响应，避免向前端传递完整标签和规则表达式。"""

    alerts = []
    for item in alerts_data.get("alerts", []):
        labels = item.get("labels") or {}
        annotations = item.get("annotations") or {}
        alert_state = str(item.get("state") or "unknown").lower()
        if alert_state not in {"firing", "pending"}:
            continue
        alerts.append(
            MonitoringAlert(
                id=hashlib.sha256(
                    json.dumps(labels, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()[:16],
                name=str(labels.get("alertname") or "未命名告警"),
                severity=str(labels.get("severity") or "未分级"),
                state=alert_state,
                summary=str(annotations.get("summary") or "暂无摘要"),
                description=str(annotations.get("description") or ""),
                active_at=item.get("activeAt"),
            )
        )

    active_targets = targets_data.get("activeTargets") or []
    targets = [
        MonitoringTarget(
            job=str(item.get("labels", {}).get("job") or "unknown"),
            instance=str(item.get("labels", {}).get("instance") or "unknown"),
            health=str(item.get("health") or "unknown").lower(),
            last_scrape=item.get("lastScrape"),
            last_error=str(item.get("lastError") or ""),
        )
        for item in active_targets
    ]

    rules = []
    for group in rules_data.get("groups", []):
        for item in group.get("rules", []):
            if item.get("type") != "alerting":
                continue
            rules.append(
                MonitoringRule(
                    id=f"{group.get('name', '')}:{item.get('name', '')}",
                    name=str(item.get("name") or "未命名规则"),
                    state=str(item.get("state") or "inactive").lower(),
                    health=str(item.get("health") or "unknown").lower(),
                    last_evaluation=item.get("lastEvaluation"),
                )
            )

    alerts.sort(key=lambda item: (item.state != "firing", item.severity, item.name, item.id))
    targets.sort(key=lambda item: (item.health != "up", item.job, item.instance))
    rules.sort(key=lambda item: (item.state not in {"firing", "pending"}, item.name, item.id))
    return MonitoringOverview(
        checked_at=datetime.now(timezone.utc),
        firing_alerts=sum(alert.state == "firing" for alert in alerts),
        pending_alerts=sum(alert.state == "pending" for alert in alerts),
        healthy_targets=sum(target.health == "up" for target in targets),
        target_count=len(targets),
        rule_count=len(rules),
        alerts=alerts,
        targets=targets,
        rules=rules,
    )


async def _prometheus_data(client: httpx.AsyncClient, base_url: str, path: str) -> Any:
    response = await client.get(f"{base_url}/api/v1/{path}")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ValueError("Prometheus API returned an unsuccessful status")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Prometheus API returned an invalid data payload")
    return data


@router.get("/overview", response_model=MonitoringOverview, summary="查询运行监控概览")
async def get_monitoring_overview(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MonitoringOverview:
    """系统管理员查看告警、规则和采集目标；不将 Prometheus 暴露给浏览器。"""

    _require_admin(db, user)
    # 释放认证期间占用的数据库连接，再等待监控服务网络响应。
    db.commit()
    settings = get_settings()
    base_url = settings.prometheus_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=settings.monitoring_request_timeout_seconds) as client:
            responses = await asyncio.gather(
                _prometheus_data(client, base_url, "alerts"),
                _prometheus_data(client, base_url, "targets"),
                _prometheus_data(client, base_url, "rules"),
                return_exceptions=True,
            )
            failure = next((item for item in responses if isinstance(item, BaseException)), None)
            if failure is not None:
                raise failure
            alerts_data, targets_data, rules_data = responses
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prometheus 监控暂不可用，请稍后刷新",
        ) from exc
    return _build_monitoring_overview(alerts_data, targets_data, rules_data)
