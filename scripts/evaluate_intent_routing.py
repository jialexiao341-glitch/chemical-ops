"""独立语义路由样本；仅发送合成问题，不读取业务库，不执行工具。"""

import argparse
import hashlib
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import get_settings
from app.modules.ai.routing import ROUTING_PROMPT, understand


CASES = [
    ("统计本月采购订单数量和金额", {}, "batch", ["analytics"]),
    ("查乙醇和甲醇库存", {}, "batch", ["inventory"]),
    ("查乙醇库存并统计本月订单数量", {}, "batch", ["inventory", "analytics"]),
    ("你好，查乙醇库存", {}, "agent", ["inventory"]),
    ("查 64-17-5 的库存", {}, "agent", ["inventory"]),
    ("库存查询支持哪些筛选条件？", {}, "capability", []),
    ("库存不足怎么处理？", {}, "guidance", []),
    ("查乙醇库存，不用比较报价", {}, "agent", ["inventory"]),
    ("不要创建订单，只统计本月订单金额", {}, "query", ["analytics"]),
    ("查供应商总数", {}, "query", ["analytics"]),
    ("把时间改成上个月", {"query_plan": {"dataset": "purchase_orders"}, "messages": [{"role": "user", "content": "统计本月采购订单金额"}]}, "query", ["analytics"]),
    ("查乙醇库存并比较报价", {}, "batch", ["inventory", "quotes"]),
    ("查乙醇闪点并查库存", {}, "batch", ["document", "inventory"]),
    ("帮我创建采购订单", {}, "unsupported", []),
    ("查一下它的库存", {"messages": [{"role": "user", "content": "乙醇闪点是多少"}]}, "agent", ["inventory"]),
    ("改查甲醇库存", {"memory": {"goal": {"intent": "inventory_and_quotes_query", "description": "查乙醇库存并比较报价"}}}, "agent", ["inventory"]),
]


async def evaluate(output: Path) -> None:
    """调用配置模型评测合成样本，写入不含密钥的 JSON 证据。

    output 为输出文件路径；并发最多三项，每项超时 45 秒且不重试。
    仅校验路由类别和任务集合，不代表工具成功率、检索质量或生产收益。
    """
    settings = get_settings().model_copy(update={"llm_max_retries": 0, "llm_timeout_seconds": 45})
    semaphore = asyncio.Semaphore(3)
    async def run(case: tuple[str, dict, str, list[str]]) -> dict:
        """评测一条问题及会话上下文，记录期望、实际分类和耗时。"""
        question, context, expected_route, expected_tasks = case
        async with semaphore:
            start = perf_counter()
            result = await understand(question, context, settings)
            return {"question": question, "context": context, "expected_route": expected_route,
                    "expected_tasks": expected_tasks, "actual": result.model_dump(mode="json"), "route": result.route,
                    "passed": result.route == expected_route and set(result.tasks) == set(expected_tasks) and
                              (expected_route != "batch" or len(result.sub_tasks) == 2),
                    "seconds": round(perf_counter() - start, 2)}
    results = await asyncio.gather(*(run(case) for case in CASES))
    report = {"evaluated_at": datetime.now(timezone.utc).isoformat(), "model": settings.llm_model,
              "prompt_sha256": hashlib.sha256(ROUTING_PROMPT.encode()).hexdigest(),
              "scope": "合成语义路由样本；不衡量工具执行、检索或生产业务效果", "total": len(results),
              "passed": sum(row["passed"] for row in results), "cases": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": report["total"], "passed": report["passed"], "output": str(output)}, ensure_ascii=False))


def main() -> None:
    """解析 --output 参数并运行评测；在项目根目录使用本地 Python 环境执行。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/evaluation/intent-routing.json"))
    asyncio.run(evaluate(parser.parse_args().output))


if __name__ == "__main__":
    main()
