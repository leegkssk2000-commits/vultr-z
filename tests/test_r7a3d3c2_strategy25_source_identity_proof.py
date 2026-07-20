from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "tools/r7a3d3c2_strategy25_source_identity_proof.py"
spec = importlib.util.spec_from_file_location("r7a3d3c2", MODULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_normalize():
    assert mod.normalize("anchor_vwap-trend") == "anchorvwaptrend"


def test_binding_reference_exact_id():
    ref = {"json_path": "strategies.anchor_vwap_trend.callable", "config_keys": []}
    assert mod.ref_has_strategy_id(ref, "anchor_vwap_trend")


def test_prior_proven_is_preserved(tmp_path: Path):
    row = {
        "strategy_id": "alpha_combo",
        "registry_patch_ready": True,
        "canonical_mapping": {"implementation_path": "backend/alpha.py", "callable": "evaluate"},
    }
    result = mod.classify(tmp_path, "deadbeef", row, 40)
    assert result["classification"] == "PRIOR_PROVEN"
    assert result["proven"] is True


def test_unbound_empty_candidate_is_not_proven(tmp_path: Path):
    row = {"strategy_id": "alpha_combo", "registry_patch_ready": False, "top_candidates": []}
    result = mod.classify(tmp_path, "deadbeef", row, 40)
    assert result["proven"] is False
    assert result["classification"] == "NO_CALLABLE_IMPLEMENTATION_PROVEN"
