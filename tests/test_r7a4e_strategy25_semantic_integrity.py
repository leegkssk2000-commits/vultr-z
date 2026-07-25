from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    path = ROOT / "tools/r7a4e_strategy25_semantic_integrity.py"
    spec = importlib.util.spec_from_file_location("r7a4e_strategy25_semantic_integrity", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_contract_registry_and_all_25_smoke() -> None:
    result = load_verifier().verify(ROOT, write_registry=False)
    assert result["status"] == "PASS_R7A4E_STRATEGY25_SEMANTIC_INTEGRITY"
    assert result["strategy_count"] == 25
    assert result["patched_strategy_count"] == 10
    assert result["identity_blocker_count"] == 5
    assert result["active_entry_count"] == 0


def test_contract_exact_ids_and_fail_closed_authority() -> None:
    contract = json.loads((ROOT / "backend/strategy25/strategy25_semantic_contract_v1.json").read_text())
    registry = json.loads((ROOT / "backend/strategy25/canonical_strategy_registry_v1.json").read_text())
    contract_ids = [row["strategy_id"] for row in contract["strategies"]]
    registry_ids = [row["strategy_id"] for row in registry["entries"]]
    assert len(contract_ids) == len(set(contract_ids)) == 25
    assert set(contract_ids) == set(registry_ids)
    assert registry["active_entry_count"] == 0
    assert all(row["active_allowed"] is False for row in registry["entries"])
    assert all(row["fail_closed"] is True for row in registry["entries"])
    assert contract["execution_authority_changed"] is False


def test_three_candle_fvg_is_not_adjacent_gap() -> None:
    from backend.strategies.fvg_revert import FvgRevertConfig, _latest_three_candle_gap

    frame = pd.DataFrame(
        [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
            {"open": 100.5, "high": 104.0, "low": 100.2, "close": 103.8, "volume": 1500.0},
            {"open": 103.8, "high": 105.0, "low": 102.0, "close": 104.5, "volume": 1200.0},
            {"open": 104.5, "high": 105.0, "low": 103.0, "close": 103.5, "volume": 1000.0},
        ]
    )
    gap = _latest_three_candle_gap(frame, FvgRevertConfig(min_gap_atr=0.2, min_gap_pct=0.0), 2.0, 103.5)
    assert gap is not None
    assert gap["gap_direction"] == "up"
    assert gap["gap_low"] == 101.0
    assert gap["gap_high"] == 102.0


def test_session_overlap_precedes_single_session_classification() -> None:
    from backend.strategies.session_bias import SessionBiasConfig, _session_name

    cfg = SessionBiasConfig(default_tz="UTC")
    assert _session_name(datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc), "UTC", cfg) == "london_newyork_overlap"
    assert _session_name(datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc), "UTC", cfg) == "london"
    assert _session_name(datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc), "UTC", cfg) == "newyork"


def test_patched_temporal_markers_are_locked() -> None:
    verifier = load_verifier()
    for strategy_id, markers in verifier.PATCH_MARKERS.items():
        path = ROOT / f"backend/strategies/{strategy_id}.py"
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker in source, (strategy_id, marker)


def test_long_only_adapter_blocker_remains_explicit() -> None:
    source = (ROOT / "backend/strategies/semantic_common.py").read_text(encoding="utf-8")
    assert "short_signal_generated_but_core_is_long_only" in source
    assert "short_pending_core_upgrade" in source
