"""可选 OpenTelemetry trace provider 与跨任务上下文传播。"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from typing import Iterator

from app.core.config import get_settings


_provider = None


def tracer_for(component: str):
    """获取组件 tracer；OTel SDK 未安装或关闭时返回无操作 tracer。"""

    try:
        from opentelemetry import trace
    except ImportError:
        return None
    return trace.get_tracer(f"chemicalops.{component}")


@contextmanager
def trace_span(name: str, attributes: dict[str, str | int | bool] | None = None) -> Iterator[object | None]:
    tracer = tracer_for("application")
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            span.set_attribute(key, value)
        yield span


def inject_trace_context(payload: dict) -> dict:
    """将当前 API span 的 W3C trace context 随持久任务传给 Worker。"""

    if not get_settings().otel_enabled:
        return payload
    from opentelemetry import propagate

    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return {**payload, "_otel_context": carrier} if carrier else payload


def configure_tracing(*, app=None, engine=None, service_name: str | None = None) -> None:
    """按需配置 OTLP/HTTP 导出以及 FastAPI、SQLAlchemy、HTTPX 自动 spans。"""

    global _provider
    settings = get_settings()
    if not settings.otel_enabled or _provider is not None:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({
        "service.name": service_name or settings.otel_service_name,
    }))
    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    if endpoint:
        endpoint = endpoint.rstrip("/")
        if not endpoint.endswith("/v1/traces"):
            endpoint += "/v1/traces"
        exporter = OTLPSpanExporter(endpoint=endpoint)
    else:
        exporter = OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    if app is not None:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=provider)
    _provider = provider


def extract_carrier(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return {str(key): str(item) for key, item in value.items()} if isinstance(value, dict) else {}


def worker_trace_carrier() -> dict[str, str]:
    return extract_carrier(os.getenv("CHEMICALOPS_TRACE_CONTEXT", ""))


def current_trace_id() -> str | None:
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    span_context = trace.get_current_span().get_span_context()
    return f"{span_context.trace_id:032x}" if span_context.is_valid else None


def shutdown_tracing() -> None:
    if _provider is not None:
        _provider.shutdown()
