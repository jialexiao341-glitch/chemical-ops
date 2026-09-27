"""固定 AI 离线评测门槛。"""

from app.modules.ai.evaluation import run_offline_evaluation


def test_offline_evaluation_cases_all_pass() -> None:
    report = run_offline_evaluation()

    assert report["suite"] == "chemicalops-ai-offline-v1"
    assert report["mode"] == "deterministic_no_llm_no_writes"
    assert report["case_count"] >= 20
    assert report["failed_count"] == 0
    assert report["accuracy"] == 1.0
