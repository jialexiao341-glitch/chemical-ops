"""Verify supervision kills descendants, not only the immediate task process."""

import asyncio
import os
import sys
import time

import pytest

from app.modules.task_queue.processes import WindowsJob, process_alive, stop_process
from pathlib import Path
import json


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object acceptance")
def test_windows_job_stops_child_and_grandchild():
    async def verify():
        code = (
            "import subprocess,sys,time; sys.stdin.readline(); "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            "print(child.pid,flush=True); time.sleep(60)"
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        )
        job = None
        try:
            job = WindowsJob(process.pid)
            process.stdin.write(b"start\n")
            await process.stdin.drain()
            descendant = int(await asyncio.wait_for(process.stdout.readline(), timeout=5))
            assert process_alive(process.pid) and process_alive(descendant)
            await asyncio.wait_for(stop_process(process, job), timeout=5)
            deadline = time.monotonic() + 5
            while process_alive(descendant) and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert not process_alive(process.pid)
            assert not process_alive(descendant)
        finally:
            if job:
                job.close()
            if process.returncode is None:
                process.kill()
                await process.wait()
    asyncio.run(verify())


@pytest.mark.skipif(os.name != "nt", reason="Windows crash acceptance")
def test_supervisor_crash_terminates_job_tree():
    async def verify():
        backend = str(Path(__file__).resolve().parents[1] / "backend")
        child_code = (
            "import subprocess,sys,time; sys.stdin.readline(); "
            "descendant=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            "print(descendant.pid,flush=True); time.sleep(60)"
        )
        supervisor_code = (
            f"import sys,subprocess,json,time; sys.path.insert(0,{backend!r}); "
            "from app.modules.task_queue.processes import WindowsJob; "
            f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True); "
            "job=WindowsJob(child.pid); child.stdin.write('start\\n'); child.stdin.flush(); "
            "descendant=int(child.stdout.readline()); print(json.dumps([child.pid,descendant]),flush=True); time.sleep(60)"
        )
        supervisor = await asyncio.create_subprocess_exec(sys.executable, "-c", supervisor_code,
            stdout=asyncio.subprocess.PIPE)
        try:
            tree = json.loads(await asyncio.wait_for(supervisor.stdout.readline(), timeout=10))
            assert all(process_alive(pid) for pid in tree)
            supervisor.kill()  # Abrupt exit, no cleanup code executes in the supervisor.
            await supervisor.wait()
            deadline = time.monotonic() + 5
            while any(process_alive(pid) for pid in tree) and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert all(not process_alive(pid) for pid in tree)
        finally:
            if supervisor.returncode is None:
                supervisor.kill()
                await supervisor.wait()
    asyncio.run(verify())


@pytest.mark.skipif(os.name != "nt", reason="Windows failed Job assignment cleanup")
def test_gated_child_is_stopped_even_without_job_handle():
    async def verify():
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(60)")
        await asyncio.wait_for(stop_process(process, None), timeout=5)
        assert not process_alive(process.pid)
    asyncio.run(verify())
