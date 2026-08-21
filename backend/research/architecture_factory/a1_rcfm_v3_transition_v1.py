from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.tools import zel_survivor_tiering_gate_v3 as tier

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "backend/research/zel_survivor_tiering_policy_v3.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
RCFM_POLICY = ROOT / "backend/research/architecture_factory/a1_regime_conditioned_flow_momentum_policy_v1.json"
CONTRACT = ROOT / "backend/research/architecture_factory/a1_rcfm_causal_control_contract_v1.json"
CANDIDATE_ID = "NEW_RCFM_001"
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
    rcfm_policy, contract, cost = read(RCFM_POLICY), read(CONTRACT), read(COST)
    if receipt.get("candidate_id") != CANDIDATE_ID or controls.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("RCFM_IDENTITY_MISMATCH")
    if controls.get("candidate_receipt_sha256") != receipt.get("receipt_sha256"):
        raise RuntimeError("RCFM_CAUSAL_RECEIPT_LINEAGE_MISMATCH")
    if controls.get("state") != "PASS_RCFM_V3_CAUSAL_CONTROLS":
        raise RuntimeError(f"RCFM_CAUSAL_CONTROLS_NOT_PASS:{controls.get('state')}")
    if (controls.get("micro_sign_permutation") or {}).get("state") != "PASS":
        raise RuntimeError("RCFM_MICRO_CAUSAL_CONTROL_NOT_PASS")
    universal = controls.get("universal_controls") or {}
    if universal.get("state") != "PASS_V3_UNIVERSAL_HARD_CONTROLS":
        raise RuntimeError("RCFM_UNIVERSAL_CONTROLS_NOT_PASS")
    if receipt.get("boundary_utc") != rcfm_policy.get("fresh_prospective_boundary_utc") or receipt.get("boundary_utc") != contract.get("prospective_boundary_utc"):
        raise RuntimeError("RCFM_BOUNDARY_LINEAGE_MISMATCH")
    if list(receipt.get("integrity_defects") or []) or int(receipt.get("leakage_lookahead") or 0) != 0 or int(receipt.get("duplicate_count") or 0) != 0:
        raise RuntimeError("RCFM_INTEGRITY_NOT_PASS")
    if cost.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("RCFM_COST_AUTHORITY_INVALID")
    trades = [x for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    if len(trades) < int((contract.get("cohort") or {}).get("trade_count") or 25):
        raise RuntimeError(f"RCFM_SAMPLE_LT25:{len(trades)}")
    metrics = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    required = ("net_pnl_bps", "net_expectancy_bps", "profit_factor", "payoff")
    if any(metrics.get(k) is None for k in required):
        raise RuntimeError("RCFM_ECONOMICS_INCOMPLETE")
    negative_controls = dict(universal.get("negative_controls") or {})
    evidence = {
        "schema_version": "zel.a1.rcfm.v3_evidence.v1",
        "candidate_id": CANDIDATE_ID,
        "mechanism_features": ["price", "volume", "multi_hour_momentum", "trade_flow", "l2_order_book", "source_freshness"],
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
            "profit_factor": float(metrics["profit_factor"]),
            "payoff_ratio": float(metrics["payoff"]),
            "retention_pct": 100.0,
            "realistic_cost_authority": True,
            "candidate_trade_count": len(trades),
        },
        "integrity": {
            "state": "PASS",
            "leakage_lookahead": 0,
            "defects": [],
            "source_quality_state": "PASS",
        },
        "negative_controls": negative_controls,
        "mechanism_specific_hard_controls": {
            "micro_sign_permutation": dict(controls.get("micro_sign_permutation") or {}),
            "wrapper_gate_state": "PASS",
        },
        "concentration": {
            "global_h5_state": "NOT_RUN_A3_OWNS_CONCENTRATION",
            "blockers": ["A3_REGIME_DURABILITY_AND_CONCENTRATION_PENDING"],
            "route": "A3_DURABILITY_NOT_A1_GLOBAL_KILL",
        },
        "a2": {"state": "NOT_RUN"},
        "a3": {"state": "NOT_RUN"},
        "lineage": {
            "candidate_receipt_sha256": receipt.get("receipt_sha256"),
            "causal_controls_receipt_sha256": controls.get("receipt_sha256"),
            "universal_controls_receipt_sha256": universal.get("receipt_sha256"),
            "policy_sha": receipt.get("policy_sha"),
            "prereg_sha": receipt.get("prereg_sha"),
            "boundary_utc": receipt.get("boundary_utc"),
            "causal_contract_sha256": controls.get("contract_sha256"),
            "same_identity_causal_retest_forbidden": True,
        },
        **AUTH,
    }
    evidence["receipt_sha256"] = tier.sha(evidence)
    return evidence


def evaluate(receipt: Mapping[str, Any], controls: Mapping[str, Any]) -> dict[str, Any]:
    evidence = build_evidence(receipt, controls)
    tiering = tier.evaluate(evidence, read(POLICY))
    result = {
        "schema_version": "zel.a1.rcfm.v3_transition.v1",
        "state": "PASS_A1_CAUSAL_READY_FOR_A2" if tiering.get("a2_entry_allowed") is True else "HOLD_A1_RCFM_V3_TRANSITION",
        "candidate_id": CANDIDATE_ID,
        "evidence": evidence,
        "tiering": tiering,
        **AUTH,
    }
    result["receipt_sha256"] = tier.sha(result)
    return result


def self_test() -> int:
    policy, contract = read(POLICY), read(CONTRACT)
    assert contract["candidate_id"] == CANDIDATE_ID
    assert contract["cohort"]["trade_count"] == 25
    assert set(policy["a1_causal_alpha_gate"]["hard_negative_controls"]) == {"same_count_random_entry", "direction_inversion"}
    print("PASS_A1_RCFM_V3_TRANSITION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path)
    ap.add_argument("--controls", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_rcfm_v3_transition_v1.json"))
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
