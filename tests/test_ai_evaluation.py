"""固定 AI 离线评测门槛。"""

from app.modules.ai.evaluation import run_offline_evaluation
from app.modules.ai.schema import Understanding, SubTask
from scripts.evaluate_intent_routing import check_execution_contract


def test_offline_evaluation_cases_all_pass() -> None:
    report = run_offline_evaluation()

    assert report["suite"] == "chemicalops-ai-offline-v1"
    assert report["mode"] == "deterministic_no_llm_no_writes"
    assert report["case_count"] >= 20
    assert report["failed_count"] == 0
    assert report["accuracy"] == 1.0


def test_semantic_route_evaluation_checks_explicit_execution_contract() -> None:
    batch = Understanding(
        purpose="query", execution_mode="batch", tasks=["inventory"],
        sub_tasks=[SubTask(id=f"t{i}", kind="inventory", question="查库存") for i in range(1, 4)],
    )
    assert check_execution_contract(batch, "batch")

    analytics = Understanding(
        purpose="query", execution_mode="query", tasks=["analytics"],
        sub_tasks=[SubTask(id="t1", kind="analytics", question="统计订单")],
    )
    assert check_execution_contract(analytics, "query")
    assert not check_execution_contract(analytics, "agent")

    clarification = Understanding(purpose="clarify", execution_mode="none")
    assert check_execution_contract(clarification, "clarify")

    same_product_combo = Understanding(
        purpose="query", execution_mode="agent", tasks=["inventory", "quotes"],
    )
    assert check_execution_contract(same_product_combo, "agent")

    purchase_draft = Understanding(purpose="purchase_draft", execution_mode="none")
    assert check_execution_contract(purchase_draft, "purchase_draft")
