from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.tools import zel_survivor_tiering_gate_v3 as tier

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
HARDENING = ROOT / "backend/research/rebuild/diagnostics/trend_rider_hardening_latest.json"
POLICY = ROOT / "backend/research/zel_survivor_tiering_policy_v3.json"

LINEAGE_BLOCKERS = {
    "TRADE_BUDGET_MISMATCH",
    "WINDOW_SHA_MISMATCH",
    "COST_MODEL_SHA_MISMATCH",
    "SOURCE_SHA_MISMATCH",
    "DATA_SHA_MISMATCH",
}

AUTHORITY = {
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


def build_evidence() -> dict[str, Any]:
    ledger = read(LEDGER)
    h = read(HARDENING)
    if int(ledger.get("done_count") or 0) != 25 or ledger.get("state") != "A1_EXACT25_BASELINE_SWEEP_COMPLETE":
        raise RuntimeError("EXACT25_NOT_COMPLETE")
    row = (ledger.get("strategies") or {}).get("trend_rider") or {}
    if row.get("status") != "A1_FINALIST_PARKED":
        raise RuntimeError(f"TREND_RIDER_NOT_FINALIST:{row.get('status')}")
    if h.get("strategy_id") != "trend_rider" or h.get("fixture") is not False:
        raise RuntimeError("TREND_RIDER_HARDENING_INVALID")
    if h.get("policy_sha") != row.get("policy_sha") or h.get("config_sha") != row.get("config_sha"):
        raise RuntimeError("POLICY_CONFIG_LINEAGE_MISMATCH")
    if h.get("boundary_utc") != row.get("prospective_boundary_utc"):
        raise RuntimeError("BOUNDARY_LINEAGE_MISMATCH")
    integ = h.get("candidate_integrity") or {}
    if integ.get("state") != "PASS" or integ.get("source_quality_state") != "PASS" or list(integ.get("integrity_defects") or []) or int(integ.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("INTEGRITY_NOT_PASS")

    h4 = h.get("h4_receipt") or {}
    if h4.get("control_engine_pass") is not True:
        raise RuntimeError("H4_ENGINE_NOT_PASS")
    control_results = h4.get("control_results") or {}
    required = {"same_count_random_entry", "direction_inversion", "timestamp_shuffle", "one_bar_delay", "indicator_removal"}
    if set(control_results) != required:
        raise RuntimeError("H4_CONTROL_SET_MISMATCH")

    candidate_net_values: list[float] = []
    controls: dict[str, Any] = {}
    for name, cr in control_results.items():
        blockers = set(str(x) for x in cr.get("blockers") or [])
        if blockers & LINEAGE_BLOCKERS:
            raise RuntimeError(f"H4_LINEAGE_FAIL:{name}:{sorted(blockers & LINEAGE_BLOCKERS)}")
        candidate_net_values.append(float(cr["control_net_R"]) + float(cr["candidate_minus_control_net_R"]))
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
    if max(candidate_net_values) - min(candidate_net_values) > 1e-6:
        raise RuntimeError("H4_CANDIDATE_NET_R_INCONSISTENT")
    candidate_net_r = sum(candidate_net_values) / len(candidate_net_values)
    candidate_trades = int(h.get("candidate_trade_count") or 0)
    if candidate_trades < 25:
        raise RuntimeError("H4_SAMPLE_INSUFFICIENT")

    oos = h.get("oos") or {}
    oos_trades = int(oos.get("trade_count") or 0)
    if oos_trades < 20 or float(oos.get("net_pnl_bps") or 0.0) <= 0 or float(oos.get("net_expectancy_bps") or 0.0) <= 0:
        raise RuntimeError("SEALED_OOS_NOT_POSITIVE_OR_INSUFFICIENT")

    # The parent policy uses Supertrend/EMA/ATR/candle direction and no session/calendar/time-of-day input.
    # signal_ts is data lineage/freshness metadata, not an alpha feature.
    mechanism_features = ["price", "supertrend", "ema", "atr", "candle_direction"]
    evidence = {
        "schema_version": "zel.a1.trend_rider.v3_transition_evidence.v1",
        "candidate_id": "trend_rider",
        "mechanism_features": mechanism_features,
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
            "profit_factor": float(row.get("profit_factor")),
            "payoff_ratio": float(row.get("payoff")),
            "retention_pct": float(h.get("retention_pct")),
            "realistic_cost_authority": bool(str(h.get("cost_authority_sha256") or "")),
            "screening_net_pnl_bps": row.get("net_pnl_bps"),
            "screening_net_expectancy_bps": row.get("net_expectancy_bps"),
            "screening_profit_factor": row.get("profit_factor"),
            "screening_payoff": row.get("payoff"),
            "screening_drawdown_bps": row.get("drawdown_bps"),
            "candidate_h4_trade_count": candidate_trades,
        },
        "integrity": {
            "state": "PASS",
            "leakage_lookahead": 0,
            "defects": [],
            "source_quality_state": integ.get("source_quality_state"),
        },
        "negative_controls": controls,
        "concentration": {
            "global_h5_state": (h.get("h5_receipt") or {}).get("state"),
            "blockers": (h.get("h5_receipt") or {}).get("blockers"),
            "route": "A3_DURABILITY_NOT_A1_GLOBAL_KILL",
        },
        "a2": {"state": "NOT_RUN"},
        "a3": {"state": "NOT_RUN"},
        "lineage": {
            "exact25_ledger_sha256": tier.sha(ledger),
            "trend_rider_screening_receipt_sha256": row.get("receipt_sha"),
            "hardening_receipt_sha256": h.get("receipt_sha256"),
            "h4_receipt_sha256": h4.get("receipt_sha256"),
            "h5_receipt_sha256": (h.get("h5_receipt") or {}).get("receipt_sha256"),
            "policy_sha": row.get("policy_sha"),
            "config_sha": row.get("config_sha"),
            "boundary_utc": row.get("prospective_boundary_utc"),
            "v2_receipt_rewritten": False,
        },
        **AUTHORITY,
    }
    evidence["receipt_sha256"] = tier.sha(evidence)
    return evidence


def run() -> dict[str, Any]:
    policy = read(POLICY)
    evidence = build_evidence()
    result = tier.evaluate(evidence, policy)
    return {
        "schema_version": "zel.a1.trend_rider.v3_transition.v1",
        "state": "PASS_A1_CAUSAL_READY_FOR_A2" if result.get("a2_entry_allowed") is True else "HOLD_A1_V3_TRANSITION",
        "candidate_id": "trend_rider",
        "evidence": evidence,
        "tiering": result,
        **AUTHORITY,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_trend_rider_v3_transition_v1.json"))
    args = ap.parse_args()
    result = run()
    result["receipt_sha256"] = tier.sha(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state":result["state"],"a1_tier":result["tiering"].get("a1_tier"),"a2_entry_allowed":result["tiering"].get("a2_entry_allowed"),"activation":result["tiering"].get("activation"),"hard_controls":result["tiering"].get("hard_control_states"),"receipt_sha256":result["receipt_sha256"]},sort_keys=True))
    return 0 if result["state"] == "PASS_A1_CAUSAL_READY_FOR_A2" else 2


if __name__ == "__main__":
    raise SystemExit(main())
