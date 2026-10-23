#!/usr/bin/env python3
"""FROZEN Supertrend Momentum 4h: source-pinned cohort and winner-risk gate.

Reads closed historical trade rows only. Never selects trading conditions,
creates a child, fetches market data or claims independent profitability.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

SOURCE_GIT_BLOB = "70f5f6829d860a67f7df8e4ff1994965218c042c"
CHILD = "supertrend_replacement_highvol_mom_long_4h_h12_v2"
G5_BOUNDARY_MS = 1789228800000
BAR_MS = 4 * 60 * 60 * 1000

def git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")

def net2(row: dict) -> float:
    return float(row["gross_bps"]) - 2 * float(row["cost_bps"])

def load(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if git_blob(raw) != SOURCE_GIT_BLOB:
        raise ValueError("SOURCE_BLOB_MISMATCH")
    body = json.loads(raw)
    lane = body["lanes"]["supertrend_pullback_main"]
    all_rows = lane["closed_trades"]
    if len(all_rows) != 39 or lane["child_id"] != CHILD:
        raise ValueError("WRONG_ORIGINAL_COHORT")
    ids = set()
    for r in all_rows:
        if r.get("child_id") != CHILD or r.get("side") != "long":
            raise ValueError("WRONG_STRATEGY")
        if type(r.get("cost_bps")) not in (int, float) or float(r["cost_bps"]) != 20.0:
            raise ValueError("COST_MODEL_CHANGED")
        for f in ("signal_ts", "entry_ts", "exit_ts"):
            if type(r.get(f)) is not int or r[f] % BAR_MS:
                raise ValueError("BAD_TIMESTAMP_OR_TIMEFRAME")
        if r["entry_ts"] != r["signal_ts"] + BAR_MS or r["exit_ts"] != r["entry_ts"] + 11 * BAR_MS:
            raise ValueError("ORIGINAL_NEXT_OPEN_H12_IDENTITY_CHANGED")
        if abs(float(r["net_bps"]) - (float(r["gross_bps"]) - 20.0)) > 1e-6:
            raise ValueError("ORIGINAL_NET1_PARITY_FAILED")
        i = r.get("closed_trade_id")
        if not i or i in ids:
            raise ValueError("DUPLICATE_OR_MISSING_TRADE_ID")
        ids.add(i)
    post = [r for r in all_rows if r["signal_ts"] >= G5_BOUNDARY_MS]
    if len(post) != 26:
        raise ValueError("FROZEN_G5_COHORT_SIZE_CHANGED")
    return post

def report(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("EMPTY_COHORT")
    winners = sorted((r for r in rows if net2(r) > 0), key=net2, reverse=True)
    if len(winners) < 2:
        raise ValueError("INSUFFICIENT_WINNERS")
    a, b = winners[:2]
    total = sum(net2(r) for r in rows)
    entry_buckets = defaultdict(list)
    exit_buckets = defaultdict(list)
    for r in rows:
        entry_buckets[(r["entry_ts"], r["exit_ts"])].append(r)
        exit_buckets[r["exit_ts"]].append(r)
    entry_cohorts = sorted(entry_buckets.items())
    exit_cohorts = sorted(exit_buckets.items())
    posthoc_winner = lambda x: {
        "closed_trade_id": x["closed_trade_id"], "symbol": x["symbol"],
        "entry_utc": iso(x["entry_ts"]), "exit_bar_open_utc": iso(x["exit_ts"]),
        "modeled_cost2_net_trade_bps": net2(x),
    }
    max_consec = current = 0
    max_consec_loss = running_loss = 0.0
    for ts, trades in exit_cohorts:
        group_net = sum(net2(z) for z in trades)
        if group_net < 0:
            current += 1
            running_loss += group_net
            if current > max_consec:
                max_consec = current
                max_consec_loss = running_loss
        else:
            current = 0
            running_loss = 0.0
    earliest_exit = min(x["exit_ts"] for x in rows)
    cohort = entry_buckets[(a["entry_ts"], a["exit_ts"])]
    if b["entry_ts"] != a["entry_ts"] or b["exit_ts"] != a["exit_ts"]:
        same_time = False
    else:
        same_time = True
    return {
        "schema": "zel.supertrend4h.winner_and_correlated_loss_cohort_v1",
        "source_original_github_blob": SOURCE_GIT_BLOB,
        "classification": "FROZEN_G5_POSTHOC_DIAGNOSTIC_NOT_DECISION_FEATURE",
        "identity": CHILD, "g5_boundary_ms": G5_BOUNDARY_MS,
        "used_reviewed_G5_postboundary_T": len(rows),
        "cost_model": "model_fixed_20bps_per_trade_at_1x_40bps_at_2x_not_realized_funding_slippage",
        "net2_trade_bps_total": total,
        "cost2_profitable_trade_count": len(winners),
        "top2_profit": [posthoc_winner(a), posthoc_winner(b)],
        "top2_same_entry_and_exit": same_time,
        "top2_model_net2_sum": net2(a) + net2(b),
        "other_24_model_net2_sum": total - net2(a) - net2(b),
        "top2_shared_entry_cohort": {
            "entry_utc": iso(a["entry_ts"]), "exit_bar_open_utc": iso(a["exit_ts"]),
            "T": len(cohort), "win_count_cost2": sum(net2(x)>0 for x in cohort),
            "model_cost2_net_bps": sum(net2(x) for x in cohort),
            "symbols": sorted(x["symbol"] for x in cohort),
        },
        "exit_batched_cohorts": len(exit_cohorts),
        "max_consecutive_negative_exit_cohorts": max_consec,
        "cumulative_model_net2_at_first_max_negative_exit_cohort_run": max_consec_loss,
        "method": "sort exits by original bar-open ts and group all same-ts exits before streak attribution",
        "first_exit_bar_open_utc": iso(earliest_exit),
        "gate": {
            "immutable_postentry_4h_market_OHLC_with_available_at_ms": "NOT_BOUND",
            "original_native_ema20_ema50_for_each_completed_4h_bar": "NOT_BOUND",
            "historical_actual_funding_and_fill": "NOT_BOUND",
            "safe_new_child_economics_allowed": False,
            "G5_pass_authority": False,
            "K117_shadow_status": "SEPARATE_NOT_FORMAL_ACTIVE",
        },
        "limitations": [
            "Original 26 G5 outcomes already reviewed; cannot re-use as untouched OOS.",
            "Top2 identities/month/winners/losses are labels for source retrieval only, NEVER trading signals.",
            "Streak count from same-timestamp sorted trade rows is order-dependent; cohort-level counts are not account DD.",
            "Cost2 is a modeled fixed cost; no portfolio NAV, available-at source, market intrabar or original funding."
        ],
        "economic_full_runs": 0, "order_calls": 0, "new_trade_rule": 0
    }

def selftest() -> None:
    sample = [{"gross_bps": 100.0, "cost_bps": 20.0, "entry_ts": BAR_MS * 2,
               "exit_ts": BAR_MS * 13, "signal_ts": BAR_MS, "symbol": s,
               "closed_trade_id": s} for s in ("BCH-USDT","1000PEPE-USDT")]
    sample += [{"gross_bps": -30.0, "cost_bps": 20.0, "entry_ts": BAR_MS * 6 + BAR_MS * i,
                "exit_ts": BAR_MS * 17 + BAR_MS * i,
                "signal_ts": BAR_MS * 5 + BAR_MS * i, "symbol": "XRP-USDT",
                "closed_trade_id": str(i)} for i in range(2)]
    r = report(sample)
    assert r["used_reviewed_G5_postboundary_T"] == 4
    assert r["top2_same_entry_and_exit"]
    assert r["top2_shared_entry_cohort"]["T"] == 2
    assert r["top2_shared_entry_cohort"]["win_count_cost2"] == 2
    assert r["cost2_profitable_trade_count"] == 2
    assert r["other_24_model_net2_sum"] == -140.0
    assert r["exit_batched_cohorts"] == 3
    assert r["max_consecutive_negative_exit_cohorts"] == 2
    assert not r["gate"]["safe_new_child_economics_allowed"]
    assert not r["new_trade_rule"] and not r["economic_full_runs"]
    print(json.dumps({"synthetic_checks":10,"result":"PASS","orders":0}))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--original", type=Path)
    p.add_argument("--test", action="store_true")
    args = p.parse_args()
    if args.test:
        selftest()
        return
    if not args.original:
        p.error("--original is required")
    print(json.dumps(report(load(args.original)), indent=2, sort_keys=True, allow_nan=False))

if __name__ == "__main__":
    main()
