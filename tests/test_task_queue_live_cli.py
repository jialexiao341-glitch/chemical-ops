"""Opt-in fault exercise: briefly stop only the project's RabbitMQ container.

Run with CHEMICALOPS_LIVE_QUEUE_ACCEPTANCE=1 after pausing business submissions.
Uses the dedicated acceptance database and a model HTTP substitute.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.ai.model import AIAgentTask
from app.modules.jobs.model import SchedulerJobRun
from app.modules.system.model import Department, User, Role, Permission, UserRole, RolePermission
from app.modules.task_queue import broker, service, processes
from app.modules.task_queue.model import TaskExecution, TaskOutbox, TaskResourceLock
from tests.test_task_queue_delivery import queue_engine, broker_settings

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "chemicalops-messaging-rabbitmq-1"
pytestmark = pytest.mark.skipif(os.getenv("CHEMICALOPS_LIVE_QUEUE_ACCEPTANCE") != "1", reason="Explicit live broker fault exercise")


def test_live_dispatcher_and_two_worker_clis_survive_broker_outage(queue_engine, tmp_path):
    Base.metadata.create_all(queue_engine, tables=[model.__table__ for model in
        (Department, User, Role, Permission, UserRole, RolePermission, AIAgentTask)])
    values = dotenv_values(ROOT / ".env")
    rabbit = dotenv_values(ROOT / ".env.rabbitmq")
    acceptance_broker = broker_settings()
    factory = sessionmaker(queue_engine, expire_on_commit=False)
    role_id = user_id = None
    executions, runs = [], []
    logs = []
    continuous = None
    crashing_worker = None

    class Model(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if getattr(self.server, "model_gate", None) is not None:
                self.server.model_started.set()
                self.server.model_gate.wait(timeout=20)
            body = json.dumps({"choices": [{"message": {"role": "assistant", "content":
                json.dumps({"action": "ask_user", "question": "请补充产品名称"})}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass  # The crash exercise deliberately closes an in-flight model request.
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env_file = tmp_path / "queue-acceptance.env"
    env_file.write_text("\n".join(f"{key}={value}" for key, value in {
        "MYSQL_HOST": values.get("MYSQL_HOST", "127.0.0.1"), "MYSQL_PORT": values.get("MYSQL_PORT", "3306"),
        "MYSQL_DATABASE": "chemicalops_mq_acceptance_20261008", "MYSQL_USER": "root",
        "MYSQL_PASSWORD": values["MYSQL_ROOT_PASSWORD"],
        "RABBITMQ_USERNAME": rabbit["RABBITMQ_USERNAME"], "RABBITMQ_PASSWORD": rabbit["RABBITMQ_PASSWORD"],
        "RABBITMQ_VHOST": acceptance_broker.rabbitmq_vhost,
        "AGENT_EXECUTION_MODE": "rabbitmq", "TECHNICAL_DOCUMENT_EXECUTION_MODE": "rabbitmq",
        "OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}", "OPENAI_API_KEY": "acceptance-only",
        "TASK_HEARTBEAT_SECONDS": 1, "TASK_LEASE_SECONDS": 15,
    }.items()), encoding="utf-8")
    def cli(script, *args, expect=0):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--env-file", str(env_file), *args],
            cwd=ROOT, capture_output=True, text=True, timeout=40)
        logs.append(result.stdout + result.stderr)
        assert result.returncode == expect, result.stdout + result.stderr
        return result
    def docker(*args):
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=40)
        assert result.returncode == 0, result.stderr

    try:
        with factory() as db:
            role = Role(role_code="ACCEPTANCE_" + uuid4().hex[:8], role_name="Queue acceptance")
            user = User(username="queue_" + uuid4().hex[:8], password_hash="no-login", display_name="Queue acceptance", status="ACTIVE")
            db.add_all([role, user])
            db.flush()
            role_id, user_id = role.id, user.id
            # Only the test role is changed; service recognises the administrator code.
            role.role_code = "SYS_ADMIN"
            db.add(UserRole(user_id=user_id, role_id=role_id))
            db.commit()
        docker("stop", CONTAINER)
        with factory() as db:
            task_id, run_id = uuid4().hex, uuid4().hex
            db.add(AIAgentTask(id=task_id, user_id=user_id, status="RUNNING", revision=0, reply="",
                payload={"messages": ["查询库存"], "trace": [], "turn_start": 0},
                created_at=service.now(), updated_at=service.now()))
            db.add(SchedulerJobRun(run_id=run_id, task_name="technical_documents_pipeline", status="QUEUED",
                result_json={"action": "fetch", "cas_no": "64-17-5", "doc_types": ["msds"], "stages": []}))
            agent = service.enqueue(db, task_type="agent.run", business_id=task_id, actor_id=user_id, generation=0, payload={})
            # Nonexistent actor proves the document child performs current authorization.
            document = service.enqueue(db, task_type="documents.fetch", business_id=run_id, actor_id=2147483647,
                generation=0, payload={"cas_no": "64-17-5", "doc_types": ["msds"]})
            executions.extend([agent.id, document.id])
            runs.append(run_id)
            db.commit()
        status = json.loads(cli("run_task_dispatcher.py", "--status").stdout)
        assert status["outbox"]["PENDING"] == 2
        cli("run_task_dispatcher.py", "--once", expect=1)
        continuous = subprocess.Popen([sys.executable, str(ROOT / "scripts/run_task_dispatcher.py"),
            "--env-file", str(env_file)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1)
        docker("start", CONTAINER)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            with factory() as db:
                sent = list(db.scalars(select(TaskOutbox.status).where(TaskOutbox.execution_id.in_(executions))))
            if sent == ["SENT", "SENT"]:
                break
            time.sleep(1)
        assert sent == ["SENT", "SENT"]
        cli("run_task_worker.py", "--queue", "agent", "--once")
        with factory() as db:
            assert db.get(TaskExecution, executions[0]).status == "WAITING_INPUT"
            assert db.get(TaskExecution, executions[1]).status == "QUEUED"
        cli("run_task_worker.py", "--queue", "documents", "--once")
        with factory() as db:
            row = db.get(TaskExecution, executions[1])
            assert row.status == "FAILED" and row.error_code == "PERMISSION_DENIED" and row.attempt_count == 1
            run = db.scalar(select(SchedulerJobRun).where(SchedulerJobRun.run_id == runs[0]))
            assert run.status == "FAILED"
        cli("run_task_worker.py", "--queue", "documents", "--recover-only")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with factory() as db:
                failure = db.scalar(select(TaskOutbox).where(TaskOutbox.execution_id == executions[1],
                    TaskOutbox.routing_key == "documents.failed"))
                published = failure is not None and failure.status == "SENT"
            if published:
                break
            time.sleep(0.2)
        assert published
        async def acknowledge_failure():
            from tests.test_task_queue_delivery import broker_settings
            async with broker.connection(broker_settings()) as client:
                channel = await client.channel()
                queue = await channel.get_queue("chemicalops.documents.failed")
                message = await queue.get(timeout=10)
                envelope = broker.TaskMessage.model_validate_json(message.body)
                assert envelope.execution_id == executions[1]
                await message.ack()
        asyncio.run(acknowledge_failure())
        # Force the actual AMQP consumer to exit while its model child is running.
        server.model_gate = threading.Event()
        server.model_started = threading.Event()
        with factory() as db:
            crash_task_id = uuid4().hex
            db.add(AIAgentTask(id=crash_task_id, user_id=user_id, status="RUNNING", revision=0, reply="",
                payload={"messages": ["查询库存"], "trace": [], "turn_start": 0},
                created_at=service.now(), updated_at=service.now()))
            crashed = service.enqueue(db, task_type="agent.run", business_id=crash_task_id,
                actor_id=user_id, generation=0, payload={})
            executions.append(crashed.id)
            db.commit()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with factory() as db:
                status = db.scalar(select(TaskOutbox.status).where(TaskOutbox.execution_id == crashed.id))
            if status == "SENT":
                break
            time.sleep(0.2)
        assert status == "SENT"
        crashing_worker = subprocess.Popen([sys.executable, str(ROOT / "scripts/run_task_worker.py"),
            "--env-file", str(env_file), "--queue", "agent", "--once"], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert server.model_started.wait(timeout=15)
        with factory() as db:
            active = db.get(TaskExecution, crashed.id)
            child_pid = active.checkpoint["process_pid"]
            previous_token = active.fencing_token
        assert processes.process_alive(child_pid)
        crashing_worker.kill()
        stdout, stderr = crashing_worker.communicate(timeout=10)
        logs.append(stdout + stderr)
        deadline = time.monotonic() + 5
        while processes.process_alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not processes.process_alive(child_pid)
        server.model_gate.set()
        server.model_gate = None
        with factory() as db:
            active = db.get(TaskExecution, crashed.id)
            active.lease_until = service.now() - timedelta(seconds=1)
            db.commit()
        cli("run_task_worker.py", "--queue", "agent", "--recover-only")
        with factory() as db:
            recovered = db.get(TaskExecution, crashed.id)
            assert recovered.status == "RETRYING" and recovered.fencing_token > previous_token
        # Old delivery may be returned first; its generation cannot claim the task.
        for _attempt in range(3):
            cli("run_task_worker.py", "--queue", "agent", "--once")
            with factory() as db:
                recovered = db.get(TaskExecution, crashed.id)
                if recovered.status == "WAITING_INPUT":
                    break
            time.sleep(1)
        assert recovered.status == "WAITING_INPUT" and recovered.attempt_count == 2
    finally:
        docker("start", CONTAINER)
        if crashing_worker and crashing_worker.poll() is None:
            crashing_worker.kill()
            crashing_worker.communicate(timeout=10)
        if getattr(server, "model_gate", None) is not None:
            server.model_gate.set()
        if continuous:
            continuous.terminate()
            stdout, stderr = continuous.communicate(timeout=15)
            logs.append(stdout + stderr)
        server.shutdown()
        server.server_close()
        env_file.unlink(missing_ok=True)
        with factory() as db:
            db.execute(delete(TaskOutbox).where(TaskOutbox.execution_id.in_(executions)))
            db.execute(delete(TaskResourceLock).where(TaskResourceLock.execution_id.in_(executions)))
            db.execute(delete(TaskExecution).where(TaskExecution.id.in_(executions)))
            if user_id:
                db.execute(delete(AIAgentTask).where(AIAgentTask.user_id == user_id))
            db.execute(delete(SchedulerJobRun).where(SchedulerJobRun.run_id.in_(runs)))
            if user_id:
                db.execute(delete(UserRole).where(UserRole.user_id == user_id))
                db.execute(delete(User).where(User.id == user_id))
            if role_id:
                db.execute(delete(Role).where(Role.id == role_id))
            db.commit()
        output = "\n".join(logs)
        assert rabbit["RABBITMQ_PASSWORD"] not in output
        assert values["MYSQL_ROOT_PASSWORD"] not in output
