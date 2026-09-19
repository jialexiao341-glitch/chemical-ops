"""ChemicalOps 本地开发入口。"""

import argparse
import logging
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parent
LOGGER = logging.getLogger("chemicalops.launcher")


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
    uvicorn.run(
        "app.main:app",
        app_dir=str(PROJECT_ROOT / "backend"),
        host="127.0.0.1" if is_dev else "0.0.0.0",
        port=8888,
        reload=is_dev,
        access_log=True,
        log_level="info",
    )


def main() -> None:
    """解析命令并执行对应动作。"""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = build_parser().parse_args()
    if args.command == "run":
        run_server(args.env)


if __name__ == "__main__":
    main()
