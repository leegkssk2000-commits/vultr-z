from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "tools/r7a3e5_strategy25_canonical_reaudit.py"
spec = importlib.util.spec_from_file_location("r7a3e5_reaudit_test", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_safe_repo_path_rejects_escape() -> None:
    assert module.safe_repo_path("backend/strategies/demo.py") == "backend/strategies/demo.py"
    with pytest.raises(ValueError, match="UNSAFE_REPO_PATH"):
        module.safe_repo_path("../../etc/passwd")
    with pytest.raises(ValueError, match="UNSAFE_REPO_PATH"):
        module.safe_repo_path("/etc/passwd")


def test_json_pointer_and_config_ref() -> None:
    path, pointer = module.split_config_ref(
        "backend/strategy25/canonical_strategy25_config_v1.json#/strategies/demo"
    )
    assert path == "backend/strategy25/canonical_strategy25_config_v1.json"
    assert pointer == "/strategies/demo"
    assert module.json_pointer({"strategies": {"demo": "demo"}}, pointer) == "demo"
    assert module.json_pointer({"a/b": {"~key": 7}}, "/a~1b/~0key") == 7


def test_callable_names_is_static_only() -> None:
    source = "class DemoStrategy:\n    def decide(self):\n        return 1\n\ndef strategy():\n    return 2\n"
    names = module.callable_names(source, "demo.py")
    assert names == {"DemoStrategy.decide", "strategy"}


def test_artifact_binding_classification_is_path_scoped() -> None:
    tokens = {"runtime_results", "artifact", "snapshot"}
    assert module.has_artifact_binding("runtime_results/demo.py", tokens) is True
    assert module.has_artifact_binding("backend/strategies/demo.py", tokens) is False
