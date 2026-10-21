"""冻结题集完整性和数字关联离线门禁；不调用模型，不复用历史评测得分。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/evaluation/offline-guards-v1-manifest.json"
# 题集更新必须同时审阅 manifest 与此锚点，不能只改清单绕过文件校验。
MANIFEST_SHA256 = "c417d355a8a6499c09c76d625579128dc640e93b0fac9877ded46f5557b1cc80"


def check_fixtures(root: Path, manifest_path: str = MANIFEST) -> dict:
    raw = (root / manifest_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("manifest integrity mismatch")
    manifest = json.loads(raw)
    files = manifest["files"]
    if not files:
        raise ValueError("empty frozen manifest")
    for entry in files:
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("fixture outside repository")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"fixture integrity mismatch: {entry['path']}")
    cases = json.loads((root / manifest["numeric_cases"]).read_text(encoding="utf-8"))
    if len({case["id"] for case in cases}) != len(cases) or len(cases) != manifest["numeric_case_count"]:
        raise ValueError("numeric case count or unique ids mismatch")
    from app.modules.ai.numeric_fidelity import faithful_numbers
    failures = [case["id"] for case in cases if faithful_numbers(case["answer"], case["evidence"]) is not case["expected"]]
    if failures:
        raise ValueError(f"numeric oracle mismatch: {', '.join(failures)}")
    return {"mode": "deterministic_no_llm_no_writes", "files_verified": len(files),
            "numeric_cases_verified": len(cases), "real_model_evaluated": False,
            "quality_scope": "fixture integrity and deterministic guards only; no current model quality claim"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        report = check_fixtures(args.root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Frozen evaluation gate failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
