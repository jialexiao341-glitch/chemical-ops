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
    ("不用查乙醇，只查甲醇库存", {}, "agent", ["inventory"]),
    ("只统计订单数量，不要金额", {}, "query", ["analytics"]),
    ("查乙醇和甲醇库存，不要报价", {}, "batch", ["inventory"]),
    ("查乙醇库存和甲醇报价", {}, "batch", ["inventory", "quotes"]),
    ("分别统计已付款和待付款的金额", {}, "batch", ["analytics"]),
    ("分别统计采购申请和采购订单数量", {}, "batch", ["analytics"]),
    ("查它的库存", {"messages": [{"role": "user", "content": "乙醇和甲醇有什么区别"}]}, "clarify", []),
    ("换成上个月", {"memory": {"batch_tasks": [{"id": "t1", "kind": "analytics", "question": "统计订单数量"}, {"id": "t2", "kind": "analytics", "question": "统计付款金额"}]}}, "clarify", []),
    ("以上两项都改成上个月", {"memory": {"batch_tasks": [{"id": "t1", "kind": "analytics", "question": "统计订单数量"}, {"id": "t2", "kind": "analytics", "question": "统计付款金额"}]}}, "batch", ["analytics"]),
    ("第二项改为甲醇报价，第一项不变", {"memory": {"batch_tasks": [{"id": "t1", "kind": "inventory", "question": "查乙醇库存"}, {"id": "t2", "kind": "quotes", "question": "查乙醇报价"}]}}, "batch", ["inventory", "quotes"]),
    ("先查乙醇库存，再根据结果查询该批次库存流水", {}, "batch", ["inventory", "analytics"]),
    ("先找已审批但未询价的采购申请，再统计这些申请的数量", {}, "batch", ["analytics"]),
    ("先查乙醇库存，然后创建采购申请", {}, "unsupported", []),
    ("查乙醇库存，再查甲醇库存，两项各看前5条", {}, "batch", ["inventory"]),
    ("第二项使用产品编码 PRD-ETHANOL-AR，第一项保持不变", {"memory": {"batch_tasks": [{"id": "t1", "kind": "analytics", "question": "统计采购订单数量", "status": "SUCCEEDED"}, {"id": "t2", "kind": "inventory", "question": "查询乙醇的可用库存", "status": "WAITING_INPUT"}]}}, "batch", ["analytics", "inventory"]),
]

# 除路由类别外，单独核对原子计划的对象、依赖和否定条件。
CONTRACTS = {
    "查乙醇和甲醇库存": {"products": ["乙醇", "甲醇"]},
    "不用查乙醇，只查甲醇库存": {"products": ["甲醇"]},
    "查乙醇和甲醇库存，不要报价": {"products": ["乙醇", "甲醇"], "excluded": "quotes"},
    "查乙醇库存和甲醇报价": {"products": ["乙醇", "甲醇"]},
    "先查乙醇库存，再根据结果查询该批次库存流水": {"dependency": True},
    "先找已审批但未询价的采购申请，再统计这些申请的数量": {"dependency": True},
    "查乙醇库存，再查甲醇库存，两项各看前5条": {"products": ["乙醇", "甲醇"], "limit": 5},
    "第二项使用产品编码 PRD-ETHANOL-AR，第一项保持不变": {"products": [None, "PRD-ETHANOL-AR"]},
}


def check_contract(question, result):
    contract = CONTRACTS.get(question)
    if not contract:
        return None
    tasks = result.sub_tasks
    slots = [task.slots for task in tasks] if tasks else [result.slots]
    checks = []
    if "products" in contract:
        checks.append([slot.product_keyword for slot in slots] == contract["products"])
    if "excluded" in contract:
        checks.append(contract["excluded"] not in result.tasks)
    if contract.get("dependency"):
        checks.append(len(tasks) == 2 and tasks[1].depends_on == [tasks[0].id])
    if "limit" in contract:
        checks.append(all(slot.limit == contract["limit"] for slot in slots))
    return all(checks)


async def evaluate(output: Path, repeats: int = 1) -> None:
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
            recognized = result.route == expected_route and set(result.tasks) == set(expected_tasks)
            planned = check_contract(question, result)
            return {"question": question, "context": context, "expected_route": expected_route,
                    "expected_tasks": expected_tasks, "actual": result.model_dump(mode="json"), "route": result.route,
                    "recognition_passed": recognized, "plan_contract_passed": planned,
                    "execution_passed": None,
                    "passed": recognized and planned is not False and (expected_route != "batch" or len(result.sub_tasks) == 2),
                    "seconds": round(perf_counter() - start, 2)}
    results = []
    for round_index in range(repeats):
        current = await asyncio.gather(*(run(case) for case in CASES))
        results.extend({"round": round_index + 1, **row} for row in current)
    report = {"evaluated_at": datetime.now(timezone.utc).isoformat(), "model": settings.llm_model,
              "prompt_sha256": hashlib.sha256(ROUTING_PROMPT.encode()).hexdigest(),
              "scope": "合成语义路由样本；不衡量工具执行、检索或生产业务效果", "repeats": repeats,
              "sample_count": len(CASES), "total": len(results),
              "passed": sum(row["passed"] for row in results), "cases": results}
    report["recognition"] = {"total": len(results), "passed": sum(row["recognition_passed"] for row in results)}
    planned = [row for row in results if row["plan_contract_passed"] is not None]
    report["plan_contract"] = {"total": len(planned), "passed": sum(row["plan_contract_passed"] for row in planned)}
    report["execution"] = {"total": 0, "passed": 0, "note": "本脚本不执行查询，不能当作执行成功率"}
    report["stability"] = {"total_samples": len(CASES), "passed_all_rounds": sum(
        all(row["passed"] for row in results if row["question"] == case[0]) for case in CASES)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": report["total"], "passed": report["passed"], "output": str(output)}, ensure_ascii=False))


def main() -> None:
    """解析 --output 参数并运行评测；在项目根目录使用本地 Python 环境执行。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/evaluation/intent-routing.json"))
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=1)
    args = parser.parse_args()
    asyncio.run(evaluate(args.output, args.repeats))


if __name__ == "__main__":
    main()
