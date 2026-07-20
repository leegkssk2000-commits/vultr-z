from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/r7_restore25_git_object_driver.py"
old_argv = sys.argv[:]
sys.argv = [str(MODULE_PATH), "--target-sha", "test-sha"]
try:
    spec = importlib.util.spec_from_file_location("restore25_git_driver", MODULE_PATH)
    assert spec and spec.loader
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
finally:
    sys.argv = old_argv


def run(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def test_target_sha_materializes_artifact_when_worktree_file_is_missing(tmp_path: Path):
    run(tmp_path, "init")
    run(tmp_path, "config", "user.email", "restore25@example.invalid")
    run(tmp_path, "config", "user.name", "restore25-test")
    relative = Path(
        "runtime_results/q4r3/strategy_source_snapshot/source/backend/strategies/alpha_combo.py"
    )
    source_path = tmp_path / relative
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "def evaluate(ctx):\n    return {'signal': 'hold'}\n", encoding="utf-8"
    )
    run(tmp_path, "add", relative.as_posix())
    run(tmp_path, "commit", "-m", "artifact snapshot")
    target_sha = run(tmp_path, "rev-parse", "HEAD")
    source_path.unlink()

    rows, reasons = driver.artifact_rows_from_git(
        tmp_path,
        {"artifact_matches": [{"path": relative.as_posix(), "callable": "evaluate"}]},
        target_sha,
    )

    assert reasons == []
    assert len(rows) == 1
    assert rows[0]["materialized_from"] == "GIT_OBJECT"
    assert rows[0]["materialized_revision"] == target_sha
    assert rows[0]["callable"] == "evaluate"


def test_unsafe_artifact_paths_are_rejected():
    assert driver.safe_repo_path("../../etc/passwd") is None
    assert driver.safe_repo_path("/etc/passwd") is None
    assert driver.safe_repo_path("runtime_results/x.py") == "runtime_results/x.py"
