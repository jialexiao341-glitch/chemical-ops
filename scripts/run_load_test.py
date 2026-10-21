"""对指定 HTTP 接口执行轻量并发压测。"""

import argparse
import http.client
import json
import math
import os
import platform
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen



def _request(url: str, headers: dict[str, str], timeout: float) -> tuple[int, float]:
    """发送一次请求并返回 HTTP 状态码和耗时。"""
    started = time.perf_counter()
    try:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=timeout) as response:
            status = response.status
    except HTTPError as exc:
        status = exc.code
    except (URLError, TimeoutError, OSError, http.client.HTTPException):
        status = 0
    return status, time.perf_counter() - started


def _metrics_snapshot(url: str, timeout: float, token: str = "") -> tuple[int | None, dict[str, int] | None]:
    """读取 API 内部累计 SQL 与 Redis 缓存事件，连接失败时返回不可用。"""
    try:
        with urlopen(Request(url, headers={"Authorization": f"Bearer {token}"} if token else {}), timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError):
        return None, None
    queries = 0
    query_series_found = False
    cache: dict[str, int] = {}
    for line in body.splitlines():
        if line.startswith("#"):
            continue
        query_match = re.match(r"chemicalops_database_queries_count(?:\{[^}]*\})?\s+([\d.]+)", line)
        if query_match:
            query_series_found = True
            queries += int(float(query_match.group(1)))
        cache_match = re.match(r'chemicalops_redis_cache_count\{([^}]*)\}\s+([\d.]+)', line)
        if cache_match:
            result = re.search(r'result="([^"]+)"', cache_match.group(1))
            if result:
                cache[result.group(1)] = cache.get(result.group(1), 0) + int(float(cache_match.group(2)))
    return (queries if query_series_found else None), cache


def _percentile_ms(sorted_durations: list[float], quantile: float) -> float:
    """按 nearest-rank 口径计算延迟分位数。"""
    index = max(0, math.ceil(quantile * len(sorted_durations)) - 1)
    return round(sorted_durations[index] * 1000, 2)


def main() -> None:
    """执行并发请求，存在非预期状态码时以失败退出。"""
    parser = argparse.ArgumentParser(description="ChemicalOps 轻量接口压测工具")
    parser.add_argument("--url", default="http://127.0.0.1:8888/health", help="被测完整 URL")
    parser.add_argument("--requests", type=int, default=100, help="总请求数")
    parser.add_argument("--concurrency", type=int, default=10, help="并发 worker 数")
    parser.add_argument("--timeout", type=float, default=10, help="单请求超时秒数")
    parser.add_argument("--token", default=os.getenv("CHEMICALOPS_LOAD_TEST_TOKEN", ""), help="可选 Bearer token")
    parser.add_argument("--expected-status", type=int, default=200, help="期望 HTTP 状态码")
    parser.add_argument("--metrics-token", default=os.getenv("METRICS_ACCESS_TOKEN", ""), help="独立的监控访问凭据")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:8888/metrics", help="API Prometheus 指标地址")
    parser.add_argument("--output", default="", help="可选 JSON 结果文件路径")
    parser.add_argument("--api-instances", type=int, default=1, help="测试期间 API 实例数")
    parser.add_argument("--database-state", default="unspecified", help="数据库服务状态记录")
    parser.add_argument("--redis-state", default="unspecified", help="Redis 服务状态记录")
    parser.add_argument("--model-used", action="store_true", help="被测接口会调用 LLM")
    args = parser.parse_args()
    if args.requests <= 0 or args.concurrency <= 0 or args.timeout <= 0:
        raise SystemExit("requests、concurrency 和 timeout 必须大于 0")
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    queries_before, cache_before = _metrics_snapshot(args.metrics_url, args.timeout, args.metrics_token)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(executor.map(lambda _: _request(args.url, headers, args.timeout), range(args.requests)))
    elapsed = time.perf_counter() - started
    latencies = sorted(item[1] for item in results)
    failures = sum(status != args.expected_status for status, _ in results)
    queries_after, cache_after = _metrics_snapshot(args.metrics_url, args.timeout, args.metrics_token)
    cache_delta = None
    if cache_before is not None and cache_after is not None:
        cache_delta = {key: max(0, cache_after.get(key, 0) - cache_before.get(key, 0))
                       for key in set(cache_before) | set(cache_after)}
    cache_hits = cache_delta.get("hit", 0) if cache_delta is not None else 0
    cache_lookups = cache_hits + cache_delta.get("miss", 0) if cache_delta is not None else 0
    report = {
        "environment": {"platform": platform.platform(), "python": sys.version.split()[0],
                        "api_instances": args.api_instances, "database_state": args.database_state,
                        "redis_state": args.redis_state, "model_used": args.model_used},
        "url": args.url,
        "metrics_url": args.metrics_url,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "failures": failures,
        "elapsed_seconds": round(elapsed, 4),
        "requests_per_second": round(args.requests / elapsed, 2) if elapsed else 0,
        "p50_ms": _percentile_ms(latencies, 0.50),
        "p95_ms": _percentile_ms(latencies, 0.95),
        "p99_ms": _percentile_ms(latencies, 0.99),
        "database_queries": (queries_after - queries_before
                             if queries_before is not None and queries_after is not None else None),
        "redis_cache_events": cache_delta,
        "redis_cache_lookup_events": cache_lookups if cache_delta is not None else None,
        "redis_cache_event_coverage": round(cache_lookups / args.requests, 4) if cache_delta is not None else None,
        "redis_cache_hit_rate": round(cache_hits / cache_lookups, 4) if cache_lookups else None,
        "status_codes": {str(status): sum(item[0] == status for item in results) for status in sorted({item[0] for item in results})},
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            output.write(rendered + "\n")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
