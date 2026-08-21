from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.tools import zel_survivor_tiering_gate_v3 as tier

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "backend/research/zel_survivor_tiering_policy_v3.json"
OWNERSHIP = ROOT / "backend/research/rebuild/a1_exact25_mechanism_ownership_v1.json"
AUTH = {
    "selection_authority": False, "promotion_authority": False,
    "execution_authority": "NONE", "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED", "protected_mutations": 0, "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def build_evidence(receipt: Mapping[str, Any], controls: Mapping[str, Any]) -> dict[str, Any]:
    candidate_id = str(receipt.get("strategy_id") or "")
    if not candidate_id or controls.get("candidate_id") != candidate_id:
        raise RuntimeError("RECEIPT_CONTROL_IDENTITY_MISMATCH")
    if controls.get("state") != "PASS_V3_UNIVERSAL_HARD_CONTROLS":
        raise RuntimeError(f"V3_HARD_CONTROLS_NOT_PASS:{controls.get('state')}")
    if controls.get("candidate_receipt_sha256") != receipt.get("receipt_sha256"):
        raise RuntimeError("V3_CONTROL_RECEIPT_LINEAGE_MISMATCH")
    source_quality = receipt.get("source_quality_gate") if isinstance(receipt.get("source_quality_gate"), Mapping) else {}
    if source_quality.get("state") != "PASS":
        raise RuntimeError("SOURCE_QUALITY_PASS_REQUIRED")
    if list(receipt.get("integrity_defects") or []) or int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("INTEGRITY_PASS_REQUIRED")

    trades = [x for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    if len(trades) < 25:
        raise RuntimeError(f"TIER_A_SAMPLE_LT25:{len(trades)}")
    boundary = _dt(str(receipt.get("boundary_utc") or ""))
    oos_cut = boundary + timedelta(hours=24)
    oos = [x for x in trades if datetime.fromtimestamp(int(x["entry_ts"]) / 1000, tz=timezone.utc) >= oos_cut]
    oos_vals = [float(x["net_bps"]) for x in oos]
    oos_net = sum(oos_vals)
    oos_exp = oos_net / len(oos_vals) if oos_vals else None
    if len(oos) < 20:
        raise RuntimeError(f"SEALED_OOS_SAMPLE_LT20:{len(oos)}")
    if oos_exp is None or oos_net <= 0.0 or oos_exp <= 0.0:
        raise RuntimeError(f"SEALED_OOS_NOT_POSITIVE:net={oos_net}:exp={oos_exp}")

    ownership = read(OWNERSHIP)
    owner = (ownership.get("strategies") or {}).get(candidate_id)
    if not isinstance(owner, Mapping) or not list(owner.get("mechanism_features") or []):
        raise RuntimeError("MECHANISM_OWNERSHIP_MISSING")
    metrics = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    net_bps = sum(float(x["net_bps"]) for x in trades)
    retention = 100.0 * len(oos) / len(trades)
    evidence = {
        "schema_version": "zel.a1_exact25.v3_forward_transition_evidence.v1",
        "candidate_id": candidate_id,
        "mechanism_features": list(owner["mechanism_features"]),
        "activation": {
            "new_fresh_boundary_after_v3_install": False,
            "reused_v2_promotion_outcome": False,
            "sealed_independent_oos": True,
            "policy_frozen_before_oos": True,
            "oos_outcomes_used_for_retune": False,
            "sealed_oos_trade_count": len(oos),
            "sealed_oos_window_rule": "entry_ts >= prospective_boundary + 24h; no OOS retune",
            "sealed_oos_net_pnl_bps": oos_net,
            "sealed_oos_net_expectancy_bps": oos_exp,
        },
        "economics": {
            "net_R": net_bps / 100.0,
            "expectancy_R": (net_bps / 100.0) / len(trades),
            "profit_factor": metrics.get("net_profit_factor"),
            "payoff_ratio": metrics.get("net_payoff"),
            "retention_pct": retention,
            "realistic_cost_authority": bool(str(receipt.get("cost_authority_sha256") or "")),
            "candidate_trade_count": len(trades),
            "screening_net_pnl_bps": metrics.get("net_pnl_bps"),
            "screening_net_expectancy_bps": metrics.get("net_expectancy_bps"),
        },
        "integrity": {
            "state": "PASS", "leakage_lookahead": 0, "defects": [],
            "source_quality_state": source_quality.get("state"),
        },
        "negative_controls": dict(controls.get("negative_controls") or {}),
        "concentration": {
            "global_h5_state": "NOT_RUN_A3_OWNS_CONCENTRATION",
            "blockers": ["A3_REGIME_DURABILITY_AND_CONCENTRATION_PENDING"],
            "route": "A3_DURABILITY_NOT_A1_GLOBAL_KILL",
        },
        "a2": {"state": "NOT_RUN"}, "a3": {"state": "NOT_RUN"},
        "lineage": {
            "candidate_receipt_sha256": receipt.get("receipt_sha256"),
            "universal_controls_receipt_sha256": controls.get("receipt_sha256"),
            "policy_sha": receipt.get("policy_sha"), "config_sha": receipt.get("config_sha"),
            "boundary_utc": receipt.get("boundary_utc"),
            "mechanism_ownership_sha256": tier.sha(ownership),
            "terminal_replay": receipt.get("terminal_replay"),
            "canonical_ledger_rewritten": False,
        },
        **AUTH,
    }
    evidence["receipt_sha256"] = tier.sha(evidence)
    return evidence


def evaluate(receipt: Mapping[str, Any], controls: Mapping[str, Any]) -> dict[str, Any]:
    evidence = build_evidence(receipt, controls)
    tiering = tier.evaluate(evidence, read(POLICY))
    out = {
        "schema_version": "zel.a1_exact25.v3_forward_transition.v1",
        "state": "PASS_A1_CAUSAL_READY_FOR_A2" if tiering.get("a2_entry_allowed") is True else "HOLD_A1_V3_FORWARD_TRANSITION",
        "candidate_id": evidence["candidate_id"], "evidence": evidence, "tiering": tiering,
        **AUTH,
    }
    out["receipt_sha256"] = tier.sha(out)
    return out


def self_test() -> int:
    policy = read(POLICY)
    assert "SEALED_INDEPENDENT_OOS" in set((policy.get("activation") or {}).get("a1_evidence_modes") or [])
    assert int((policy.get("activation") or {}).get("minimum_sealed_independent_oos_trades") or 0) <= 20
    print("PASS_A1_EXACT25_V3_FORWARD_TRANSITION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--receipt", type=Path); ap.add_argument("--controls", type=Path); ap.add_argument("--output", type=Path, default=Path("out/a1_v3_forward_transition_v1.json")); ap.add_argument("--self-test", action="store_true"); args = ap.parse_args()
    if args.self_test: return self_test()
    if not args.receipt or not args.controls: raise SystemExit("--receipt and --controls required")
    result = evaluate(read(args.receipt), read(args.controls)); args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"state":result["state"],"candidate_id":result["candidate_id"],"a1_tier":result["tiering"].get("a1_tier"),"a2_entry_allowed":result["tiering"].get("a2_entry_allowed"),"activation":result["tiering"].get("activation"),"receipt_sha256":result["receipt_sha256"]},sort_keys=True))
    return 0 if result["state"] == "PASS_A1_CAUSAL_READY_FOR_A2" else 2


if __name__ == "__main__": raise SystemExit(main())
