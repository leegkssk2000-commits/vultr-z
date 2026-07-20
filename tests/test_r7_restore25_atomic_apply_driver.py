from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "tools/r7_restore25_atomic_apply_driver.py"
spec = importlib.util.spec_from_file_location("restore25_atomic", MODULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_artifact_direct_entry_is_reclassified_for_restore25():
    row = {
        "strategy_id": "ema_ribbon_scalp",
        "binding_mode": "DIRECT_PROVEN",
        "canonical_engine": {
            "implementation_path": (
                "runtime_results/q4r3/exact25_candidate_package/source/"
                "backend/strategies/ema_ribbon_scalp.py"
            ),
            "callable": "evaluate",
            "source_blob_sha": "abc123",
        },
    }
    entry, error = mod.synthetic_recovery_entry(row)
    assert error is None
    assert entry is not None
    assert entry["strategy_id"] == "ema_ribbon_scalp"
    assert entry["classification"] == "ARTIFACT_DIRECT_RECLASSIFIED_FOR_RESTORE25"
    assert entry["artifact_matches"][0]["callable"] == "evaluate"


def test_true_source_is_not_reclassified_as_missing_artifact():
    row = {
        "strategy_id": "ema_ribbon_scalp",
        "binding_mode": "DIRECT_PROVEN",
        "canonical_engine": {
            "implementation_path": "backend/strategies/ema_ribbon_scalp.py",
            "callable": "evaluate",
        },
    }
    entry, error = mod.synthetic_recovery_entry(row)
    assert entry is None
    assert error == (
        "DIRECT_ENTRY_ALREADY_TRUE_SOURCE:ema_ribbon_scalp:"
        "backend/strategies/ema_ribbon_scalp.py"
    )


def test_missing_direct_metadata_fails_closed():
    entry, error = mod.synthetic_recovery_entry({"strategy_id": "vol_spike_fade"})
    assert entry is None
    assert error == "DIRECT_ENGINE_METADATA_INVALID:vol_spike_fade"
