#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild.a1_trendrider_current12_fresh2_reservoir_v1 import rebuild_current
from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import strict, metrics, payoff, trade_key

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
FRESH2 = ROOT / "backend/research/rebuild/a1_trendrider_8125_fresh2_source_v1.json"
SCHEMA = "zel.a1.trendrider.8125.strict25_fresh_watch.v1"
FREEZE_BOUNDARY_MS = 1787866209000  # PR #1050 merged 2026-08-27T21:30:09Z
REQUIRED_REFERENCE_BPS = 2225.644277854492

# Exact PR #1050 closest-24T donor6 block. Historical oracle only; never promotion evidence.
DONOR6 = [
    {"symbol":"BTC-USDT","signal_ts":1786914000000,"entry_ts":1786917600000,"side":"short","net_bps":-39.60576398325979,"reason":"SL"},
    {"symbol":"BTC-USDT","signal_ts":1787133600000,"entry_ts":1787137200000,"side":"long","net_bps":1897.6021632243794,"reason":"TIMEOUT"},
    {"symbol":"ETH-USDT","signal_ts":1787054400000,"entry_ts":1787058000000,"side":"long","net_bps":1972.4024993415846,"reason":"TIMEOUT"},
    {"symbol":"ETH-USDT","signal_ts":1787072400000,"entry_ts":1787076000000,"side":"long","net_bps":2103.2887645189817,"reason":"TIMEOUT"},
    {"symbol":"ETH-USDT","signal_ts":1787094000000,"entry_ts":1787097600000,"side":"long","net_bps":2190.3015455958616,"reason":"TIMEOUT"},
    {"symbol":"ETH-USDT","signal_ts":1787097600000,"entry_ts":1787101200000,"side":"long","net_bps":2316.0156383979934,"reason":"TIMEOUT"},
]


def read(path: Path) -> dict[str, Any]:
    v = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def compact(t: dict[str, Any]) -> dict[str, Any]:
    return {k:t.get(k) for k in ("symbol","signal_ts","entry_ts","exit_ts","side","net_bps","reason","intent_sha")}


def run() -> dict[str, Any]:
    parent_doc = read(PARENT)
    fresh_doc = read(FRESH2)
    parent = [dict(x) for x in parent_doc.get("trades") or []]
    fresh2 = [dict(x) for x in fresh_doc.get("trades") or []]
    if len(parent) != 16 or abs(float(parent_doc["metrics"]["win_rate"]) - 0.8125) > 1e-12:
        raise RuntimeError("PARENT_16T_8125_MISMATCH")
    if len(fresh2) != 2 or any(float(x.get("net_bps") or 0) <= 0 for x in fresh2):
        raise RuntimeError("FRESH2_MISMATCH")

    current = rebuild_current()
    current_rows = [dict(x) for x in current.get("trades") or []]
    blocked = {trade_key(x) for x in parent + fresh2 + DONOR6}
    unseen_closed = [
        x for x in current_rows
        if int(x.get("signal_ts") or 0) > FREEZE_BOUNDARY_MS and trade_key(x) not in blocked
    ]

    base_added = fresh2 + [dict(x) for x in DONOR6]
    base_ok, base_checks, _, base_metrics, base_payoff = strict(parent, base_added)
    if len(parent) + len(base_added) != 24:
        raise RuntimeError("BASE_24T_MISMATCH")

    candidates = []
    for t in unseen_closed:
        ok, checks, added_m, combined_m, combined_payoff = strict(parent, base_added + [t])
        candidates.append({
            "trade": compact(t),
            "strict25_metric_pass": bool(ok and int(combined_m["trades"]) == 25),
            "checks": checks,
            "added_metrics": added_m,
            "combined_metrics": combined_m,
            "combined_payoff": combined_payoff,
            "reference_highamp_bps_met": float(t.get("net_bps") or 0) >= REQUIRED_REFERENCE_BPS,
        })
    strict25 = [x for x in candidates if x["strict25_metric_pass"]]
    strict25.sort(key=lambda x: float(x["trade"].get("net_bps") or 0), reverse=True)

    state = "PASS_STRICT25_METRIC_CANDIDATE_FOUND_NONPROMOTABLE" if strict25 else "HOLD_WAIT_NEW_UNSEEN_HIGHAMP_CLOSED_T"
    return {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_primary_wr8125",
        "freeze_boundary_ms": FREEZE_BOUNDARY_MS,
        "freeze_boundary_utc": "2026-08-27T21:30:09Z",
        "parent_T": 16,
        "fresh2_T": 2,
        "historical_oracle_donor_T": 6,
        "base_combined_T": 24,
        "base_combined_metrics": base_metrics,
        "base_combined_payoff": base_payoff,
        "base_strict_pass": base_ok,
        "base_failed_checks": [k for k,v in base_checks.items() if not v],
        "required_reference_one_unseen_winner_bps": REQUIRED_REFERENCE_BPS,
        "current_native_T": len(current_rows),
        "current_native_receipt_sha256": current.get("receipt_sha256"),
        "unseen_closed_after_freeze_T": len(unseen_closed),
        "unseen_closed_after_freeze": [compact(x) for x in unseen_closed],
        "strict25_metric_candidate_count": len(strict25),
        "strict25_metric_candidates": strict25,
        "metric_candidate_is_promotion_evidence": False,
        "historical_oracle_donor_is_promotion_evidence": False,
        "next": "DERIVE_AND_FREEZE_OUTCOME_BLIND_PREENTRY_GATE_THEN_REQUIRE_NEW_PROSPECTIVE_CONFIRMATION" if strict25 else "KEEP_COLLECTING_UNSEEN_CLOSED_T_AFTER_FREEZE",
        "parent_immutable": True,
        "fresh2_fixed_not_deleted": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": "hold",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_8125_strict25_fresh_watch_v1.json"))
    args = ap.parse_args()
    r = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": r["state"],
        "current_native_T": r["current_native_T"],
        "unseen_closed_after_freeze_T": r["unseen_closed_after_freeze_T"],
        "strict25_metric_candidate_count": r["strict25_metric_candidate_count"],
    }, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
