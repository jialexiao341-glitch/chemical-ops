"""不依赖外部服务的 Prometheus 指标格式测试。"""

from app.core.observability import MetricsRegistry


def test_observed_duration_renders_cumulative_histogram_buckets() -> None:
    registry = MetricsRegistry()
    registry.observe("api_request_duration_seconds", 0.02, labels={"method": "GET"})

    rendered = registry.render_prometheus()

    assert "# TYPE chemicalops_api_request_duration_seconds_histogram histogram" in rendered
    assert 'chemicalops_api_request_duration_seconds_histogram_bucket{le="0.01",method="GET"} 0' in rendered
    assert 'chemicalops_api_request_duration_seconds_histogram_bucket{le="0.025",method="GET"} 1' in rendered
    assert 'chemicalops_api_request_duration_seconds_histogram_bucket{le="+Inf",method="GET"} 1' in rendered
    assert "chemicalops_api_request_duration_seconds_histogram_sum{method=\"GET\"} 0.020000" in rendered
    assert "chemicalops_api_request_duration_seconds_histogram_count{method=\"GET\"} 1" in rendered
