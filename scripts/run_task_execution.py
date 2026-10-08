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
    from app.modules.task_queue.execution import run
    asyncio.run(run())


if __name__ == "__main__":
    main()
