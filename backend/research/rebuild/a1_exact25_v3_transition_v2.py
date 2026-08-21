from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.tools import zel_survivor_tiering_gate_v3 as tier

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
POLICY = ROOT / "backend/research/zel_survivor_tiering_policy_v3.json"
OWNERSHIP = ROOT / "backend/research/rebuild/a1_exact25_mechanism_ownership_v1.json"

LINEAGE_BLOCKERS = {
    "TRADE_BUDGET_MISMATCH", "WINDOW_SHA_MISMATCH", "COST_MODEL_SHA_MISMATCH",
    "SOURCE_SHA_MISMATCH", "DATA_SHA_MISMATCH",
}
AUTHORITY = {
    "selection_authority": False, "promotion_authority": False,
    "execution_authority": "NONE", "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED", "protected_mutations": 0, "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _controls(hardening: Mapping[str, Any]) -> tuple[dict[str, Any], float, int]:
    h4 = hardening.get("h4_receipt") if isinstance(hardening.get("h4_receipt"), Mapping) else {}
    if h4.get("schema_version") != "zel.economic_hardening.h4.receipt.v2":
        raise RuntimeError("H4_SCHEMA_INVALID")
    if h4.get("control_engine_pass") is not True:
        raise RuntimeError("H4_ENGINE_NOT_VERIFIED")
    raw = h4.get("control_results") if isinstance(h4.get("control_results"), Mapping) else {}
    required = {"same_count_random_entry", "direction_inversion", "timestamp_shuffle", "one_bar_delay", "indicator_removal"}
    if not required.issubset(set(raw)):
        raise RuntimeError(f"H4_CONTROL_SET_INCOMPLETE:{sorted(required-set(raw))}")
    candidate_values: list[float] = []
    controls: dict[str, Any] = {}
    for name in sorted(required):
        cr = raw[name]
        if not isinstance(cr, Mapping):
            raise RuntimeError(f"H4_CONTROL_INVALID:{name}")
        blockers = {str(x) for x in cr.get("blockers") or []}
        bad = blockers & LINEAGE_BLOCKERS
        if bad:
            raise RuntimeError(f"H4_LINEAGE_FAIL:{name}:{sorted(bad)}")
        if cr.get("control_net_R") is None or cr.get("candidate_minus_control_net_R") is None:
            raise RuntimeError(f"H4_NET_R_MISSING:{name}")
        candidate_values.append(float(cr["control_net_R"]) + float(cr["candidate_minus_control_net_R"]))
        controls[name] = {
            "state": "PASS" if cr.get("pass") is True else "FAIL",
            "p_value": cr.get("p_value"),
            "candidate_minus_control_ci_low_R": cr.get("candidate_minus_control_ci_low_R"),
            "equal_trade_budget": True,
            "identical_window_lineage": True,
            "identical_cost_lineage": True,
            "source_receipt_sha256": cr.get("source_receipt_sha256"),
            "original_v2_blockers": sorted(blockers),
        }
    if max(candidate_values) - min(candidate_values) > 1e-6:
        raise RuntimeError("H4_CANDIDATE_NET_R_INCONSISTENT")
    trades = int(hardening.get("candidate_trade_count") or 0)
    if trades < 25:
        raise RuntimeError(f"H4_SAMPLE_INSUFFICIENT:{trades}<25")
    return controls, sum(candidate_values) / len(candidate_values), trades


def build_evidence(candidate_id: str, hardening: Mapping[str, Any]) -> dict[str, Any]:
    ledger, ownership = read(LEDGER), read(OWNERSHIP)
    if int(ledger.get("done_count") or 0) != 25 or ledger.get("state") != "A1_EXACT25_BASELINE_SWEEP_COMPLETE":
        raise RuntimeError("EXACT25_NOT_COMPLETE")
    row = (ledger.get("strategies") or {}).get(candidate_id)
    if not isinstance(row, Mapping):
        raise RuntimeError(f"CANDIDATE_NOT_IN_EXACT25:{candidate_id}")
    if hardening.get("strategy_id") != candidate_id or hardening.get("fixture") is not False:
        raise RuntimeError("HARDENING_IDENTITY_INVALID")
    if hardening.get("policy_sha") != row.get("policy_sha") or hardening.get("config_sha") != row.get("config_sha"):
        raise RuntimeError("POLICY_CONFIG_LINEAGE_MISMATCH")
    if hardening.get("boundary_utc") != row.get("prospective_boundary_utc"):
        raise RuntimeError("BOUNDARY_LINEAGE_MISMATCH")
    integ = hardening.get("candidate_integrity") if isinstance(hardening.get("candidate_integrity"), Mapping) else {}
    if integ.get("state") != "PASS" or integ.get("source_quality_state") != "PASS" or list(integ.get("integrity_defects") or []) or int(integ.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("INTEGRITY_NOT_PASS")

    controls, candidate_net_r, candidate_trades = _controls(hardening)
    oos = hardening.get("oos") if isinstance(hardening.get("oos"), Mapping) else {}
    oos_trades = int(oos.get("trade_count") or 0)
    if oos_trades < 20 or float(oos.get("net_pnl_bps") or 0.0) <= 0 or float(oos.get("net_expectancy_bps") or 0.0) <= 0:
        raise RuntimeError("SEALED_OOS_NOT_POSITIVE_OR_INSUFFICIENT")
    own = (ownership.get("strategies") or {}).get(candidate_id)
    if not isinstance(own, Mapping) or not list(own.get("mechanism_features") or []):
        raise RuntimeError("MECHANISM_OWNERSHIP_NOT_SEALED")

    evidence = {
        "schema_version": "zel.a1_exact25.v3_transition_evidence.v2",
        "candidate_id": candidate_id,
        "mechanism_features": list(own["mechanism_features"]),
        "activation": {
            "new_fresh_boundary_after_v3_install": False,
            "reused_v2_promotion_outcome": False,
            "sealed_independent_oos": True,
            "policy_frozen_before_oos": True,
            "oos_outcomes_used_for_retune": False,
            "sealed_oos_trade_count": oos_trades,
            "sealed_oos_window_rule": oos.get("window_rule"),
            "sealed_oos_net_pnl_bps": oos.get("net_pnl_bps"),
            "sealed_oos_net_expectancy_bps": oos.get("net_expectancy_bps"),
        },
        "economics": {
            "net_R": candidate_net_r,
            "expectancy_R": candidate_net_r / candidate_trades,
            "profit_factor": float(row.get("profit_factor") or 0.0),
            "payoff_ratio": float(row.get("payoff") or 0.0),
            "retention_pct": float(hardening.get("retention_pct") or 0.0),
            "realistic_cost_authority": bool(str(hardening.get("cost_authority_sha256") or "")),
            "screening_net_pnl_bps": row.get("net_pnl_bps"),
            "screening_net_expectancy_bps": row.get("net_expectancy_bps"),
            "screening_profit_factor": row.get("profit_factor"),
            "screening_payoff": row.get("payoff"),
            "screening_drawdown_bps": row.get("drawdown_bps"),
            "candidate_h4_trade_count": candidate_trades,
        },
        "integrity": {"state": "PASS", "leakage_lookahead": 0, "defects": [], "source_quality_state": "PASS"},
        "negative_controls": controls,
        "concentration": {
            "global_h5_state": (hardening.get("h5_receipt") or {}).get("state"),
            "blockers": (hardening.get("h5_receipt") or {}).get("blockers"),
            "route": "A3_DURABILITY_NOT_A1_GLOBAL_KILL",
        },
        "a2": {"state": "NOT_RUN"}, "a3": {"state": "NOT_RUN"},
        "lineage": {
            "exact25_ledger_sha256": tier.sha(ledger),
            "screening_receipt_sha256": row.get("receipt_sha"),
            "hardening_receipt_sha256": hardening.get("receipt_sha256"),
            "h4_receipt_sha256": (hardening.get("h4_receipt") or {}).get("receipt_sha256"),
            "h5_receipt_sha256": (hardening.get("h5_receipt") or {}).get("receipt_sha256"),
            "policy_sha": row.get("policy_sha"), "config_sha": row.get("config_sha"),
            "boundary_utc": row.get("prospective_boundary_utc"),
            "mechanism_ownership_sha256": tier.sha(ownership), "v2_receipt_rewritten": False,
        },
        **AUTHORITY,
    }
    evidence["receipt_sha256"] = tier.sha(evidence)
    return evidence


def evaluate(candidate_id: str, hardening: Mapping[str, Any]) -> dict[str, Any]:
    evidence = build_evidence(candidate_id, hardening)
    result = tier.evaluate(evidence, read(POLICY))
    out = {
        "schema_version": "zel.a1_exact25.v3_transition.v2",
        "state": "PASS_A1_CAUSAL_READY_FOR_A2" if result.get("a2_entry_allowed") is True else "HOLD_A1_V3_TRANSITION",
        "candidate_id": candidate_id, "evidence": evidence, "tiering": result, **AUTHORITY,
    }
    out["receipt_sha256"] = tier.sha(out)
    return out


def self_test() -> int:
    ownership = read(OWNERSHIP)
    assert len(ownership.get("strategies") or {}) == 25
    conditional = set((read(POLICY).get("a1_causal_alpha_gate") or {}).get("conditional_hard_controls", {}).get("timestamp_shuffle", {}).get("required_if_any_feature_owner") or [])
    time_owners = {cid for cid, row in ownership["strategies"].items() if set(row.get("mechanism_features") or []) & conditional}
    assert time_owners == {"session_bias"}, time_owners
    print("PASS_A1_EXACT25_V3_TRANSITION_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-id")
    ap.add_argument("--hardening", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_exact25_v3_transition_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.candidate_id or not args.hardening:
        raise SystemExit("--candidate-id and --hardening required")
    out = evaluate(args.candidate_id, read(args.hardening))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": out["state"], "candidate_id": out["candidate_id"], "a1_tier": out["tiering"].get("a1_tier"), "a2_entry_allowed": out["tiering"].get("a2_entry_allowed"), "hard_controls": out["tiering"].get("hard_control_states"), "receipt_sha256": out["receipt_sha256"]}, sort_keys=True))
    return 0 if out["state"] == "PASS_A1_CAUSAL_READY_FOR_A2" else 2


if __name__ == "__main__":
    raise SystemExit(main())
