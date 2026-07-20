from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "tools/r7_restore25_atomic_apply_driver.py"
spec = importlib.util.spec_from_file_location("restore25_atomic", MODULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def git(root: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return cp.stdout.strip()


def test_exact_direct_engine_can_be_loaded_from_deleted_git_path(tmp_path: Path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "restore25@example.invalid")
    git(tmp_path, "config", "user.name", "Restore25")
    path = tmp_path / "backend/strategies/alpha_combo.py"
    path.parent.mkdir(parents=True)
    source = "def evaluate(ctx):\n    return {'signal': 'hold'}\n"
    path.write_text(source, encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "add direct engine")
    blob = git(tmp_path, "rev-parse", "HEAD:backend/strategies/alpha_combo.py")
    path.unlink()
    git(tmp_path, "add", "-u")
    git(tmp_path, "commit", "-qm", "remove direct engine")
    head = git(tmp_path, "rev-parse", "HEAD")

    recovered, error = mod.exact_path_source(
        tmp_path,
        "backend/strategies/alpha_combo.py",
        "evaluate",
        blob,
        head,
    )
    assert error is None
    assert recovered == source


def test_direct_engine_path_must_be_production_source(tmp_path: Path):
    source, error = mod.exact_path_source(
        tmp_path,
        "runtime_results/x/backend/strategies/alpha_combo.py",
        "evaluate",
        None,
        "deadbeef",
    )
    assert source is None
    assert error == "DIRECT_PATH_INVALID"
