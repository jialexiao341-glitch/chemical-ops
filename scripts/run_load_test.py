"""对指定 HTTP 接口执行轻量并发压测。"""

import argparse
import json
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
    except URLError:
        status = 0
    return status, time.perf_counter() - started


def main() -> None:
    """执行并发请求，存在非预期状态码时以失败退出。"""
    parser = argparse.ArgumentParser(description="ChemicalOps 轻量接口压测工具")
    parser.add_argument("--url", default="http://127.0.0.1:8888/health", help="被测完整 URL")
    parser.add_argument("--requests", type=int, default=100, help="总请求数")
    parser.add_argument("--concurrency", type=int, default=10, help="并发 worker 数")
    parser.add_argument("--timeout", type=float, default=10, help="单请求超时秒数")
    parser.add_argument("--token", default="", help="可选 Bearer token")
    parser.add_argument("--expected-status", type=int, default=200, help="期望 HTTP 状态码")
    args = parser.parse_args()
    if args.requests <= 0 or args.concurrency <= 0 or args.timeout <= 0:
        raise SystemExit("requests、concurrency 和 timeout 必须大于 0")
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(executor.map(lambda _: _request(args.url, headers, args.timeout), range(args.requests)))
    elapsed = time.perf_counter() - started
    latencies = sorted(item[1] for item in results)
    failures = sum(status != args.expected_status for status, _ in results)
    report = {
        "url": args.url,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "failures": failures,
        "elapsed_seconds": round(elapsed, 4),
        "requests_per_second": round(args.requests / elapsed, 2) if elapsed else 0,
        "p50_ms": round(latencies[len(latencies) // 2] * 1000, 2),
        "p95_ms": round(latencies[max(0, int(len(latencies) * 0.95) - 1)] * 1000, 2),
        "status_codes": {str(status): sum(item[0] == status for item in results) for status in sorted({item[0] for item in results})},
    }
    print(json.dumps(report, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
