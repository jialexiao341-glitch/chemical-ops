"""请求链路、结构化日志和轻量运行指标。"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import hashlib
from threading import Lock
from time import perf_counter
from typing import Iterator
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
trace_id_context: ContextVar[str] = ContextVar("trace_id", default="-")


def _incoming_id(value: str | None) -> str:
    """只接受可打印且有长度上限的链路 ID，避免日志注入。"""

    candidate = (value or "").strip()
    if not candidate or len(candidate) > 128 or any(ord(char) < 32 for char in candidate):
        return uuid4().hex
    return candidate


def get_request_id() -> str:
    return request_id_context.get()


def get_trace_id() -> str:
    return trace_id_context.get()


class JsonFormatter(logging.Formatter):
    """输出单行 JSON，方便 Loki/ELK/Cloud Logging 直接采集。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
            "trace_id": getattr(record, "trace_id", get_trace_id()),
        }
        for key in ("event", "duration_ms", "status_code", "method", "path", "component", "sql_hash"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@dataclass
class _Metric:
    count: int = 0
    total: float = 0.0
    maximum: float = 0.0


class MetricsRegistry:
    """进程内指标注册表；多进程部署时由每个 worker 暴露独立指标。"""

    def __init__(self) -> None:
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], _Metric] = defaultdict(_Metric)
        self._lock = Lock()

    @staticmethod
    def _key(name: str, labels: dict[str, object] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
        normalised = tuple(sorted((key, str(value)) for key, value in (labels or {}).items()))
        return name, normalised

    @staticmethod
    def _escape_label(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def increment(self, name: str, *, labels: dict[str, object] | None = None, value: float = 1.0) -> None:
        key = self._key(name, labels)
        with self._lock:
            metric = self._values[key]
            metric.count += int(value)
            metric.total += value

    def observe(self, name: str, value: float, *, labels: dict[str, object] | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            metric = self._values[key]
            metric.count += 1
            metric.total += value
            metric.maximum = max(metric.maximum, value)

    def render_prometheus(self) -> str:
        """渲染简单 Counter/Summary 指标，不暴露请求参数或文件内容。"""

        lines = ["# TYPE chemicalops_metric counter"]
        with self._lock:
            values = list(self._values.items())
        for (name, labels), metric in sorted(values):
            safe_name = "chemicalops_" + "".join(char if char.isalnum() or char == "_" else "_" for char in name)
            label_text = ""
            if labels:
                encoded = [f'{key}="{self._escape_label(value)}"' for key, value in labels]
                label_text = "{" + ",".join(encoded) + "}"
            lines.append(f"{safe_name}_count{label_text} {metric.count}")
            lines.append(f"{safe_name}_total{label_text} {metric.total:.6f}")
            if metric.maximum:
                lines.append(f"{safe_name}_max{label_text} {metric.maximum:.6f}")
        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()


@contextmanager
def observe_duration(name: str, *, labels: dict[str, object] | None = None) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        metrics.observe(name, perf_counter() - started, labels=labels)


class RequestContextMiddleware:
    """为每个请求注入 request/trace ID、响应头、访问日志和 API 指标。"""

    def __init__(self, app: ASGIApp, slow_request_ms: float = 1000.0) -> None:
        self.app = app
        self.slow_request_ms = slow_request_ms

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        request_id = _incoming_id(headers.get("x-request-id"))
        trace_id = _incoming_id(headers.get("x-trace-id") or request_id)
        request_token = request_id_context.set(request_id)
        trace_token = trace_id_context.set(trace_id)
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id
        scope["state"]["trace_id"] = trace_id
        started = perf_counter()
        status_code = 500
        try:
            async def send_with_context(message: Message) -> None:
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = int(message["status"])
                    response_headers = list(message.get("headers", []))
                    response_headers.extend(((b"x-request-id", request_id.encode()), (b"x-trace-id", trace_id.encode())))
                    message = {**message, "headers": response_headers}
                await send(message)

            await self.app(scope, receive, send_with_context)
        except Exception:
            metrics.increment("api_requests", labels={"status": "exception"})
            raise
        finally:
            duration = perf_counter() - started
            route = getattr(scope.get("route"), "path", None) or scope.get("path", "unknown")
            metrics.increment("api_requests", labels={"method": scope.get("method", "UNKNOWN"), "path": route, "status": status_code})
            metrics.observe("api_request_duration_seconds", duration, labels={"method": scope.get("method", "UNKNOWN"), "path": route})
            logger = logging.getLogger("chemicalops.http")
            level = logging.WARNING if duration * 1000 >= self.slow_request_ms or status_code >= 500 else logging.INFO
            logger.log(level, "HTTP request completed", extra={"event": "http_request", "duration_ms": round(duration * 1000, 2), "status_code": status_code, "method": scope.get("method", "UNKNOWN"), "path": route})
            request_id_context.reset(request_token)
            trace_id_context.reset(trace_token)


def log_context() -> dict[str, str]:
    """供后台任务和外部调用日志附带当前链路标识。"""

    return {"request_id": get_request_id(), "trace_id": get_trace_id()}
