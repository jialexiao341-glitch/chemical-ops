"""Internal gated task process; only an assigned supervisor can start execution."""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.task_queue import context, processes


def main():
    if not context.identity() or not os.environ.get("CHEMICALOPS_WORKER_PID"):
        raise SystemExit("Managed execution identity required")
    processes.supervise_linux_parent()
    if sys.stdin.readline().strip() != "start":
        raise SystemExit("Supervisor did not start task")
    from opentelemetry import context as otel_context, propagate, trace
    from app.core.db import engine
    from app.core.telemetry import configure_tracing, shutdown_tracing, worker_trace_carrier

    configure_tracing(engine=engine, service_name="chemicalops-task-worker")
    parent = propagate.extract(worker_trace_carrier())
    context_token = otel_context.attach(parent)
    from app.modules.task_queue.execution import run
    try:
        with trace.get_tracer("chemicalops.worker").start_as_current_span("task.execute") as span:
            span.set_attribute("chemicalops.execution.id", context.identity()[0])
            asyncio.run(run())
    finally:
        otel_context.detach(context_token)
        shutdown_tracing()


if __name__ == "__main__":
    main()
