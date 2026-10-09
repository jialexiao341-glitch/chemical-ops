"""ChemicalOps 本地开发入口。"""

import argparse
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parent
LOGGER = logging.getLogger("chemicalops.launcher")


@contextmanager
def development_workers():
    """Keep development workers outside the API reload process and stop them on exit."""
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
    from app.core.config import get_settings
    from app.modules.task_queue.processes import WindowsJob

    settings = get_settings()
    workers = []
    try:
        for queue, mode in (("documents", settings.technical_document_execution_mode),
                            ("agent", settings.agent_execution_mode)):
            if mode != "database":
                continue
            process = subprocess.Popen(
                [sys.executable, str(PROJECT_ROOT / "scripts/run_task_worker.py"),
                 "--queue", queue, "--env-file", str(PROJECT_ROOT / ".env")],
                cwd=PROJECT_ROOT, start_new_session=os.name != "nt",
            )
            workers.append((process, None))
            if os.name == "nt":
                workers[-1] = (process, WindowsJob(process.pid))
            LOGGER.info("启动数据库任务 Worker queue=%s pid=%s", queue, process.pid)
        yield
    finally:
        for process, job in reversed(workers):
            if job:
                job.close()
            elif process.poll() is None:
                if os.name == "nt":
                    process.terminate()
                else:
                    os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""

    parser = argparse.ArgumentParser(description="ChemicalOps 服务启动工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="启动后端 API 服务")
    run_parser.add_argument(
        "--env",
        choices=("dev", "prod"),
        default="dev",
        help="运行环境，dev 使用本机地址并开启热重载，prod 使用 .env 配置",
    )
    return parser


def run_server(environment: str) -> None:
    """根据运行环境启动 FastAPI 服务。"""

    is_dev = environment == "dev"
    LOGGER.info(
        "启动 ChemicalOps 命令=run 环境=%s 地址=%s 端口=%s 热重载=%s",
        environment,
        "127.0.0.1" if is_dev else "0.0.0.0",
        8888,
        is_dev,
    )
    options = dict(
        app_dir=str(PROJECT_ROOT / "backend"),
        host="127.0.0.1" if is_dev else "0.0.0.0",
        port=8888,
        reload=is_dev,
        access_log=True,
        log_level="info",
    )
    if is_dev:
        with development_workers():
            uvicorn.run("app.main:app", **options)
    else:
        uvicorn.run("app.main:app", **options)


def main() -> None:
    """解析命令并执行对应动作。"""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = build_parser().parse_args()
    if args.command == "run":
        run_server(args.env)


if __name__ == "__main__":
    main()
