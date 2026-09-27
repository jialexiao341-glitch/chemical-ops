"""运行固定的 AI 离线护栏评测，不调用外部模型或修改业务数据。"""

import argparse
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.ai.evaluation import run_offline_evaluation  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="ChemicalOps AI 离线护栏评测")
    parser.add_argument("--min-accuracy", type=float, default=1.0, help="通过门槛，默认要求全部用例通过")
    args = parser.parse_args()
    if not 0 <= args.min_accuracy <= 1:
        raise SystemExit("min-accuracy 必须介于 0 和 1 之间")

    report = run_offline_evaluation()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["accuracy"] < args.min_accuracy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
