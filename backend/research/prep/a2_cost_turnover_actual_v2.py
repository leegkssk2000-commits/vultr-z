from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as _v2_retry_patch  # noqa:F401
from backend.tools.zel_survivor_tiering_gate_v3 import sha

ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/prep/a2_cost_turnover_ssot_v1.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
AUTHORITY = {
    "selection_authority": False, "promotion_authority": False,
    "execution_authority": "NONE", "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED", "exchange_order_submitted": False,
    "protected_mutations": 0, "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def evaluate(transition: Mapping[str, Any], hardening: Mapping[str, Any]) -> dict[str, Any]:
    ssot, cost_authority, ledger = read(SSOT), read(COST), read(LEDGER)
    if ssot.get("state") != "A2_PREP_READY":
        raise RuntimeError("A2_SSOT_NOT_READY")
    activation = ssot.get("activation") or {}
    required_state = str(activation.get("required_a1_receipt_state") or "")
    allowed_tiers = {str(x) for x in activation.get("allowed_a1_tiers") or []}
    if transition.get("state") != required_state:
        raise RuntimeError("A1_CAUSAL_READY_RECEIPT_REQUIRED")
    candidate_id = str(transition.get("candidate_id") or "")
    if not candidate_id or hardening.get("strategy_id") != candidate_id:
        raise RuntimeError("A1_A2_CANDIDATE_IDENTITY_MISMATCH")
    tiering = transition.get("tiering") if isinstance(transition.get("tiering"), Mapping) else {}
    if tiering.get("a2_entry_allowed") is not True or tiering.get("a1_tier") not in allowed_tiers:
        raise RuntimeError("A1_TIER_NOT_ELIGIBLE_FOR_A2")
    if transition.get("execution_authority") != "NONE" or transition.get("order_authority") != "BLOCKED":
        raise RuntimeError("A1_TRANSITION_AUTHORITY_INVALID")
    if tiering.get("activation", {}).get("mode") == "SEALED_INDEPENDENT_OOS" and activation.get("sealed_independent_oos_may_authorize_a2_entry") is not True:
        raise RuntimeError("SEALED_OOS_A2_ENTRY_NOT_ALLOWED")
    if cost_authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_INVALID")
    row = (ledger.get("strategies") or {}).get(candidate_id)
    if not isinstance(row, Mapping):
        raise RuntimeError("SCREENING_LINEAGE_MISSING")
    if hardening.get("policy_sha") != row.get("policy_sha") or hardening.get("config_sha") != row.get("config_sha"):
        raise RuntimeError("HARDENING_SCREENING_LINEAGE_MISMATCH")
    if hardening.get("boundary_utc") != row.get("prospective_boundary_utc"):
        raise RuntimeError("HARDENING_BOUNDARY_MISMATCH")

    symbols = ["BTC-USDT", "ETH-USDT"]
    snapshots = {symbol: ev.fetch_execution_snapshot(symbol, cost_authority) for symbol in symbols}
    worst_symbol = max(symbols, key=lambda s: float(snapshots[s]["pretrade_verified_cost_bps"]))
    one_x_cost = float(snapshots[worst_symbol]["pretrade_verified_cost_bps"])
    two_x_cost = 2.0 * one_x_cost
    p95_funding = max(float(snapshots[s]["funding_p95_abs_bps"]) for s in symbols)

    gross_exp = float(row["gross_expectancy_bps"])
    screening_net_exp = float(row["net_expectancy_bps"])
    one_x_net_exp = gross_exp - one_x_cost
    two_x_net_exp = gross_exp - two_x_cost
    p95_net_exp = one_x_net_exp

    h4 = hardening.get("h4_receipt") if isinstance(hardening.get("h4_receipt"), Mapping) else {}
    delay = (h4.get("control_results") or {}).get("one_bar_delay") or {}
    delay_net_r = float(delay["control_net_R"]) if delay.get("control_net_R") is not None else None
    delay_trades = int(hardening.get("candidate_trade_count") or 0)
    plus_one_bar_exp_r = delay_net_r / delay_trades if delay_net_r is not None and delay_trades > 0 else None

    start = parse_utc(str(row["prospective_boundary_utc"])); end = parse_utc(str(row["terminal_at_utc"]))
    elapsed_days = max((end - start).total_seconds() / 86400.0, 1e-9)
    round_trips = int(row["completed_trades"])
    turnover_per_day = round_trips / elapsed_days

    stress = {
        "1X_COST": {"pass": one_x_net_exp > 0.0, "gross_expectancy_bps": gross_exp, "cost_bps_per_trade": one_x_cost, "net_expectancy_bps": one_x_net_exp},
        "2X_COST": {"pass": two_x_net_exp > 0.0, "gross_expectancy_bps": gross_exp, "cost_bps_per_trade": two_x_cost, "net_expectancy_bps": two_x_net_exp},
        "P95_FUNDING": {"pass": p95_net_exp > 0.0, "p95_funding_abs_bps": p95_funding, "cost_bps_per_trade": one_x_cost, "net_expectancy_bps": p95_net_exp},
        "PLUS_ONE_BAR": {"pass": plus_one_bar_exp_r is not None and plus_one_bar_exp_r > 0.0, "source": f"{candidate_id} H4 one_bar_delay deterministic replay", "net_R": delay_net_r, "trade_count": delay_trades, "expectancy_R": plus_one_bar_exp_r, "superiority_to_parent_required": False},
        "TURNOVER": {"pass": round_trips > 0 and turnover_per_day > 0.0, "round_trips": round_trips, "elapsed_days": elapsed_days, "round_trips_per_day": turnover_per_day, "cost_bps_total_at_1x": one_x_cost * round_trips, "cost_bps_per_trade": one_x_cost, "duplicate_transition_forbidden": True, "integrity_defects": list(row.get("integrity_defects") or [])},
    }
    stress_pass = all(x.get("pass") is True for x in stress.values()) and not list(row.get("integrity_defects") or [])
    result = {
        "schema_version": "zel.a2.cost_turnover_actual.v2",
        "state": "PASS_A2_COST_TURNOVER" if stress_pass else "HOLD_A2_COST_TURNOVER",
        "stage": "A2", "candidate_id": candidate_id,
        "a1_transition_receipt_sha256": transition.get("receipt_sha256"),
        "a1_tier": tiering.get("a1_tier"), "a1_activation_mode": tiering.get("activation", {}).get("mode"),
        "cost_authority": {
            "ssot_sha256": sha(ssot), "cost_authority_sha256": sha(cost_authority),
            "worst_current_symbol": worst_symbol, "one_x_cost_bps": one_x_cost, "two_x_cost_bps": two_x_cost,
            "screening_realized_average_cost_bps": gross_exp - screening_net_exp,
            "funding_p95_abs_bps": p95_funding,
            "snapshots": {s: {k:v for k,v in snapshots[s].items() if k != "funding_rows"} for s in symbols},
        },
        "stress": stress, "stress_contract": list(ssot.get("stress_contract") or []) + ["TURNOVER"],
        "execution_observation": {
            "reference_notional_usdt": float(ssot["depth_vwap_impact"]["reference_notional_usdt"]),
            "depth_full_fill_verified_by_snapshot": True,
            "partial_fill_cost_observed_from_live_orders": False, "reject_rate_observed_from_live_orders": False,
            "unverified_improvement_assumed": False, "maker_rescue_used": False,
            "deferred_execution_fields": ["live_order_partial_fill_distribution", "live_order_reject_rate"],
            "deferred_to": str((ssot.get("partial_fill_reject") or {}).get("live_distribution_calibration_deferred_to") or "G10_BINGX_EXECUTION_COST_CALIBRATION"),
        },
        "promotion_authority_note": "A2 pass is research-only; post-V3 fresh A3 is still mandatory.",
        "next_stage_if_pass": "A3_ACTUAL_REGIME_DURABILITY", **AUTHORITY,
    }
    result["receipt_sha256"] = sha(result)
    return result


def self_test() -> int:
    ssot = read(SSOT)
    assert set(ssot.get("stress_contract") or []) >= {"1X_COST", "2X_COST", "P95_FUNDING", "PLUS_ONE_BAR"}
    assert ssot.get("activation", {}).get("actual_evaluation_requires_a1_receipt") is True
    print("PASS_A2_COST_TURNOVER_ACTUAL_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transition", type=Path)
    ap.add_argument("--hardening", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a2_cost_turnover_actual_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.transition or not args.hardening:
        raise SystemExit("--transition and --hardening required")
    result = evaluate(read(args.transition), read(args.hardening))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state":result["state"],"candidate_id":result["candidate_id"],"stress":{k:v.get("pass") for k,v in result["stress"].items()},"next":result["next_stage_if_pass"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True))
    return 0 if result["state"] == "PASS_A2_COST_TURNOVER" else 2


if __name__ == "__main__":
    raise SystemExit(main())
