"""冻结样本或 oracle 发生漂移时 CI 必须非零退出。"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_evaluation_fixtures import MANIFEST, ROOT


@pytest.fixture
def frozen_root(tmp_path):
    manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    for relative in [MANIFEST, *(entry["path"] for entry in manifest["files"])]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return tmp_path


def run_check(root):
    return subprocess.run([sys.executable, str(ROOT / "scripts/check_evaluation_fixtures.py"), "--root", str(root)],
                          capture_output=True, text=True, encoding="utf-8")


def test_frozen_offline_gate_has_no_real_model_quality_claim(frozen_root):
    result = run_check(frozen_root)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["numeric_cases_verified"] == 12
    assert report["files_verified"] == 5
    assert report["real_model_evaluated"] is False


@pytest.mark.parametrize("relative", ["docs/evaluation/offline-numeric-associations-v1.json",
                                     "docs/evaluation/agent-business-v1-cases.json",
                                     "scripts/agent_business_cases.py", "scripts/agent_evaluation_data.py",
                                     "scripts/evaluate_agent_tasks.py", MANIFEST])
def test_frozen_fixture_or_manifest_drift_fails_cli(frozen_root, relative):
    path = frozen_root / relative
    path.write_bytes(path.read_bytes() + b"\n")
    result = run_check(frozen_root)
    assert result.returncode != 0
    reason = "manifest integrity mismatch" if relative == MANIFEST else f"fixture integrity mismatch: {relative}"
    assert reason in result.stderr


def test_frozen_gate_accepts_only_line_ending_changes(frozen_root):
    """仅换行符差异等价；尾部空行和其他内容变化仍由各文件篡改用例拦截。"""
    manifest = json.loads((frozen_root / MANIFEST).read_text(encoding='utf-8'))
    for relative in [MANIFEST, *(entry['path'] for entry in manifest['files'])]:
        path = frozen_root / relative
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    result = run_check(frozen_root)
    assert result.returncode == 0, result.stderr
