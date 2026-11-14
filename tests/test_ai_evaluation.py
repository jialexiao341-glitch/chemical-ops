"""固定 AI 离线评测门槛。"""

from app.modules.ai_agent.quality_operations.evaluation import run_offline_evaluation
from app.modules.ai_agent.agent_execution.routing import IntentRecognitionError
from app.modules.ai_agent.schema import Understanding, SubTask
from scripts.evaluate_intent_routing import check_execution_contract, failure_meta


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


def test_routing_failure_meta_exposes_error_class_for_harness() -> None:
    """模型服务故障必须标成 TRANSIENT_INFRA，否则会被统计成实现失败。"""
    assert failure_meta(IntentRecognitionError("服务故障", "INTENT_SERVICE_ERROR")) == {
        "error": {"class": "TRANSIENT_INFRA", "code": "INTENT_SERVICE_ERROR"}}
    assert failure_meta(IntentRecognitionError("结构错误", "INTENT_SCHEMA_ERROR")) == {
        "error": {"class": "FORMAT", "code": "INTENT_SCHEMA_ERROR"}}
    assert failure_meta(ValueError("无错误码")) == {}


def test_routing_evaluation_preserves_model_timeout_and_retry_settings(monkeypatch, tmp_path) -> None:
    """路由评测不得在无数据库回退时把超时压低到 45 秒并关闭重试。"""
    import asyncio
    from types import SimpleNamespace
    from scripts import evaluate_intent_routing as eval_routing

    seen_settings = []

    async def fake_understand(question, context, settings=None, *, manifest=None):
        seen_settings.append((settings.llm_timeout_seconds, settings.llm_max_retries))
        return Understanding(purpose="greeting", execution_mode="none")

    monkeypatch.setattr(eval_routing, "CASES", [("你好", {}, "greeting", [])])
    monkeypatch.setattr(eval_routing, "understand", fake_understand)
    monkeypatch.setattr(
        eval_routing,
        "resolve_model_profile",
        lambda settings: SimpleNamespace(name="MaxApi", model="deepseek-v4.1-flash"),
    )
    out = tmp_path / "routing.json"
    asyncio.run(eval_routing.evaluate(out, repeats=1))

    assert seen_settings
    assert seen_settings[0][0] >= 120
    assert seen_settings[0][1] == eval_routing.get_settings().llm_max_retries
