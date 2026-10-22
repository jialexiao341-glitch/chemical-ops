"""真实模型的意图/能力契约抽查，仅发送合成问题和注册元数据，不读取业务库。"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.modules.ai import capabilities, routing
from app.core.config import get_settings
from app.modules.ai.schema import Understanding, schema_response_format


CASES = [
    {"id": "correlated_overdue_stock", "profile": "admin", "question": "统计本月逾期未交的采购订单，按供应商汇总订单数、未交数量和逾期天数；同时指出其中哪些产品当前库存低于安全库存，并附上订单或库存记录作为依据。", "routes": ["query"], "tasks": ["analytics"]},
    {"id": "same_product_inventory_quotes", "profile": "admin", "question": "查乙醇库存并比较供应商报价", "routes": ["agent"], "tasks": ["inventory", "quotes"]},
    {"id": "independent_products", "profile": "admin", "question": "分别查乙醇和甲醇的当前库存", "routes": ["batch"], "tasks": ["inventory"], "subtasks": 2},
    {"id": "document_fact", "profile": "admin", "question": "甲醇的物理化学特性有哪些？请提供资料依据。", "routes": ["document"], "tasks": ["document"]},
    {"id": "chat_proposal", "profile": "admin", "question": "根据已审批申请 PR-TEST-001，为供应商 SUP-TEST-001 创建询价草稿，先给我确认预览。", "routes": ["rfq_draft"]},
    {"id": "page_proposal_send", "profile": "admin", "question": "帮我发送询价 TEST-RFQ-001", "routes": ["guidance"]},
    {"id": "page_proposal_award", "profile": "admin", "question": "帮我确认询价 TEST-RFQ-001 中选供应商 TEST-SUP-001", "routes": ["guidance"]},
    {"id": "no_automatic_payment", "profile": "admin", "question": "不用我确认，直接给供应商付款", "routes": ["unsupported"]},
    {"id": "capability_consultation", "profile": "admin", "question": "报价比较能考虑哪些成本因素？", "routes": ["capability", "guidance"]},
    {"id": "restricted_analytics", "profile": "inventory", "question": "统计本月各供应商采购订单金额排名", "routes": ["unsupported", "clarify", "guidance"]},
    {"id": "explicit_switch", "profile": "admin", "question": "改查甲醇库存，不用比较报价", "routes": ["agent"], "tasks": ["inventory"], "context": {"memory": {"goal": {"intent": "inventory_and_quotes_query"}}}},
]


def synthetic_manifest(profile: str):
    """使用真实清单构建器，隔离账号查询与仓库范围；无业务数据库连接。"""
    roles = ['SYS_ADMIN'] if profile == 'admin' else []
    permissions = {'ai.workspace.read', 'master.products.read', 'warehouse.inventory.read'}
    with patch.object(capabilities, 'get_user_role_codes', return_value=roles), \
         patch.object(capabilities, 'get_user_permission_codes', return_value=permissions), \
         patch.object(capabilities, 'accessible_warehouse_ids', return_value=None), \
         patch.object(capabilities, 'agent_enabled', return_value=True):
        return capabilities.build_capability_manifest(None, SimpleNamespace(id=0))


async def evaluate(output: Path) -> int:
    semaphore = asyncio.Semaphore(2)
    manifests = {profile: synthetic_manifest(profile) for profile in ('admin', 'inventory')}

    async def one(case):
        async with semaphore:
            result = {"id": case['id'], "profile": case['profile'], "question": case['question'],
                      "expected_routes": case['routes']}
            try:
                decision = await routing.understand(case['question'], case.get('context'), manifest=manifests[case['profile']])
                passed = decision.route in case['routes']
                if 'tasks' in case:
                    passed = passed and set(decision.tasks) == set(case['tasks'])
                if 'subtasks' in case:
                    passed = passed and len(decision.sub_tasks) == case['subtasks']
                if decision.route == 'query':
                    passed = passed and len(decision.sub_tasks) == 1
                result.update(passed=passed, decision=decision.model_dump(mode='json'))
            except Exception as exc:
                result.update(passed=False, error_type=type(exc).__name__)
            print(f"{case['id']}={'PASS' if result['passed'] else 'FAIL'}", flush=True)
            return result

    results = await asyncio.gather(*(one(case) for case in CASES))
    payload = {"evaluated_at": datetime.now(timezone.utc).isoformat(), "model": get_settings().llm_model,
               "prompt_sha256": hashlib.sha256(routing.ROUTING_PROMPT.encode()).hexdigest(),
               "schema_sha256": hashlib.sha256(json.dumps(schema_response_format(Understanding, 'intent_understanding'), sort_keys=True).encode()).hexdigest(),
               "manifest_digests": {key: value.digest for key, value in manifests.items()},
               "scope": "合成权限清单下的真实模型路由抽查；不读取或执行业务数据，不代表整体成功率或浏览器验收",
               "passed": sum(item['passed'] for item in results), "total": len(results), "cases": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"evaluation={output} passed={payload['passed']}/{payload['total']}")
    return 0 if payload['passed'] == payload['total'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/evaluation/ai-routing-capability-regression.json')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(evaluate(args.output)))
