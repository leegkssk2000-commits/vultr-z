from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_forward_r_writer_surface_audit.py"
    spec = importlib.util.spec_from_file_location("test_q4r3_forward_r_writer_surface_audit_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_closed_evidence_rejects_explicit_open() -> None:
    row = {"status": "open", "closed_at": "2026-07-12T00:00:00Z"}
    assert MODULE.closed_evidence(row) is False


def test_closed_evidence_accepts_boolean_or_exit_timestamp() -> None:
    assert MODULE.closed_evidence({"status_closed": True}) is True
    assert MODULE.closed_evidence({"exit_ts": 1_700_000_000_000}) is True


def test_open_evidence_requires_entry_contract_without_close() -> None:
    assert MODULE.open_evidence({"status": "open", "entry_price": 100.0}) is True
    assert MODULE.open_evidence({"entry_ts": 1, "entry": 100.0}) is True
    assert MODULE.open_evidence({"entry_ts": 1}) is False
    assert MODULE.open_evidence({"status": "closed", "entry": 100.0}) is False


def test_linear_contract_values_are_explicit_only() -> None:
    assert MODULE.explicit_linear_contract({"contract_type": "linear_usdt"}) is True
    assert MODULE.explicit_linear_contract({"contract_type": "inverse"}) is False
    assert MODULE.explicit_linear_contract({}) is False


def test_code_candidate_requires_close_and_writer_terms() -> None:
    text = "closed_at = now; payload['realized_pnl_usdt']=pnl; atomic_json(path,payload); trade_id='x'"
    out = MODULE.score_code_candidate(Path("writer.py"), text)
    assert out is not None
    assert out["score"] >= 12
    assert out["contains_realized_usdt"] is True
    assert MODULE.score_code_candidate(Path("reader.py"), "closed_at = now") is None


def test_forward_contract_forbids_unsafe_backfill() -> None:
    contract = MODULE.build_contract()
    forbidden = set(contract["forbidden_inference"])
    assert "rr" in forbidden
    assert "leverage alone" in forbidden
    assert contract["scope"].startswith("future closed events only")


def test_freeze_manifest_blocks_execution_and_keeps_restart_gate() -> None:
    freeze = MODULE.build_freeze_manifest(
        {"verdict": "HISTORICAL_CLOSED_PNL_EXISTS_BUT_R_DENOMINATOR_ABSENT"},
        {"best_independent_candidate": "confirm_prior_best_PB8_R7"},
    )
    assert freeze["state"] == "FROZEN_OBSERVER_RESERVE"
    assert freeze["execution_enabled"] is False
    assert freeze["paper_enabled"] is False
    assert freeze["live_enabled"] is False
    assert freeze["best_preserved_candidate"] == "confirm_prior_best_PB8_R7"
    assert len(freeze["restart_conditions"]) >= 4


def runtime_inventory(**overrides):
    payload = {
        "stable_id_join_rate_pct": 0.0,
        "join_explicit_risk_ready_count": 0,
        "join_formula_ready_count": 0,
        "close_explicit_realized_r_count": 0,
        "close_usdt_plus_explicit_risk_count": 0,
    }
    payload.update(overrides)
    return payload


def code_surface(dominant: bool):
    return {
        "dominant_single_writer": dominant,
        "dominant_writer": {"path": "/home/z/z/backend/close_writer.py", "score": 20} if dominant else None,
    }


def test_decision_prefers_single_writer_patch_when_join_is_ready() -> None:
    decision = MODULE.decide(
        runtime_inventory(stable_id_join_rate_pct=90.0, join_explicit_risk_ready_count=5),
        code_surface(True),
    )
    assert decision["verdict"] == "COMMON_CLOSE_WRITER_PATCH_READY"


def test_decision_requires_entry_risk_capture_when_dominant_writer_has_no_denominator() -> None:
    decision = MODULE.decide(runtime_inventory(stable_id_join_rate_pct=90.0), code_surface(True))
    assert decision["verdict"] == "COMMON_WRITER_FOUND_ENTRY_RISK_CAPTURE_REQUIRED"


def test_decision_uses_sidecar_only_when_join_contract_is_ready_without_single_writer() -> None:
    decision = MODULE.decide(
        runtime_inventory(stable_id_join_rate_pct=85.0, join_formula_ready_count=3),
        code_surface(False),
    )
    assert decision["verdict"] == "SIDECAR_FORWARD_R_WRITER_READY"
