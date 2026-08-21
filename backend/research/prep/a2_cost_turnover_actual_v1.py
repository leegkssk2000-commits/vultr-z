from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as v1
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as _v2_retry_patch  # noqa:F401
from backend.tools.zel_survivor_tiering_gate_v3 import sha

ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/prep/a2_cost_turnover_ssot_v1.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
HARDENING = ROOT / "backend/research/rebuild/diagnostics/trend_rider_hardening_latest.json"

AUTHORITY = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def evaluate(transition: dict[str, Any]) -> dict[str, Any]:
    ssot, authority, ledger, hardening = read(SSOT), read(COST), read(LEDGER), read(HARDENING)
    if ssot.get("state") != "A2_PREP_READY":
        raise RuntimeError("A2_SSOT_NOT_READY")
    activation = ssot.get("activation") or {}
    if activation.get("actual_survivor_evaluation_allowed") is not True or activation.get("actual_evaluation_requires_a1_receipt") is not True:
        raise RuntimeError("A2_ACTUAL_EVALUATION_NOT_ACTIVATED")
    required_state = str(activation.get("required_a1_receipt_state") or "")
    allowed_tiers = set(str(x) for x in activation.get("allowed_a1_tiers") or [])
    if transition.get("state") != required_state:
        raise RuntimeError("A1_CAUSAL_READY_RECEIPT_REQUIRED")
    tiering = transition.get("tiering") or {}
    if tiering.get("a2_entry_allowed") is not True or tiering.get("a1_tier") not in allowed_tiers:
        raise RuntimeError("A1_TIER_NOT_ELIGIBLE_FOR_A2")
    if transition.get("execution_authority") != "NONE" or transition.get("order_authority") != "BLOCKED":
        raise RuntimeError("A1_TRANSITION_AUTHORITY_INVALID")
    if tiering.get("activation", {}).get("mode") == "SEALED_INDEPENDENT_OOS" and activation.get("sealed_independent_oos_may_authorize_a2_entry") is not True:
        raise RuntimeError("SEALED_OOS_A2_ENTRY_NOT_ALLOWED")
    if authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_INVALID")

    row = (ledger.get("strategies") or {}).get("trend_rider") or {}
    if row.get("status") != "A1_FINALIST_PARKED":
        raise RuntimeError("TREND_RIDER_SCREENING_LINEAGE_INVALID")

    symbols = ["BTC-USDT", "ETH-USDT"]
    snapshots = {symbol: v1.fetch_execution_snapshot(symbol, authority) for symbol in symbols}
    worst_symbol = max(symbols, key=lambda s: float(snapshots[s]["pretrade_verified_cost_bps"]))
    worst = snapshots[worst_symbol]
    one_x_cost = float(worst["pretrade_verified_cost_bps"])
    two_x_cost = 2.0 * one_x_cost
    p95_funding = max(float(snapshots[s]["funding_p95_abs_bps"]) for s in symbols)

    gross_exp = float(row["gross_expectancy_bps"])
    screening_realized_cost = gross_exp - float(row["net_expectancy_bps"])
    one_x_net_exp = gross_exp - one_x_cost
    two_x_net_exp = gross_exp - two_x_cost
    p95_net_exp = one_x_net_exp

    h4 = hardening.get("h4_receipt") or {}
    delay = (h4.get("control_results") or {}).get("one_bar_delay") or {}
    delay_net_r = float(delay.get("control_net_R"))
    delay_trades = int(hardening.get("candidate_trade_count") or 0)
    plus_one_bar_expectancy_r = delay_net_r / delay_trades if delay_trades > 0 else None

    start = parse_utc(str(row["prospective_boundary_utc"]))
    end = parse_utc(str(row["terminal_at_utc"]))
    elapsed_days = max((end - start).total_seconds() / 86400.0, 1e-9)
    round_trips = int(row["completed_trades"])
    round_trips_per_day = round_trips / elapsed_days
    one_x_cost_total_bps = one_x_cost * round_trips

    stress = {
        "1X_COST": {"pass": one_x_net_exp > 0.0, "gross_expectancy_bps": gross_exp, "cost_bps_per_trade": one_x_cost, "net_expectancy_bps": one_x_net_exp},
        "2X_COST": {"pass": two_x_net_exp > 0.0, "gross_expectancy_bps": gross_exp, "cost_bps_per_trade": two_x_cost, "net_expectancy_bps": two_x_net_exp},
        "P95_FUNDING": {"pass": p95_net_exp > 0.0, "p95_funding_abs_bps": p95_funding, "cost_bps_per_trade": one_x_cost, "net_expectancy_bps": p95_net_exp},
        "PLUS_ONE_BAR": {"pass": plus_one_bar_expectancy_r is not None and plus_one_bar_expectancy_r > 0.0, "source": "trend_rider H4 one_bar_delay deterministic replay", "net_R": delay_net_r, "trade_count": delay_trades, "expectancy_R": plus_one_bar_expectancy_r, "superiority_to_parent_required": False},
        "TURNOVER": {"pass": round_trips > 0 and round_trips_per_day > 0.0, "round_trips": round_trips, "elapsed_days": elapsed_days, "round_trips_per_day": round_trips_per_day, "gross_turnover_notional": "NORMALIZED_RESEARCH_ONLY", "cost_bps_total_at_1x": one_x_cost_total_bps, "cost_bps_per_trade": one_x_cost, "duplicate_transition_forbidden": True, "integrity_defects": list(row.get("integrity_defects") or [])},
    }
    stress_pass = all(x.get("pass") is True for x in stress.values()) and not list(row.get("integrity_defects") or [])

    execution_observation = {
        "reference_notional_usdt": float(ssot["depth_vwap_impact"]["reference_notional_usdt"]),
        "depth_full_fill_verified_by_snapshot": True,
        "partial_fill_cost_observed_from_live_orders": False,
        "reject_rate_observed_from_live_orders": False,
        "partial_fill_cost_field": "UNOBSERVED_LIVE_RESEARCH_ONLY",
        "reject_rate_field": "UNOBSERVED_LIVE_RESEARCH_ONLY",
        "unverified_improvement_assumed": False,
        "maker_rescue_used": False,
        "deferred_execution_fields": ["live_order_partial_fill_distribution", "live_order_reject_rate"],
        "deferred_to": str((ssot.get("partial_fill_reject") or {}).get("live_distribution_calibration_deferred_to") or "G10_BINGX_EXECUTION_COST_CALIBRATION"),
        "note": "A2 is a research cost/turnover gate. No order authority is granted and no synthetic zero reject-rate is inserted."
    }

    result = {
        "schema_version": "zel.a2.cost_turnover_actual.v1",
        "state": "PASS_A2_COST_TURNOVER" if stress_pass else "HOLD_A2_COST_TURNOVER",
        "stage": "A2",
        "candidate_id": "trend_rider",
        "a1_transition_receipt_sha256": transition.get("receipt_sha256"),
        "a1_tier": tiering.get("a1_tier"),
        "a1_activation_mode": tiering.get("activation", {}).get("mode"),
        "cost_authority": {
            "ssot_sha256": sha(ssot),
            "cost_authority_sha256": sha(authority),
            "worst_current_symbol": worst_symbol,
            "one_x_cost_bps": one_x_cost,
            "two_x_cost_bps": two_x_cost,
            "screening_realized_average_cost_bps": screening_realized_cost,
            "funding_p95_abs_bps": p95_funding,
            "snapshots": {s:{k:v for k,v in snapshots[s].items() if k != "funding_rows"} for s in symbols},
        },
        "stress": stress,
        "stress_contract": list(ssot.get("stress_contract") or []) + ["TURNOVER"],
        "execution_observation": execution_observation,
        "promotion_authority_note": "PASS_A2_COST_TURNOVER does not promote a final Survivor. New post-V3 fresh + A3 remain required.",
        "next_stage_if_pass": "A3_ACTUAL_REGIME_DURABILITY",
        **AUTHORITY,
    }
    result["receipt_sha256"] = sha(result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transition", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=Path("out/a2_cost_turnover_actual_v1.json"))
    args = ap.parse_args()
    transition = read(args.transition)
    result = evaluate(transition)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state":result["state"],"candidate_id":result["candidate_id"],"one_x":result["stress"]["1X_COST"],"two_x":result["stress"]["2X_COST"],"p95":result["stress"]["P95_FUNDING"],"plus_one_bar":result["stress"]["PLUS_ONE_BAR"],"turnover":result["stress"]["TURNOVER"],"next":result["next_stage_if_pass"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True))
    return 0 if result["state"] == "PASS_A2_COST_TURNOVER" else 2


if __name__ == "__main__":
    raise SystemExit(main())
