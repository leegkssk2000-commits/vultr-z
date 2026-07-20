from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/r7_restore25_canonical_source_recovery.py"
spec = importlib.util.spec_from_file_location("restore25", MODULE_PATH)
assert spec and spec.loader
restore25 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore25)


def test_artifact_paths_are_never_true_sources():
    allowed = ["backend/strategies/", "backend/strategy25/"]
    assert not restore25.is_true_source(
        "runtime_results/q4r3/strategy_source_snapshot/source/backend/strategies/alpha_combo.py",
        allowed,
    )
    assert restore25.is_true_source("backend/strategies/alpha_combo.py", allowed)


def test_normalized_module_ast_ignores_formatting_and_comments():
    left = "def evaluate(x):\n    # comment\n    return {'signal': 'hold'}\n"
    right = "def evaluate(x):\n\n    return {\"signal\": \"hold\"}\n"
    assert restore25.module_ast_sha(left) == restore25.module_ast_sha(right)


def test_callable_selection_is_fail_closed():
    source = "def evaluate(ctx):\n    return {'signal':'hold'}\n"
    matches = [{"callable": "evaluate"}, {"callable": "evaluate"}]
    assert restore25.choose_callable(source, "backend/strategies/x.py", matches) == "evaluate"
    ambiguous = "def evaluate(ctx):\n    return 1\ndef run(ctx):\n    return 2\n"
    assert restore25.choose_callable(ambiguous, "backend/strategies/x.py", []) is None
