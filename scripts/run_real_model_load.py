"""按显式预算运行真实模型 Gateway 小批量并发；不访问业务数据。"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

async def run(args):
    started_at = datetime.now(timezone.utc).isoformat()
    # 固定短 ASCII 输入，以 UTF-8 字节数保守预留输入 token；禁用重试/fallback。
    system = "Reply with OK only."
    prompt = "Health check."
    input_reserve = len((system + prompt).encode()) + 256
    reservation = input_reserve + args.max_output_tokens
    if args.requests * reservation > args.token_budget:
        raise SystemExit("Token 预算不足以预留全部请求输入和最大输出，未调用模型")
    from app.core.config import get_settings
    from app.modules.ai.gateway import resolve_model_profile
    from app.modules.ai.llm import chat
    from app.modules.ai.schema import AIChatMessage, AIChatRequest

    settings = get_settings()
    profile = resolve_model_profile(settings)
    settings = settings.model_copy(update={
        "llm_model_profiles_json": "", "llm_default_profile": "",
        "llm_provider": profile.provider, "llm_model": profile.model,
        "openai_base_url": profile.base_url, "openai_api_key": profile.api_key,
        "llm_max_tokens": args.max_output_tokens, "llm_max_retries": 0,
        "llm_timeout_seconds": 60, "llm_max_concurrency": args.concurrency,
    })
    results = []
    semaphore = asyncio.Semaphore(args.concurrency)
    started = perf_counter()

    async def one(index):
        async with semaphore:
            call_started = perf_counter()
            row = {"request": index}
            try:
                response = await chat(
                    AIChatRequest(messages=[AIChatMessage(role="user", content=prompt)]),
                    settings=settings, system_prompt=system, _allow_fallback=False,
                )
                row.update(status="ok", usage=response.usage,
                           nonempty_response=bool(response.message.content.strip()))
            except Exception as exc:
                # 不输出上游异常正文，避免 URL 或凭据进入报告。
                row.update(status="error", error_type=type(exc).__name__)
            row["duration_ms"] = round((perf_counter() - call_started) * 1000, 2)
            results.append(row)

    await asyncio.gather(*(one(index) for index in range(1, args.requests + 1)))
    durations = sorted(row["duration_ms"] for row in results)
    total = sum((row.get("usage") or {}).get("total_tokens", 0) for row in results)
    report = {
        "scope": "真实模型 Gateway 小样本并发；固定无业务数据提示，不代表业务质量或容量上限",
        "started_at": started_at,
        "model": profile.model, "provider": profile.provider,
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(), "requests": args.requests,
        "concurrency": args.concurrency, "token_budget": args.token_budget,
        "reserved_tokens": reservation * args.requests,
        "max_output_tokens_per_request": args.max_output_tokens,
        "retries": 0, "fallback": False, "elapsed_seconds": round(perf_counter() - started, 3),
        "observed_total_tokens": total,
        "usage_complete": all((row.get("usage") or {}).get("total_tokens") is not None for row in results),
        "latency_ms": {f"p{p}": durations[math.ceil(p / 100 * len(durations)) - 1] for p in (50, 95, 99)},
        "results": sorted(results, key=lambda row: row["request"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False))
    return all(row["status"] == "ok" and row["nonempty_response"] for row in results) and report["usage_complete"] and total <= args.token_budget


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--token-budget", type=int, required=True)
    parser.add_argument("--max-output-tokens", type=int, default=512)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.requests, args.concurrency, args.token_budget, args.max_output_tokens) <= 0:
        parser.error("所有预算和并发参数必须大于零")
    if args.output.exists():
        parser.error("输出文件已存在，请选择新路径以保留历史证据")
    sys.exit(0 if asyncio.run(run(args)) else 1)
