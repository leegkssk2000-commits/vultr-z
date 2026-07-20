from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "tools/r7a3e3_strategy25_contract_tests_after_restore25.py"
spec = importlib.util.spec_from_file_location("r7a3e3", MODULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_safe_repo_path_rejects_traversal_and_absolute_paths():
    assert mod.safe_repo_path("../../etc/passwd") is None
    assert mod.safe_repo_path("/etc/passwd") is None
    assert mod.safe_repo_path("backend/strategies/alpha.py") == "backend/strategies/alpha.py"


def test_artifact_paths_are_not_canonical_sources():
    prefixes = ["backend/strategies/"]
    artifacts = {"runtime_results", "snapshot", "exact25_candidate_package"}
    assert mod.allowed_path("backend/strategies/alpha.py", prefixes, artifacts)
    assert not mod.allowed_path(
        "runtime_results/q4r3/exact25_candidate_package/source/backend/strategies/alpha.py",
        prefixes,
        artifacts,
    )


def test_json_pointer_resolves_and_unescapes_tokens():
    value = {"strategies": {"a/b": {"~key": {"enabled": False}}}}
    ok, result = mod.json_pointer(value, "/strategies/a~1b/~0key")
    assert ok is True
    assert result == {"enabled": False}
    assert mod.json_pointer(value, "/strategies/missing")[0] is False


def test_callable_names_support_functions_and_class_methods():
    source = "def evaluate(ctx):\n    return None\nclass Engine:\n    def run(self, ctx):\n        return None\n"
    assert mod.callable_names(source, "x.py") == {"evaluate", "Engine.run"}


def test_config_ref_requires_path_and_pointer():
    assert mod.split_config_ref("config/exact25.json#/strategies/alpha") == (
        "config/exact25.json",
        "/strategies/alpha",
    )
    assert mod.split_config_ref("config/exact25.json") == (None, None)
