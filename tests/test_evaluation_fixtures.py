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
    assert report["real_model_evaluated"] is False


@pytest.mark.parametrize("relative", ["docs/evaluation/offline-numeric-associations-v1.json",
                                     "scripts/agent_business_cases.py", MANIFEST])
def test_frozen_fixture_or_manifest_drift_fails_cli(frozen_root, relative):
    path = frozen_root / relative
    path.write_bytes(path.read_bytes() + b"\n")
    result = run_check(frozen_root)
    assert result.returncode != 0
    assert "integrity" in result.stderr
