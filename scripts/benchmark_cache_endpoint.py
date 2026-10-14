"""对缓存只读 HTTP 接口执行串行冷/热对照并记录应用指标。"""

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
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _get(url: str, headers: dict[str, str], timeout: float) -> tuple[int, float]:
    started = time.perf_counter()
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            status = response.status
    except HTTPError as exc:
        status = exc.code
    except (URLError, TimeoutError, OSError, http.client.HTTPException):
        status = 0
    return status, time.perf_counter() - started


def _percentile_ms(sorted_durations: list[float], quantile: float) -> float:
    """按 nearest-rank 口径计算延迟分位数。"""
    index = max(0, math.ceil(quantile * len(sorted_durations)) - 1)
    return round(sorted_durations[index] * 1000, 2)


def _snapshot(url: str, timeout: float, space: str) -> tuple[int | None, dict[str, int]]:
    with urlopen(url, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    selects = 0
    select_found = False
    cache: dict[str, int] = {}
    for line in body.splitlines():
        if line.startswith("#"):
            continue
        query_match = re.match(r'chemicalops_database_queries_count\{([^}]*)\}\s+([\d.]+)', line)
        if query_match and re.search(r'operation="SELECT"', query_match.group(1)):
            selects += int(float(query_match.group(2)))
            select_found = True
        cache_match = re.match(r'chemicalops_redis_cache_count\{([^}]*)\}\s+([\d.]+)', line)
        if cache_match:
            labels = cache_match.group(1)
            if re.search(rf'space="{re.escape(space)}"', labels):
                result = re.search(r'result="([^"]+)"', labels)
                if result:
                    cache[result.group(1)] = cache.get(result.group(1), 0) + int(float(cache_match.group(2)))
    return (selects if select_found else None), cache


def _phase(name: str, count: int, url: str, headers: dict[str, str], timeout: float,
           metrics_url: str, concurrency: int, space: str) -> dict[str, object]:
    before_queries, before_cache = _snapshot(metrics_url, timeout, space)

    def request(_index: int) -> tuple[int, float]:
        if name == "cold":
            # The benchmark uses one worker for cold samples, so invalidating a shared
            # version key cannot race with another request in the same phase.
            from app.core.cache import invalidate

            invalidate(space)
        return _get(url, headers, timeout)

    phase_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(request, range(count)))
    elapsed = time.perf_counter() - phase_started
    after_queries, after_cache = _snapshot(metrics_url, timeout, space)
    durations = sorted(item[1] for item in results)
    events = {key: max(0, after_cache.get(key, 0) - before_cache.get(key, 0))
              for key in set(before_cache) | set(after_cache)}
    hits, misses = events.get("hit", 0), events.get("miss", 0)
    lookup_events = hits + misses
    return {
        "requests": count,
        "concurrency": concurrency,
        "elapsed_seconds": round(elapsed, 4),
        "requests_per_second": round(count / elapsed, 2) if elapsed else 0,
        "failures": sum(status != 200 for status, _ in results),
        "status_codes": {str(status): sum(item[0] == status for item in results)
                         for status in sorted({item[0] for item in results})},
        "database_selects": (after_queries - before_queries
                             if before_queries is not None and after_queries is not None else None),
        "redis_cache_events": events,
        "redis_cache_lookup_events": lookup_events,
        "cache_event_coverage": round(lookup_events / count, 4),
        "cache_hit_rate": round(hits / lookup_events, 4) if lookup_events else None,
        "p50_ms": _percentile_ms(durations, 0.50),
        "p95_ms": _percentile_ms(durations, 0.95),
        "p99_ms": _percentile_ms(durations, 0.99),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="对一个缓存接口运行串行冷/热对照")
    parser.add_argument("--url", required=True, help="完整 GET API URL")
    parser.add_argument("--space", required=True, help="缓存空间名，如 product_catalog")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:8888/metrics")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if args.requests <= 0 or args.timeout <= 0:
        raise SystemExit("requests 和 timeout 必须大于 0")
    token = os.environ.get("CHEMICALOPS_LOAD_TEST_TOKEN", "").strip()
    if not token:
        raise SystemExit("请先设置 CHEMICALOPS_LOAD_TEST_TOKEN")
    from app.core.config import get_settings
    from app.core.redis_client import get_redis
    from sqlalchemy.engine import make_url

    runtime = get_settings()
    if not runtime.redis_enabled or get_redis() is None:
        raise SystemExit("本地基准进程的 Redis 配置不可用")
    client = get_redis()
    if client is None:
        raise SystemExit("Redis 未启用")
    client.ping()
    database_url = make_url(runtime.resolved_database_url)
    headers = {"Authorization": f"Bearer {token}"}
    cold = _phase("cold", args.requests, args.url, headers, args.timeout,
                  args.metrics_url, concurrency=1, space=args.space)
    hot = _phase("hot", args.requests, args.url, headers, args.timeout,
                 args.metrics_url, concurrency=1, space=args.space)
    report = {
        "environment": {"platform": platform.platform(), "python": sys.version.split()[0],
                        "app_env": runtime.app_env, "api_instances": 1,
                        "redis_enabled": runtime.redis_enabled,
                        "redis_version": client.info("server").get("redis_version"),
                        "database_driver": database_url.drivername,
                        "database_endpoint": f"{database_url.host}:{database_url.port}",
                        "database_metric_scope": "target API process SELECT counter, including authentication and permission queries",
                        "model_used": False},
        "url": args.url,
        "cache_space": args.space,
        "cold": cold,
        "hot": hot,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    if cold["failures"] or hot["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
