from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.tools import zel_survivor_tiering_gate_v3 as tier

ROOT = Path(__file__).resolve().parents[3]
PREREG = ROOT / "backend/research/architecture_factory/a1_trend_rider_transition_repair_prereg_v1.json"
POLICY = ROOT / "backend/research/zel_survivor_tiering_policy_v3.json"
CANDIDATE_ID = "trend_rider_confirm_transition_v1"
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def build_evidence(receipt: Mapping[str, Any], controls: Mapping[str, Any]) -> dict[str, Any]:
    prereg = read(PREREG)
    if receipt.get("strategy_id") != CANDIDATE_ID or prereg.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("REPAIR_IDENTITY_MISMATCH")
    if receipt.get("prereg_blob_sha") is None or receipt.get("boundary_utc") != prereg.get("prospective_boundary_utc"):
        raise RuntimeError("REPAIR_PREREG_LINEAGE_MISMATCH")
    if controls.get("candidate_id") != CANDIDATE_ID or controls.get("candidate_receipt_sha256") != receipt.get("receipt_sha256"):
        raise RuntimeError("CONTROL_RECEIPT_LINEAGE_MISMATCH")
    if controls.get("state") != "PASS_V3_UNIVERSAL_HARD_CONTROLS":
        raise RuntimeError(f"V3_HARD_CONTROLS_NOT_PASS:{controls.get('state')}")
    if (receipt.get("source_quality_gate") or {}).get("state") != "PASS":
        raise RuntimeError(f"SOURCE_QUALITY_NOT_PASS:{(receipt.get('source_quality_gate') or {}).get('state')}")
    defects = list(receipt.get("integrity_defects") or [])
    if defects or int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("REPAIR_INTEGRITY_NOT_PASS")
    trades = [x for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    if len(trades) < 25:
        raise RuntimeError(f"REPAIR_SAMPLE_LT25:{len(trades)}")
    metrics = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    required = ("net_pnl_bps", "net_expectancy_bps", "net_profit_factor", "net_payoff")
    if any(metrics.get(k) is None for k in required):
        raise RuntimeError("REPAIR_ECONOMICS_INCOMPLETE")
    invariants = receipt.get("repair_invariants") if isinstance(receipt.get("repair_invariants"), Mapping) else {}
    if invariants.get("parent_thresholds_changed") is not False or invariants.get("parent_risk_geometry_changed") is not False or invariants.get("parent_timeout_changed") is not False:
        raise RuntimeError("REPAIR_NOT_SINGLE_AXIS")
    if invariants.get("historical_backfill") is not False or invariants.get("preboundary_outcomes_used") is not False:
        raise RuntimeError("REPAIR_PROSPECTIVE_INTEGRITY_FAIL")

    good_controls = dict(controls.get("negative_controls") or {})
    evidence = {
        "schema_version": "zel.a1.trend_rider_transition_repair.v3_evidence.v1",
        "candidate_id": CANDIDATE_ID,
        "mechanism_features": ["price", "supertrend", "ema", "atr", "candle_direction", "state_transition"],
        "activation": {
            "new_fresh_boundary_after_v3_install": True,
            "reused_v2_promotion_outcome": False,
            "sealed_independent_oos": False,
            "policy_frozen_before_oos": True,
            "oos_outcomes_used_for_retune": False,
            "sealed_oos_trade_count": 0,
        },
        "economics": {
            "net_R": float(metrics["net_pnl_bps"]) / 100.0,
            "expectancy_R": float(metrics["net_expectancy_bps"]) / 100.0,
            "profit_factor": float(metrics["net_profit_factor"]),
            "payoff_ratio": float(metrics["net_payoff"]),
            "retention_pct": 100.0,
            "realistic_cost_authority": bool(str(receipt.get("cost_authority_sha256") or "")),
            "candidate_trade_count": len(trades),
        },
        "integrity": {
            "state": "PASS",
            "leakage_lookahead": 0,
            "defects": [],
            "source_quality_state": "PASS",
        },
        "negative_controls": good_controls,
        "concentration": {
            "global_h5_state": "NOT_RUN_A3_OWNS_CONCENTRATION",
            "blockers": ["A3_REGIME_DURABILITY_AND_CONCENTRATION_PENDING"],
            "route": "A3_DURABILITY_NOT_A1_GLOBAL_KILL",
        },
        "a2": {"state": "NOT_RUN"},
        "a3": {"state": "NOT_RUN"},
        "lineage": {
            "candidate_receipt_sha256": receipt.get("receipt_sha256"),
            "controls_receipt_sha256": controls.get("receipt_sha256"),
            "prereg_blob_sha": receipt.get("prereg_blob_sha"),
            "policy_sha": receipt.get("policy_sha"),
            "config_sha": receipt.get("config_sha"),
            "boundary_utc": receipt.get("boundary_utc"),
            "parent_registry_receipt_sha256": receipt.get("parent_registry_receipt_sha256"),
            "same_parent_identity_retest_forbidden": True,
        },
        **AUTH,
    }
    evidence["receipt_sha256"] = tier.sha(evidence)
    return evidence


def evaluate(receipt: Mapping[str, Any], controls: Mapping[str, Any]) -> dict[str, Any]:
    evidence = build_evidence(receipt, controls)
    tiering = tier.evaluate(evidence, read(POLICY))
    result = {
        "schema_version": "zel.a1.trend_rider_transition_repair.v3_transition.v1",
        "state": "PASS_A1_CAUSAL_READY_FOR_A2" if tiering.get("a2_entry_allowed") is True else "HOLD_A1_REPAIR_V3_TRANSITION",
        "candidate_id": CANDIDATE_ID,
        "evidence": evidence,
        "tiering": tiering,
        **AUTH,
    }
    result["receipt_sha256"] = tier.sha(result)
    return result


def self_test() -> int:
    prereg = read(PREREG)
    policy = read(POLICY)
    assert prereg["candidate_id"] == CANDIDATE_ID
    assert prereg["prospective_boundary_utc"] == "2026-08-21T17:00:00Z"
    assert "NEW_FRESH_BOUNDARY" in set((policy.get("activation") or {}).get("a1_evidence_modes") or [])
    print("PASS_A1_TREND_RIDER_TRANSITION_REPAIR_V3_TRANSITION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path)
    ap.add_argument("--controls", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_trend_rider_transition_repair_v3_transition_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.receipt or not args.controls:
        raise SystemExit("--receipt and --controls required")
    result = evaluate(read(args.receipt), read(args.controls))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "candidate_id": result["candidate_id"],
        "a1_tier": result["tiering"].get("a1_tier"),
        "a2_entry_allowed": result["tiering"].get("a2_entry_allowed"),
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0 if result["state"] == "PASS_A1_CAUSAL_READY_FOR_A2" else 2


if __name__ == "__main__":
    raise SystemExit(main())
