"""Standalone Linux container acceptance, no dependencies beyond Python stdlib."""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.modules.task_queue.processes import stop_process


def stopped(pid):
    status = Path(f"/proc/{pid}/stat")
    return not status.exists() or status.read_text().split()[2] == "Z"


async def main():
    child_code = (
        f"import sys,subprocess,time; sys.path.insert(0,{str(ROOT / 'backend')!r}); "
        "from app.modules.task_queue.processes import supervise_linux_parent; supervise_linux_parent(); "
        "descendant=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "print(descendant.pid,flush=True); time.sleep(60)"
    )
    env = {**os.environ, "CHEMICALOPS_WORKER_PID": str(os.getpid())}
    child = await asyncio.create_subprocess_exec(sys.executable, "-c", child_code,
        env=env, start_new_session=True, stdout=asyncio.subprocess.PIPE)
    descendant = int(await asyncio.wait_for(child.stdout.readline(), 5))
    await stop_process(child, None)
    assert stopped(child.pid) and stopped(descendant)
    supervisor_code = (
        "import sys,os,subprocess,json,time; "
        "env={**os.environ,'CHEMICALOPS_WORKER_PID':str(os.getpid())}; "
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}],env=env,start_new_session=True,stdout=subprocess.PIPE,text=True); "
        "descendant=int(child.stdout.readline()); print(json.dumps([child.pid,descendant]),flush=True); time.sleep(60)"
    )
    supervisor = subprocess.Popen([sys.executable, "-c", supervisor_code], stdout=subprocess.PIPE, text=True)
    try:
        tree = json.loads(supervisor.stdout.readline())
        supervisor.kill()
        supervisor.wait(timeout=5)
        deadline = time.monotonic() + 5
        while not all(stopped(pid) for pid in tree) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert all(stopped(pid) for pid in tree)
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=5)
    print("Linux group termination and abrupt parent exit: passed")


if __name__ == "__main__":
    asyncio.run(main())
