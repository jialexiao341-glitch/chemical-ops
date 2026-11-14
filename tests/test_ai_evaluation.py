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


def test_eval_runtime_common_distinguishes_4xx_config_from_infra() -> None:
    """HTTP 400 配置错误不得误记为基础设施失败；上游断流/超时应归入 AMBIGUOUS_TIMEOUT。"""
    import httpx
    from app.core.errors import BusinessValidationError
    from scripts.eval_runtime_common import exception_run_meta

    bad_req = BusinessValidationError("AI 服务拒绝了请求（HTTP 400）")
    bad_req.__cause__ = httpx.HTTPStatusError(
        "bad request",
        request=httpx.Request("POST", "https://example.test"),
        response=httpx.Response(400),
    )
    assert exception_run_meta(bad_req) == {}

    reset = httpx.RemoteProtocolError("Server disconnected")
    assert exception_run_meta(reset, default_infra_code="INTENT_SERVICE_ERROR") == {
        "error": {"class": "AMBIGUOUS_TIMEOUT", "code": "INTENT_SERVICE_ERROR"}
    }


def test_prod_regression_and_routing_contract_record_run_meta_and_timeout(monkeypatch, tmp_path) -> None:
    """prod_regression 与 ai_routing_contract 必须启用 >=120s 超时、解析激活模型并写入 run_meta。"""
    import asyncio
    from types import SimpleNamespace
    import httpx
    from scripts import evaluate_ai_routing_contract as eval_contract
    from scripts import evaluate_prod_regression as eval_prod

    seen_prod = []

    async def fake_prod_understand(question, context, settings, *, manifest=None):
        seen_prod.append((settings.llm_timeout_seconds, settings.llm_max_retries))
        cause = httpx.ReadTimeout("slow")
        raise IntentRecognitionError("service timeout", "INTENT_SERVICE_ERROR") from cause

    monkeypatch.setattr(eval_prod.routing, "understand", fake_prod_understand)
    monkeypatch.setattr(eval_prod, "build_manifest", lambda _name: SimpleNamespace(digest="d"))
    monkeypatch.setattr(
        eval_prod,
        "resolve_model_profile",
        lambda _s: SimpleNamespace(name="MaxApi", model="deepseek-v4.1-flash"),
    )
    prod_report = asyncio.run(eval_prod.evaluate([{"id": "PR01", "question": "查乙醇库存"}]))
    assert seen_prod[0][0] >= 120
    assert prod_report["cases"][0]["evaluation_error_code"] == "INTENT_SERVICE_ERROR"
    assert prod_report["cases"][0]["run_meta"]["error"]["class"] == "AMBIGUOUS_TIMEOUT"

    seen_contract = []
    base = eval_contract.routing.get_settings()

    async def fake_contract_understand(question, context, settings, *, manifest=None):
        seen_contract.append(settings.llm_timeout_seconds)
        raise IntentRecognitionError("down", "INTENT_SERVICE_ERROR")

    monkeypatch.setattr(eval_contract, "CASES", [{"id": "C1", "profile": "admin", "question": "查库存", "routes": ["agent"]}])
    monkeypatch.setattr(eval_contract, "synthetic_manifest", lambda _p: SimpleNamespace(digest="m"))
    monkeypatch.setattr(
        eval_contract,
        "activate_eval_profile",
        lambda **kw: (base.model_copy(update={"llm_timeout_seconds": max(base.llm_timeout_seconds, kw.get("min_timeout_seconds", 120))}),
                      SimpleNamespace(name="MaxApi", model="deepseek-v4.1-flash")),
    )
    monkeypatch.setattr(eval_contract.routing, "understand", fake_contract_understand)
    contract_out = tmp_path / "contract.json"
    code = asyncio.run(eval_contract.evaluate(contract_out))
    assert code == 1
    assert seen_contract[0] >= 120
    import json
    saved = json.loads(contract_out.read_text(encoding="utf-8"))
    assert saved["model"] == "deepseek-v4.1-flash"
    assert saved["cases"][0]["evaluation_error_code"] == "INTENT_SERVICE_ERROR"
    assert saved["cases"][0]["run_meta"]["error"]["class"] == "TRANSIENT_INFRA"
