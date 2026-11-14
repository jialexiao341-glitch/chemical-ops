"""统一评测 harness：多轮采样、断点续跑、统一 envelope 与失败分类。

四个既有评测脚本保持独立可运行；本脚本只负责编排与汇总，不改写历史报告。
envelope 结构：
    {
      "suite", "generated_at", "model", "prompt_sha256", "code_revision",
      "dataset_sha256", "repeat",
      "cases": [{"key", "safety", "trials": [
          {"trial", "passed", "status", "error_classes", "failed_checks"}]}],
      "summary": {"total", "passed", "failed", "infra_failed", "verdict"}
    }

`--suite all` 一次跑完四个套件，写入 `--out-dir/harness-<suite>.json`，供
`eval_prompt_gate.py --mode envelope` 直接消费；单套件模式可用 `--out` 指定单文件路径。
`--resume` 复用已完成轮次，但含基础设施/响应超时失败（TRANSIENT_INFRA / AMBIGUOUS_TIMEOUT）
或异常中断的轮次默认重跑（business 支持保留已通过用例并仅补跑受污染用例），
避免把一次模型抖动固化成稳定性结论；确需复用时显式加 `--reuse-infra`。

退出码：0 全部通过；1 存在实现失败；2 仅剩基础设施失败（本轮不可作证据）。
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_stability import INFRA_ERROR_CLASSES, extract_error_classes, is_infra_classes  # noqa: E402

PYTHON = sys.executable
TRIAL_SUFFIX = ".trial-{index}.json"

SUITES = ("routing", "tasks", "business", "prod")


def trial_path(out: Path, index: int) -> Path:
    """每轮写独立文件，便于断点续跑与事后核对。"""
    return out.with_name(out.stem + TRIAL_SUFFIX.format(index=index))


def suite_envelope_path(directory: Path, suite: str) -> Path:
    """多套件模式的固定文件布局；门禁按同一命名查找，避免两处各写一套路径。"""
    return directory / f"harness-{suite}.json"


def build_command(
    suite: str,
    out: Path,
    *,
    workers: int,
    shard_index: int | None = None,
    shard_count: int | None = None,
    resume_trial: bool = False,
) -> list[str]:
    """按套件拼评测命令；参数只做最小必要传递，其余沿用脚本默认值。"""
    if shard_index is not None or shard_count is not None:
        if shard_index is None or shard_count is None or shard_count < 1 or not 1 <= shard_index <= shard_count:
            raise ValueError("分片参数无效：需同时提供 --shard-index 与 --shard-count，且 1 <= shard_index <= shard_count")
        if suite != "business" and shard_count > 1:
            raise ValueError("目前仅 business 套件支持分片")
    if suite == "routing":
        return [PYTHON, str(ROOT / "scripts/evaluate_intent_routing.py"),
                "--output", str(out), "--repeats", "1"]
    if suite == "tasks":
        return [PYTHON, str(ROOT / "scripts/evaluate_agent_tasks.py"), "--output", str(out)]
    if suite == "business":
        # 逐任务原始结果落在输出目录旁，避免依赖只读的 .cache。
        scratch = out.parent / f"{out.stem}.scratch"
        command = [PYTHON, str(ROOT / "scripts/evaluate_agent_business.py"),
                   "--output", str(out), "--repetitions", "1", "--workers", str(workers),
                   "--scratch-dir", str(scratch)]
        if shard_count and shard_count > 1:
            command += ["--shard-index", str(shard_index), "--shard-count", str(shard_count)]
        if resume_trial:
            command += ["--resume", "--drop-infra"]
        return command
    if suite == "prod":
        return [PYTHON, str(ROOT / "scripts/evaluate_prod_regression.py"),
                "--cases", str(ROOT / "docs/evaluation/prod-regression/cases.json"),
                "--output", str(out)]
    raise ValueError(f"未知套件：{suite}")


def _case_key(row: dict) -> str:
    if row.get("id") is not None:
        return str(row["id"])
    if row.get("question") is not None:
        return str(row["question"])
    raise ValueError("用例缺少 id 与 question，无法建立稳定键")


_error_classes = extract_error_classes


def _failed_checks(row: dict) -> list[str]:
    """保留本轮失败的检查项名，供门禁报告定位退化环节。"""
    checks = row.get("checks") or {}
    if not isinstance(checks, dict):
        return []
    return sorted(str(name) for name, value in checks.items() if value is False)


def _runner_error_classes(err: dict) -> list[str]:
    """从 runner_errors 兼容条目提取错误分类，确保子进程超时不会静默丢轮次。"""
    if err.get("error_class"):
        return [str(err["error_class"])]
    if err.get("error_type") == "TimeoutExpired":
        return ["AMBIGUOUS_TIMEOUT"]
    return []


def _summarize_envelope_cases(ordered: list[dict]) -> dict:
    """按全通过、仅基础设施失败与实现失败统计 envelope 汇总结论。"""
    passed = [entry for entry in ordered if all(t["passed"] for t in entry["trials"])]
    failed = [entry for entry in ordered if entry not in passed]
    infra_only = [entry for entry in failed
                  if all(is_infra_classes(t["error_classes"])
                         for t in entry["trials"] if not t["passed"])]
    if not failed:
        verdict = "PASS"
    elif len(infra_only) == len(failed):
        verdict = "INVALID_RUN"
    else:
        verdict = "FAILURES"
    return {
        "total": len(ordered),
        "passed": len(passed),
        "failed": len(failed),
        "infra_failed": len(infra_only),
        "verdict": verdict,
    }


def merge_trials(suite: str, reports: list[dict], repeat: int) -> dict:
    """把多轮原始报告合成 envelope；同一 key 的每轮结果都保留。"""
    cases: dict[str, dict] = {}
    safety: dict[str, bool] = {}
    for index, report in enumerate(reports, start=1):
        rows = [row for row in (report.get("cases") or []) if isinstance(row, dict)]
        seen_in_round: set[str] = set()
        for row in rows:
            key = _case_key(row)
            seen_in_round.add(key)
            safety[key] = safety.get(key, False) or bool(row.get("safety"))
            entry = cases.setdefault(key, {"key": key, "trials": []})
            entry["trials"].append({
                "trial": index,
                "passed": bool(row.get("passed")),
                "status": row.get("status"),
                "error_classes": sorted(_error_classes(row)),
                "failed_checks": _failed_checks(row),
            })
        # 兼容旧报告或异常中断只写了 runner_errors 而缺席 cases 的情况，绝不允许漏记轮次变成假全过。
        for err in (report.get("runner_errors") or []):
            if not isinstance(err, dict) or err.get("id") is None:
                continue
            key = str(err["id"])
            if key in seen_in_round:
                continue
            seen_in_round.add(key)
            safety.setdefault(key, False)
            entry = cases.setdefault(key, {"key": key, "trials": []})
            error_type = str(err.get("error_type") or "UNKNOWN")
            entry["trials"].append({
                "trial": index,
                "passed": False,
                "status": f"RUNNER_ERROR:{error_type}",
                "error_classes": sorted(_runner_error_classes(err)),
                "failed_checks": [f"runner_error:{error_type}"],
            })
    ordered = list(cases.values())
    for entry in ordered:
        entry["safety"] = safety.get(entry["key"], False)
    meta_source = next((r for r in reports if r.get("model") or r.get("code_revision")), {})
    return {
        "suite": suite,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repeat": repeat,
        "model": meta_source.get("model"),
        "prompt_sha256": meta_source.get("prompt_sha256") or meta_source.get("planner_sha256"),
        "code_revision": meta_source.get("code_revision"),
        "dataset_sha256": meta_source.get("dataset_sha256"),
        "cases": ordered,
        "summary": _summarize_envelope_cases(ordered),
    }


def merge_trial_shard_reports(reports: list[dict]) -> dict:
    """合并同一轮内多个互不相交分片的原始报告，生成完整单轮报告以复用 --resume。"""
    if not reports:
        raise ValueError("分片报告列表不能为空")
    first = reports[0]
    for field in ("model", "planner_sha256", "prompt_sha256", "dataset_sha256", "code_revision"):
        expected = first.get(field)
        for report in reports[1:]:
            if expected is not None and report.get(field) is not None and report.get(field) != expected:
                raise ValueError(f"分片元数据 {field} 不一致：{expected} != {report.get(field)}")
    merged_cases: list[dict] = []
    seen: set[str] = set()
    for report in reports:
        for row in (report.get("cases") or []):
            if not isinstance(row, dict):
                continue
            key = _case_key(row)
            if key in seen:
                raise ValueError(f"分片包含重复用例：{key}")
            seen.add(key)
            merged_cases.append(row)
    merged_cases.sort(key=_case_key)
    merged = dict(first)
    merged.pop("shard", None)
    merged["cases"] = merged_cases
    merged["unique_cases"] = len(merged_cases)
    merged["completed_runs"] = len(merged_cases)
    merged["planned_runs"] = len(merged_cases)
    return merged


def merge_envelopes(envelopes: list[dict]) -> dict:
    """把同一套件的多份分片 envelope 合并为单一规范 envelope 并重算汇总结论。"""
    if not envelopes:
        raise ValueError("分片 envelope 列表不能为空")
    first = envelopes[0]
    suite = first.get("suite")
    repeat = first.get("repeat")
    for env in envelopes[1:]:
        if env.get("suite") != suite:
            raise ValueError(f"分片套件不一致：{suite} != {env.get('suite')}")
        if env.get("repeat") != repeat:
            raise ValueError(f"分片轮次不一致：{repeat} != {env.get('repeat')}")
        for field in ("model", "prompt_sha256", "dataset_sha256", "code_revision"):
            expected, current = first.get(field), env.get(field)
            if expected is not None and current is not None and current != expected:
                raise ValueError(f"分片元数据 {field} 不一致：{expected} != {current}")
    merged_cases: list[dict] = []
    seen: set[str] = set()
    for env in envelopes:
        for case in (env.get("cases") or []):
            if not isinstance(case, dict) or case.get("key") is None:
                continue
            key = str(case["key"])
            if key in seen:
                raise ValueError(f"分片包含重复用例：{key}")
            seen.add(key)
            merged_cases.append(case)
    merged_cases.sort(key=lambda item: str(item["key"]))
    return {
        "suite": suite,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repeat": repeat,
        "model": first.get("model"),
        "prompt_sha256": first.get("prompt_sha256"),
        "code_revision": first.get("code_revision"),
        "dataset_sha256": first.get("dataset_sha256"),
        "cases": merged_cases,
        "summary": _summarize_envelope_cases(merged_cases),
    }


def _contaminated(report: dict) -> bool:
    """本轮存在“失败且错误类别全是基础设施”或存在 runner_errors 缺失用例时，该轮不能作为稳定性证据。

    resume 默认重跑这类轮次：静默复用会把一次模型抖动固化成“2/3 通过”的假波动。
    """
    if report.get("runner_errors"):
        return True
    for row in (report.get("cases") or []):
        if not isinstance(row, dict) or row.get("passed"):
            continue
        if is_infra_classes(_error_classes(row)):
            return True
    return False


def _default_runner(command: list[str], out: Path) -> dict:
    """评测脚本在有用例失败时也返回 1，只有报告缺失才算运行失败。"""
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
    if not out.exists():
        raise RuntimeError(
            f"评测未生成报告（退出码 {completed.returncode}）："
            f"{(completed.stderr or completed.stdout or '').strip()[:400]}")
    return json.loads(out.read_text(encoding="utf-8"))


def _shard_trial_path(path: Path, shard_index: int, shard_count: int) -> Path:
    return path.with_name(f"{path.stem}.shard-{shard_index}of{shard_count}.json")


def run(
    suite: str,
    out: Path,
    *,
    repeat: int = 1,
    workers: int = 2,
    resume: bool = False,
    reuse_infra: bool = False,
    runner=None,
    shard_index: int | None = None,
    shard_count: int | None = None,
    business_shards: int = 1,
) -> dict:
    """执行（或在 resume 时复用）每轮报告，再合成 envelope 并落盘。"""
    if repeat < 1:
        raise ValueError("repeat 必须为正数")
    if business_shards < 1 or business_shards > 4:
        raise ValueError("business_shards 必须在 1 到 4 之间")
    if (shard_index is not None or shard_count is not None) and business_shards > 1:
        raise ValueError("--shard-index/--shard-count 不能与 --business-shards 同时使用")
    if business_shards > 1 and suite != "business":
        raise ValueError("只有 business 套件支持本地分片并行")
    runner = runner or _default_runner
    reports: list[dict] = []
    for index in range(1, repeat + 1):
        path = trial_path(out, index)
        rerunning_contaminated = False
        if resume and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if reuse_infra or not _contaminated(data):
                reports.append(data)
                continue
            rerunning_contaminated = True
            print(f"[harness] 第 {index} 轮含基础设施失败，重跑：{path}", flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        if suite == "business" and business_shards > 1:
            with ThreadPoolExecutor(max_workers=business_shards) as pool:
                futures = [
                    pool.submit(
                        runner,
                        build_command(
                            suite,
                            _shard_trial_path(path, idx, business_shards),
                            workers=workers,
                            shard_index=idx,
                            shard_count=business_shards,
                            resume_trial=(rerunning_contaminated and _shard_trial_path(path, idx, business_shards).exists()),
                        ),
                        _shard_trial_path(path, idx, business_shards),
                    )
                    for idx in range(1, business_shards + 1)
                ]
                shard_reports = [future.result() for future in futures]
            trial_report = merge_trial_shard_reports(shard_reports)
            path.write_text(json.dumps(trial_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            reports.append(trial_report)
        else:
            reports.append(
                runner(
                    build_command(
                        suite,
                        path,
                        workers=workers,
                        shard_index=shard_index,
                        shard_count=shard_count,
                        resume_trial=(rerunning_contaminated and suite == "business" and path.exists()),
                    ),
                    path,
                )
            )
    envelope = merge_trials(suite, reports, repeat)
    if shard_count and shard_count > 1:
        envelope["shard"] = {"index": shard_index, "count": shard_count}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return envelope


def run_all(
    out_dir: Path,
    *,
    suites=SUITES,
    repeat: int = 1,
    workers: int = 2,
    resume: bool = False,
    reuse_infra: bool = False,
    runner=None,
    business_shards: int = 1,
    parallel_suites: bool = False,
) -> dict[str, dict]:
    """按套件依次或并发跑完并各写一份 envelope；单套件等价于 run(suite, path)。"""
    suite_list = list(suites)
    if not parallel_suites or len(suite_list) <= 1:
        envelopes: dict[str, dict] = {}
        for suite in suite_list:
            shards = business_shards if suite == "business" else 1
            envelopes[suite] = run(
                suite,
                suite_envelope_path(out_dir, suite),
                repeat=repeat,
                workers=workers,
                resume=resume,
                reuse_infra=reuse_infra,
                runner=runner,
                business_shards=shards,
            )
        return envelopes
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(suite_list)) as pool:
        futures = {
            pool.submit(
                run,
                suite,
                suite_envelope_path(out_dir, suite),
                repeat=repeat,
                workers=workers,
                resume=resume,
                reuse_infra=reuse_infra,
                runner=runner,
                business_shards=business_shards if suite == "business" else 1,
            ): suite
            for suite in suite_list
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return {suite: results[suite] for suite in suite_list}


def worst_verdict(verdicts) -> str:
    """多套件汇总时按“实现失败 > 证据不可用 > 通过”取最严重的一档。"""
    verdicts = set(verdicts)
    if "FAILURES" in verdicts:
        return "FAILURES"
    if "INVALID_RUN" in verdicts:
        return "INVALID_RUN"
    return "PASS"


def render_text(envelope: dict) -> str:
    summary = envelope["summary"]
    return "\n".join([
        f"套件：{envelope['suite']}  重复：{envelope['repeat']} 次",
        f"模型：{envelope.get('model') or '—'}  代码：{envelope.get('code_revision') or '—'}",
        f"用例：{summary['passed']}/{summary['total']} 通过；"
        f"失败 {summary['failed']} 条，其中基础设施 {summary['infra_failed']} 条",
        f"判定：{summary['verdict']}",
    ])


def render_all_text(envelopes: dict[str, dict]) -> str:
    lines = []
    for suite, envelope in envelopes.items():
        summary = envelope["summary"]
        lines.append(f"{suite}：{summary['passed']}/{summary['total']} 通过；"
                     f"失败 {summary['failed']}，基础设施 {summary['infra_failed']}；"
                     f"{summary['verdict']}")
    lines.append(f"综合判定：{worst_verdict(env['summary']['verdict'] for env in envelopes.values())}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=("all",) + SUITES, default="all")
    parser.add_argument("--suites", nargs="+", choices=SUITES, default=None,
                        help="指定要运行的多套件子集（覆盖 --suite）")
    parser.add_argument("--out", type=Path, help="单套件或合并分片 envelope 输出路径（可省略）")
    parser.add_argument("--out-dir", type=Path,
                        default=ROOT / "docs/evaluation/candidate" / "envelopes",
                        help="多套件输出目录，写入 harness-<suite>.json")
    parser.add_argument("--repeat", type=int, default=1, help="同一套件重复采样次数")
    parser.add_argument("--workers", type=int, default=2, help="business 套件并发数")
    parser.add_argument("--shard-index", type=int, default=None, help="单套件分片序号（从 1 开始，仅 business）")
    parser.add_argument("--shard-count", type=int, default=None, help="单套件总分片数（仅 business）")
    parser.add_argument("--business-shards", type=int, default=1,
                        help="本地同机每轮拆分的 business 并行分片数（1-4）")
    parser.add_argument("--parallel-suites", action="store_true",
                        help="多套件同时执行，缩短全量墙钟耗时")
    parser.add_argument("--merge-shards", nargs="+", type=Path, default=None,
                        help="合并多份分片 envelope 为单一规范 envelope")
    parser.add_argument("--resume", action="store_true",
                        help="复用已有 trial 报告，只补缺失轮次；含基础设施失败的轮次默认重跑")
    parser.add_argument("--reuse-infra", action="store_true",
                        help="resume 时也复用含基础设施失败的轮次（仅限人工确认可接受时）")
    parser.add_argument("--json", action="store_true", help="输出 envelope JSON")
    args = parser.parse_args(argv)
    try:
        if args.merge_shards:
            shards = [json.loads(path.read_text(encoding="utf-8")) for path in args.merge_shards]
            envelope = merge_envelopes(shards)
            out = args.out or suite_envelope_path(args.out_dir, str(envelope["suite"]))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            envelopes = {str(envelope["suite"]): envelope}
            payload = envelope
            single_mode = True
        elif args.suites:
            envelopes = run_all(
                args.out_dir,
                suites=args.suites,
                repeat=args.repeat,
                workers=args.workers,
                resume=args.resume,
                reuse_infra=args.reuse_infra,
                business_shards=args.business_shards,
                parallel_suites=args.parallel_suites,
            )
            payload = envelopes
            single_mode = False
        elif args.suite == "all":
            envelopes = run_all(
                args.out_dir,
                repeat=args.repeat,
                workers=args.workers,
                resume=args.resume,
                reuse_infra=args.reuse_infra,
                business_shards=args.business_shards,
                parallel_suites=args.parallel_suites,
            )
            payload = envelopes
            single_mode = False
        else:
            out = args.out or suite_envelope_path(args.out_dir, args.suite)
            envelope = run(
                args.suite,
                out,
                repeat=args.repeat,
                workers=args.workers,
                resume=args.resume,
                reuse_infra=args.reuse_infra,
                shard_index=args.shard_index,
                shard_count=args.shard_count,
                business_shards=args.business_shards,
            )
            envelopes = {args.suite: envelope}
            payload = envelope
            single_mode = True
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"评测失败：{exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload) if single_mode else render_all_text(payload))
    verdict = worst_verdict(env["summary"]["verdict"] for env in envelopes.values())
    return 0 if verdict == "PASS" else (2 if verdict == "INVALID_RUN" else 1)


if __name__ == "__main__":
    raise SystemExit(main())