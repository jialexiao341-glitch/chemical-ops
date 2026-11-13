"""合成样本转化基准：只验证链路与口径，不把 fixture 当生产证据。"""

from scripts.measure_regression_conversion import (
    DEFAULT_APPROVALS,
    DEFAULT_FIXTURES,
    measure,
    render_markdown,
)


def test_benchmark_runs_end_to_end_on_synthetic_fixture():
    result = measure(DEFAULT_FIXTURES, DEFAULT_APPROVALS)

    assert result["production_measured"] is False
    assert result["dataset"]["samples"] == 20
    assert result["counts"] == {
        "candidates": 20, "created": 20, "reused": 0,
        "skipped_create": 0, "failed_create": 0,
        "approved": 18, "archived": 2, "exported": 18,
    }
    assert result["redaction_hits"]["mobile"] == 2
    assert result["approval_fixture"]["measured_human_time"] is False
    assert "不能" in result["approval_fixture"]["note"]

    markdown = render_markdown(result)
    assert "不是生产差评" in markdown
    assert "不能用于宣称" in markdown
    assert "| 20 | 20 | 0 | 0 | 0 | 18 | 2 | 18 |" in markdown