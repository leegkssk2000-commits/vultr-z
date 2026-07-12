from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_exact25_shadow_binding_surface_audit.py"
    spec = importlib.util.spec_from_file_location("q4r3_shadow_binding_surface_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_close_writer_scoring_requires_realized_r_lineage() -> None:
    text = """
strategy_id = row['strategy_id']
entry_ts = row['entry_ts']
exit_ts = row['exit_ts']
initial_risk_usdt = row['initial_risk_usdt']
realized_pnl_usdt = row['realized_pnl_usdt']
realized_r = realized_pnl_usdt / initial_risk_usdt
append_jsonl(row)
"""
    scores = MODULE.score_categories(text)
    assert scores["close_r_writer"]["score"] >= 12
    assert MODULE.is_strong("close_r_writer", scores["close_r_writer"]["score"])


def test_manifest_validation_exact25_hashes_and_all_flags_false(tmp_path: Path) -> None:
    entries = []
    for strategy_id in MODULE.EXPECTED_25:
        path = tmp_path / "backend" / "strategies" / f"{strategy_id}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def strategy(df, state=None, risk_action='hold'):\n    return {'action':'hold'}\n", encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append({
            "strategy_id": strategy_id,
            "owner_path": f"backend/strategies/{strategy_id}.py",
            "owner_sha256": digest,
            "contract_pass": True,
            "enabled_for_shadow": False,
            "enabled_for_paper": False,
            "enabled_for_live": False,
        })
    manifest = tmp_path / "backend" / "config" / "q4r3_canonical_strategy_owner_manifest_v1.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "runtime_binding_status": "NOT_BOUND_STAGED_ACTIVE",
        "strategies": entries,
    }), encoding="utf-8")
    result = MODULE.validate_manifest(tmp_path, manifest)
    assert result["exact_25"] is True
    assert result["unique_25"] is True
    assert result["all_hashes_match"] is True
    assert result["all_contract_pass"] is True
    assert result["all_shadow_flags_false"] is True
    assert result["all_paper_flags_false"] is True
    assert result["all_live_flags_false"] is True


def strong_surface() -> dict:
    return {
        "market_data": [{"strong": True}],
        "strategy_runner": [{"strong": True}],
        "open_writer": [{"strong": True}],
        "close_r_writer": [{"strong": True}],
        "epoch_or_ledger": [{"strong": True}],
    }


def good_manifest() -> dict:
    return {
        "valid_json": True,
        "exact_25": True,
        "unique_25": True,
        "all_hashes_match": True,
        "all_contract_pass": True,
        "all_shadow_flags_false": True,
        "all_paper_flags_false": True,
        "all_live_flags_false": True,
    }


def test_decision_ready_only_with_active_watcher_and_all_surfaces() -> None:
    units = [{"unit": "q4r3-forward-r-watch.service", "is_forward_r_watcher": True, "active_state": "active"}]
    decision = MODULE.decide(good_manifest(), strong_surface(), units)
    assert decision["verdict"] == "EXACT25_SHADOW_BINDING_SURFACE_READY"
    assert decision["gaps"] == []


def test_decision_holds_when_r_writer_is_missing() -> None:
    surfaces = strong_surface()
    surfaces["close_r_writer"] = []
    units = [{"unit": "q4r3-forward-r-watch.service", "is_forward_r_watcher": True, "active_state": "active"}]
    decision = MODULE.decide(good_manifest(), surfaces, units)
    assert decision["verdict"] == "EXACT25_READY_WRITER_LINEAGE_GAPS_REMAIN"
    assert "realized_r_close_writer_unresolved" in decision["gaps"]


def test_required_measurement_fields_include_owner_epoch_and_r() -> None:
    required = set(MODULE.REQUIRED_EDGE_FIELDS)
    assert {"strategy_id", "owner_sha256", "epoch_id", "initial_risk_usdt", "realized_R"}.issubset(required)
