"""Agent 成本报告：用量归一、聚合、费用估算与覆盖率。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.modules.ai_agent.agent_execution import agent_runtime as runtime
from scripts import agent_cost_report as report


def _usage(*, calls: int, prompt: int, completion: int, total: int,
           unmetered: int = 0, split_unavailable: int = 0) -> dict:
    return {
        "calls": calls, "input_tokens": prompt, "output_tokens": completion,
        "total_tokens": total, "unmetered_calls": unmetered,
        "split_unavailable_calls": split_unavailable,
    }


def _task(task_id: str, *, scene: str = "inventory", model: str = "deepseek-flash",
          planner: str = "planner@1-a", status: str = "SUCCEEDED",
          usage: dict | None = None, budget: int | None = None,
          duration: int = 10, include_meta: bool = True):
    payload = {"memory_state": {"goal": {"intent": scene}}}
    if include_meta:
        payload["run_meta"] = {
            "model": {"name": model},
            "prompt_versions": {"planner": planner},
        }
        if usage is not None:
            payload["run_meta"]["usage_totals"] = usage
    if budget is not None:
        payload["token_budget"] = {"used_tokens": budget, "estimated_tokens": 0, "calls": 1}
    created = datetime(2026, 1, 1, 12, 0, 0)
    return SimpleNamespace(id=task_id, status=status, payload=payload,
                           created_at=created, updated_at=created + timedelta(seconds=duration))


def test_collect_and_summarize_groups_scene_model_and_prompt():
    tasks = [
        _task("t1", usage=_usage(calls=2, prompt=1000, completion=500, total=1500),
              duration=10),
        _task("t2", status="FAILED",
              usage=_usage(calls=3, prompt=2000, completion=1000, total=3000),
              duration=20),
        _task("t3", scene="quotes", budget=4000, include_meta=False, duration=30),
    ]

    rows = report.collect_rows(tasks, price_in=1.0, price_out=2.0,
                               default_model="deepseek-flash")

    assert [row["scene"] for row in rows] == ["inventory", "inventory", "quotes"]
    assert rows[0]["estimated_cost"] == pytest.approx(0.002)
    assert rows[1]["estimated_cost"] == pytest.approx(0.004)
    assert rows[2]["usage_source"] == "token_budget"
    assert rows[2]["total_tokens"] == 4000
    assert rows[2]["estimated_cost"] is None

    summary = report.summarize(rows)
    assert summary["tasks"] == 3
    assert summary["succeeded"] == 2
    assert summary["success_rate"] == pytest.approx(0.6667)
    assert summary["input_tokens"] == 3000
    assert summary["output_tokens"] == 1500
    assert summary["total_tokens"] == 8500
    assert summary["estimated_cost"] == pytest.approx(0.006)
    assert summary["cost_tasks"] == 2
    assert summary["cost_missing_tasks"] == 1
    assert summary["p50_seconds"] == pytest.approx(20)
    assert summary["p95_seconds"] == pytest.approx(29)

    built = report.build_report(rows, days=7, price_in=1.0, price_out=2.0,
                                default_model="deepseek-flash")
    by_scene = {row["scene"]: row for row in built["by_scene"]}
    assert by_scene["inventory"]["tasks"] == 2
    assert by_scene["inventory"]["total_tokens"] == 4500
    assert by_scene["quotes"]["tasks"] == 1
    assert {row["prompt_version"] for row in built["by_prompt_version"]} == {
        "planner@1-a", "unknown"}


def test_latency_percentiles_exclude_waiting_tasks():
    rows = report.collect_rows(
        [_task("done", duration=10),
         _task("wait", status="WAITING_INPUT", duration=99999)],
        price_in=1.0, price_out=2.0, default_model="deepseek-flash")

    summary = report.summarize(rows)

    assert summary["terminal_tasks"] == 1
    assert summary["p50_seconds"] == pytest.approx(10)
    assert summary["p95_seconds"] == pytest.approx(10)
    built = report.build_report(rows, days=7, price_in=1.0, price_out=2.0,
                                default_model="deepseek-flash")
    assert built["coverage"]["tasks_with_duration"] == 1
    assert built["coverage"]["terminal_tasks"] == 1


def test_unmetered_and_missing_usage_are_reported_not_priced():
    tasks = [
        _task("t1", usage=_usage(calls=2, prompt=0, completion=0, total=100,
                                 unmetered=2), budget=900),
        _task("t2", include_meta=False),
    ]

    rows = report.collect_rows(tasks, price_in=1.0, price_out=2.0,
                               default_model="deepseek-flash")

    assert rows[0]["usage_source"] == "token_budget"
    assert rows[0]["total_tokens"] == 900
    assert rows[0]["unmetered_calls"] == 2
    assert rows[0]["estimated_cost"] is None
    assert rows[1]["usage_source"] == "missing"
    assert rows[1]["total_tokens"] == 0
    assert rows[1]["estimated_cost"] is None

    built = report.build_report(rows, days=7, price_in=1.0, price_out=2.0,
                                default_model="deepseek-flash")
    assert built["coverage"]["tasks"] == 2
    assert built["coverage"]["token_budget_only"] == 1
    assert built["coverage"]["missing"] == 1
    assert built["coverage"]["unmetered_calls"] == 2
    assert "缺 usage" in report.render_markdown(built)


def test_zero_prices_do_not_claim_a_cost():
    rows = report.collect_rows(
        [_task("t1", usage=_usage(calls=1, prompt=10, completion=5, total=15))],
        price_in=0.0, price_out=0.0, default_model="deepseek-flash")

    assert rows[0]["estimated_cost"] is None
    built = report.build_report(rows, days=7, price_in=0.0, price_out=0.0,
                                default_model="deepseek-flash")
    assert built["pricing"]["configured"] is False
    assert "未配置" in report.render_markdown(built)


def test_partial_usage_split_is_flagged():
    rows = report.collect_rows(
        [_task("t1", usage=_usage(calls=2, prompt=0, completion=500, total=500,
                                  split_unavailable=1))],
        price_in=1.0, price_out=2.0, default_model="deepseek-flash")

    assert rows[0]["cost_partial"] is True
    assert rows[0]["estimated_cost"] == pytest.approx(0.001)
    built = report.build_report(rows, days=7, price_in=1.0, price_out=2.0,
                                default_model="deepseek-flash")
    assert built["summary"]["partial_cost_tasks"] == 1


def test_accumulate_usage_totals_across_calls():
    state = SimpleNamespace(run_meta={})

    runtime._accumulate_usage(state, {"prompt_tokens": 10, "completion_tokens": 5,
                                      "total_tokens": 15})
    runtime._accumulate_usage(state, {"prompt_tokens": 20, "completion_tokens": 7,
                                      "total_tokens": 27})
    runtime._accumulate_usage(state, {"total_tokens": 30})
    runtime._accumulate_usage(state, None)

    totals = state.run_meta["usage_totals"]
    assert totals["calls"] == 4
    assert totals["input_tokens"] == 30
    assert totals["output_tokens"] == 12
    assert totals["total_tokens"] == 72
    assert totals["split_unavailable_calls"] == 1
    assert totals["unmetered_calls"] == 1


def test_percentile_handles_empty_and_interpolation():
    assert report.percentile([], 0.5) is None
    assert report.percentile([10, 20, 30], 0.5) == pytest.approx(20)
    assert report.percentile([10, 20, 30], 0.95) == pytest.approx(29)