from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/r7a3e3c_strategy25_config_reference_closure.py"
spec = importlib.util.spec_from_file_location("a3e3c", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def init_repo(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "a3e3c@example.invalid")
    git(root, "config", "user.name", "A3E3C")


def test_json_pointer_and_pointer_token_round_trip():
    strategy_id = "alpha_combo"
    document = {"strategies": {strategy_id: {"period": 20}}}
    pointer = f"/strategies/{mod.pointer_token(strategy_id)}"
    ok, value = mod.json_pointer(document, pointer)
    assert ok is True
    assert value == {"period": 20}


def test_artifact_path_is_not_canonical_config_path():
    parts = {"runtime_results", "snapshot", "artifact"}
    assert mod.is_artifact_path(
        "runtime_results/q4r3/exact25_candidate_package/config/strategy25.json",
        parts,
    )
    assert not mod.is_artifact_path("backend/strategy25/canonical_strategy25_config_v1.json", parts)


def test_deleted_artifact_config_resolves_from_git_history(tmp_path: Path):
    init_repo(tmp_path)
    path = tmp_path / "runtime_results/q4r3/exact25_candidate_package/config/strategy25.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"strategies":{"alpha_combo":{"period":20}}}\n', encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "add artifact config")
    path.unlink()
    git(tmp_path, "add", "-u")
    git(tmp_path, "commit", "-qm", "remove artifact config")
    head = git(tmp_path, "rev-parse", "HEAD")

    value, receipt, errors = mod.resolve_config_value(
        tmp_path,
        head,
        "runtime_results/q4r3/exact25_candidate_package/config/strategy25.json",
        "/strategies/alpha_combo",
    )
    assert value == {"period": 20}
    assert receipt is not None
    assert receipt["source_path"].endswith("strategy25.json")
    assert not any(error.startswith("CONFIG_VALUE_NOT_FOUND") for error in errors)


def test_history_with_two_distinct_values_fails_closed(tmp_path: Path):
    init_repo(tmp_path)
    path = tmp_path / "runtime_results/x/config.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"strategies":{"alpha_combo":{"period":20}}}\n', encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "v1")
    path.write_text('{"strategies":{"alpha_combo":{"period":30}}}\n', encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "v2")
    path.unlink()
    git(tmp_path, "add", "-u")
    git(tmp_path, "commit", "-qm", "remove")
    head = git(tmp_path, "rev-parse", "HEAD")

    value, receipt, errors = mod.resolve_config_value(
        tmp_path,
        head,
        "runtime_results/x/config.json",
        "/strategies/alpha_combo",
    )
    assert value is None
    assert receipt is None
    assert any(error.startswith("CONFIG_HISTORY_AMBIGUOUS") for error in errors)
