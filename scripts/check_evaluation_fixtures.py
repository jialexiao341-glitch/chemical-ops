"""冻结题集完整性和数字关联离线门禁；不调用模型，不复用历史评测得分。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/evaluation/offline-guards-v2-manifest.json"
# 题集更新必须同时审阅 manifest 与此锚点，不能只改清单绕过文件校验。
MANIFEST_SHA256 = "19e0bdc49ec655d6b8a87d7bcf7e351c947833265780750d14720d4f5c424783"


def text_digest(raw: bytes) -> str:
    """仅统一 CRLF/LF，不忽略其他空白、字段顺序、尾部空行或业务值。"""
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def check_fixtures(root: Path, manifest_path: str = MANIFEST) -> dict:
    raw = (root / manifest_path).read_bytes()
    if text_digest(raw) != MANIFEST_SHA256:
        raise ValueError("manifest integrity mismatch")
    manifest = json.loads(raw)
    if manifest.get("hash_mode") != "utf8-lf":
        raise ValueError("unsupported frozen hash mode")
    files = manifest["files"]
    if not files:
        raise ValueError("empty frozen manifest")
    for entry in files:
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("fixture outside repository")
        if text_digest(path.read_bytes()) != entry["sha256"]:
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
