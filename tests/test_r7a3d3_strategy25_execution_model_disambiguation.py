from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/r7a3d3_strategy25_execution_model_disambiguation.py"
spec = importlib.util.spec_from_file_location("r7a3d3", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_diagnostic_paths_are_rejected():
    assert module.diagnostic_path("tools/bootstrap_strategy_probe.py") is True
    assert module.diagnostic_path("backend/strategies/trend_ma_macd.py") is False


def test_unique_direct_module_resolves():
    candidate = {
        "implementation_path": "backend/strategies/trend_ma_macd.py",
        "callable": "evaluate",
        "binding_kind": "direct",
        "score": 170,
    }
    mapping = {"evidence": [], "test_refs": ["tests/test_strategy.py"]}
    result = module.choose_model(
        "trend_ma_macd", [candidate], mapping,
        Counter({module.candidate_key(candidate): 1}), [], 20,
    )
    assert result["resolved"] is True
    assert result["execution_model"] == "DIRECT_MODULE"


def test_multiple_shared_engines_remain_unresolved():
    candidates = [
        {"implementation_path": "backend/engine_a.py", "callable": "evaluate", "binding_kind": "registry_or_shared"},
        {"implementation_path": "backend/engine_b.py", "callable": "evaluate", "binding_kind": "registry_or_shared"},
    ]
    evidence = [
        {
            "source_path": candidate["implementation_path"],
            "callable": "evaluate",
            "config_keys": ["trigger", "risk"],
            "kind": "PYTHON_LITERAL_REGISTRY_KEY",
        }
        for candidate in candidates
    ]
    prevalence = Counter({module.candidate_key(candidate): 25 for candidate in candidates})
    result = module.choose_model("alpha_combo", candidates, {"evidence": evidence}, prevalence, [], 20)
    assert result["resolved"] is False
    assert result["shared_engine_candidate_count"] == 2


def test_unique_shared_engine_with_explicit_binding_resolves():
    candidate = {
        "implementation_path": "backend/shared_strategy_engine.py",
        "callable": "evaluate",
        "binding_kind": "registry_or_shared",
    }
    mapping = {
        "evidence": [{
            "source_path": "backend/shared_strategy_engine.py",
            "callable": "evaluate",
            "config_keys": ["trigger", "risk"],
            "kind": "PYTHON_LITERAL_REGISTRY_KEY",
        }]
    }
    result = module.choose_model(
        "alpha_combo", [candidate], mapping,
        Counter({module.candidate_key(candidate): 25}), [], 20,
    )
    assert result["resolved"] is True
    assert result["execution_model"] == "SHARED_ENGINE_CONFIG"
