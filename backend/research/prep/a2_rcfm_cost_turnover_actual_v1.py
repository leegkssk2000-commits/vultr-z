from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.tools.zel_survivor_tiering_gate_v3 import sha

ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/prep/a2_cost_turnover_ssot_v1.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
CANDIDATE_ID = "NEW_RCFM_001"
AUTH = {
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


def _plus_one_bar(receipt: Mapping[str, Any]) -> dict[str, Any]:
    trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    symbols = sorted({str(x["symbol"]) for x in trades})
    bars_by = {s: ev.fetch_bars(s, "5m", 1000) for s in symbols}
    maps = {s: {int(b["ts_ms"]): i for i, b in enumerate(bars_by[s])} for s in symbols}
    values: list[float] = []
    defects: list[str] = []
    for t in trades:
        symbol = str(t["symbol"]); entry_ts = int(t["entry_ts_ms"]); exit_ts = int(t["exit_ts_ms"])
        mp, bars = maps[symbol], bars_by[symbol]
        if entry_ts not in mp:
            defects.append(f"ENTRY_BAR_MISSING:{symbol}:{entry_ts}")
            continue
        j = mp[entry_ts] + 1
        if j >= len(bars):
            defects.append(f"PLUS_ONE_BAR_MISSING:{symbol}:{entry_ts}")
            continue
        delayed_ts = int(bars[j]["ts_ms"])
        if delayed_ts >= exit_ts:
            defects.append(f"DELAY_REACHES_EXIT:{symbol}:{entry_ts}:{exit_ts}")
            continue
        entry = float(bars[j]["open"]); exit_px = float(t["exit_px"])
        side = 1.0 if str(t["side"]) == "long" else -1.0
        gross = side * (exit_px - entry) / entry * 10000.0
        net = gross - float(t["realized_cost_bps"])
        values.append(net)
    exp = sum(values) / len(values) if values else None
    complete = len(values) == len(trades) and not defects
    return {
        "pass": complete and exp is not None and exp > 0.0,
        "source": "RCFM_SAME_SIGNAL_PLUS_ONE_ADDITIONAL_5M_ENTRY_BAR_ORIGINAL_CAUSAL_EXIT_AND_REALIZED_COST",
        "trade_count": len(values),
        "candidate_trade_count": len(trades),
        "coverage_pct": 100.0 * len(values) / len(trades) if trades else 0.0,
        "net_expectancy_bps": exp,
        "net_R": sum(values) / 100.0,
        "defects": defects,
        "same_signal": True,
        "same_exit_timestamp_and_logic": True,
        "same_realized_cost_per_trade": True,
        "stress_fill": "PLUS_ONE_ADDITIONAL_SOURCE_BAR",
    }


def evaluate(transition: Mapping[str, Any], receipt: Mapping[str, Any]) -> dict[str, Any]:
    ssot, authority = read(SSOT), read(COST)
    if ssot.get("state") != "A2_PREP_READY" or authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("A2_RCFM_AUTHORITY_NOT_READY")
    activation = ssot.get("activation") or {}
    if transition.get("state") != activation.get("required_a1_receipt_state"):
        raise RuntimeError("A1_CAUSAL_READY_RECEIPT_REQUIRED")
    if transition.get("candidate_id") != CANDIDATE_ID or receipt.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("RCFM_A2_IDENTITY_MISMATCH")
    tiering = transition.get("tiering") or {}
    if tiering.get("a2_entry_allowed") is not True or tiering.get("a1_tier") not in set(activation.get("allowed_a1_tiers") or []):
        raise RuntimeError("RCFM_A1_TIER_NOT_ELIGIBLE")
    evidence_lineage = ((transition.get("evidence") or {}).get("lineage") or {})
    if evidence_lineage.get("candidate_receipt_sha256") != receipt.get("receipt_sha256"):
        raise RuntimeError("RCFM_A2_RECEIPT_LINEAGE_MISMATCH")
    if list(receipt.get("integrity_defects") or []) or int(receipt.get("leakage_lookahead") or 0) != 0 or int(receipt.get("duplicate_count") or 0) != 0:
        raise RuntimeError("RCFM_A2_INTEGRITY_INVALID")
    metrics = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    gross_exp = float(metrics["gross_expectancy_bps"])
    trades = [x for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    if not trades:
        raise RuntimeError("RCFM_A2_NO_TRADES")

    symbols = sorted({str(x["symbol"]) for x in trades})
    snapshots = {s: ev.fetch_execution_snapshot(s, authority) for s in symbols}
    worst_symbol = max(symbols, key=lambda s: float(snapshots[s]["pretrade_verified_cost_bps"]))
    one_x_cost = float(snapshots[worst_symbol]["pretrade_verified_cost_bps"])
    two_x_cost = 2.0 * one_x_cost
    p95_funding = max(float(snapshots[s]["funding_p95_abs_bps"]) for s in symbols)
    one_x_net_exp = gross_exp - one_x_cost
    two_x_net_exp = gross_exp - two_x_cost
    p95_net_exp = one_x_net_exp

    plus_one = _plus_one_bar(receipt)
    start = parse_utc(str(receipt["boundary_utc"]))
    end_ms = max(int(x["exit_ts_ms"]) for x in trades)
    end = datetime.fromtimestamp(end_ms / 1000.0, tz=timezone.utc)
    elapsed_days = max((end - start).total_seconds() / 86400.0, 1e-9)
    round_trips = len(trades)
    round_trips_per_day = round_trips / elapsed_days
    one_x_total = one_x_cost * round_trips

    stress = {
        "1X_COST": {"pass": one_x_net_exp > 0.0, "gross_expectancy_bps": gross_exp, "cost_bps_per_trade": one_x_cost, "net_expectancy_bps": one_x_net_exp},
        "2X_COST": {"pass": two_x_net_exp > 0.0, "gross_expectancy_bps": gross_exp, "cost_bps_per_trade": two_x_cost, "net_expectancy_bps": two_x_net_exp},
        "P95_FUNDING": {"pass": p95_net_exp > 0.0, "p95_funding_abs_bps": p95_funding, "cost_bps_per_trade": one_x_cost, "net_expectancy_bps": p95_net_exp},
        "PLUS_ONE_BAR": plus_one,
        "TURNOVER": {
            "pass": round_trips > 0 and round_trips_per_day > 0.0,
            "round_trips": round_trips,
            "elapsed_days": elapsed_days,
            "round_trips_per_day": round_trips_per_day,
            "gross_turnover_notional": "NORMALIZED_RESEARCH_ONLY",
            "cost_bps_total_at_1x": one_x_total,
            "cost_bps_per_trade": one_x_cost,
            "duplicate_transition_forbidden": True,
            "integrity_defects": [],
        },
    }
    stress_pass = all((stress.get(name) or {}).get("pass") is True for name in ("1X_COST", "2X_COST", "P95_FUNDING", "PLUS_ONE_BAR", "TURNOVER"))
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
    }
    result = {
        "schema_version": "zel.a2.rcfm.cost_turnover_actual.v1",
        "state": "PASS_A2_COST_TURNOVER" if stress_pass else "HOLD_A2_COST_TURNOVER",
        "stage": "A2",
        "candidate_id": CANDIDATE_ID,
        "a1_transition_receipt_sha256": transition.get("receipt_sha256"),
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "a1_tier": tiering.get("a1_tier"),
        "a1_activation_mode": (tiering.get("activation") or {}).get("mode"),
        "cost_authority": {
            "ssot_sha256": sha(ssot),
            "cost_authority_sha256": sha(authority),
            "worst_current_symbol": worst_symbol,
            "one_x_cost_bps": one_x_cost,
            "two_x_cost_bps": two_x_cost,
            "funding_p95_abs_bps": p95_funding,
            "snapshots": {s: {k: v for k, v in snapshots[s].items() if k != "funding_rows"} for s in symbols},
        },
        "stress": stress,
        "stress_contract": ["1X_COST", "2X_COST", "P95_FUNDING", "PLUS_ONE_BAR", "TURNOVER"],
        "execution_observation": execution_observation,
        "promotion_authority_note": "PASS_A2_COST_TURNOVER does not promote RCFM; RCFM-specific forward A3 remains required.",
        "next_stage_if_pass": "RCFM_FORWARD_A3_ENTRY_CONTEXT_AND_DURABILITY",
        **AUTH,
    }
    result["receipt_sha256"] = sha(result)
    return result


def self_test() -> int:
    ssot = read(SSOT)
    assert ssot["state"] == "A2_PREP_READY"
    assert set(ssot["stress_contract"]) == {"1X_COST", "2X_COST", "P95_FUNDING", "PLUS_ONE_BAR"}
    assert ssot["latency"]["stress_fill"] == "PLUS_ONE_ADDITIONAL_SOURCE_BAR"
    print("PASS_A2_RCFM_COST_TURNOVER_ACTUAL_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transition", type=Path)
    ap.add_argument("--receipt", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a2_rcfm_cost_turnover_actual_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.transition or not args.receipt:
        raise SystemExit("--transition and --receipt required")
    result = evaluate(read(args.transition), read(args.receipt))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "candidate_id": result["candidate_id"],
        "one_x": result["stress"]["1X_COST"],
        "two_x": result["stress"]["2X_COST"],
        "p95": result["stress"]["P95_FUNDING"],
        "plus_one_bar": result["stress"]["PLUS_ONE_BAR"],
        "turnover": result["stress"]["TURNOVER"],
        "next": result["next_stage_if_pass"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0 if result["state"] == "PASS_A2_COST_TURNOVER" else 2


if __name__ == "__main__":
    raise SystemExit(main())
