#!/usr/bin/env python3
"""Source-pinned, READ-ONLY G5 Supertrend Momentum forensic.

This does not create or optimize a strategy, run economic FULL, start a
collector, or grant any G5A/G5B, Shadow, Paper, Live or order authority.
Post-boundary outcomes are diagnostic and may NOT train a new entry filter.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

SOURCE_BLOB = "70f5f6829d860a67f7df8e4ff1994965218c042c"
SSOT_BLOB = "4ea2a275518ef728ee05985a9266cfedc0583c34"
FROZEN_ID = "supertrend_replacement_highvol_mom_long_4h_h12_v2"
BOUNDARY = 1789228800000
COLLECTOR_T = 39
G5_FRESH_T = 26
MODELED_COST_BPS = 20


def pinned_json(path: Path, expected_blob: str) -> tuple[dict, str]:
    content = path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\x00" + content).hexdigest()
    if blob != expected_blob:
        raise ValueError("FROZEN_SOURCE_BLOB_MISMATCH")
    return json.loads(content), hashlib.sha256(content).hexdigest()


def valid_row(t: dict) -> None:
    if t.get("child_id") != FROZEN_ID or t.get("side") != "long":
        raise ValueError("WRONG_FROZEN_ID_OR_SIDE")
    for key in ("signal_ts", "entry_ts", "exit_ts"):
        if type(t.get(key)) is not int:
            raise ValueError("INVALID_TIMESTAMP")
    if not 0 <= t["signal_ts"] <= t["entry_ts"] < t["exit_ts"]:
        raise ValueError("TIMESTAMP_CAUSAL_ORDER_INVALID")
    if not t.get("closed_trade_id") or not isinstance(t.get("symbol"), str):
        raise ValueError("TRADE_ID_OR_SYMBOL_MISSING")
    for key in ("cost_bps", "gross_bps", "net_bps", "entry_px", "exit_px"):
        if type(t.get(key)) not in (int, float) or not math.isfinite(t[key]):
            raise ValueError("NONFINITE_OR_MISSING_ACCOUNTING")
    if t["entry_px"] <= 0 or t["exit_px"] <= 0 or t["cost_bps"] != MODELED_COST_BPS:
        raise ValueError("MODEL_PRICE_OR_COST_CHANGED")
    if not math.isclose(t["gross_bps"] - t["cost_bps"], t["net_bps"], abs_tol=1e-8):
        raise ValueError("GROSS_COST_NET_DOES_NOT_RECONCILE")


def summarize(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("EMPTY_COHORT")
    net1 = [r["net_bps"] for r in rows]
    net2 = [r["gross_bps"] - 2*r["cost_bps"] for r in rows]
    sum1, sum2 = math.fsum(net1), math.fsum(net2)
    profit = math.fsum(x for x in net2 if x > 0)
    loss = -math.fsum(x for x in net2 if x < 0)
    top = sorted((x for x in net2 if x > 0), reverse=True)
    profit_total = math.fsum(top)
    months = defaultdict(lambda: {"trades": 0, "net2_trade_bps": 0.0})
    symbols = defaultdict(lambda: {"trades": 0, "net2_trade_bps": 0.0})
    seq = sorted(rows, key=lambda r:(r["exit_ts"], r["closed_trade_id"]))
    running = best = dd = 0.0
    losing = longest = 0
    for r in seq:
        pnl2 = r["gross_bps"] - 2*r["cost_bps"]
        running += pnl2
        best = max(best, running)
        dd = max(dd, best - running)
        losing = losing + 1 if pnl2 < 0 else 0
        longest = max(longest, losing)
    for r in rows:
        m = datetime.fromtimestamp(r["entry_ts"]/1000, tz=timezone.utc).strftime("%Y-%m")
        pnl2 = r["gross_bps"] - 2*r["cost_bps"]
        months[m]["trades"] += 1
        months[m]["net2_trade_bps"] += pnl2
        symbols[r["symbol"]]["trades"] += 1
        symbols[r["symbol"]]["net2_trade_bps"] += pnl2
    removed = {}
    for n in (1,2,3,5):
        removed[str(n)] = {
            "posthoc_drop_profit_winners_net2_trade_bps": sum2 - math.fsum(top[:n]),
            "posthoc_fraction_positive_net2_profit": math.fsum(top[:n])/profit_total if profit_total else None,
        }
    return {
        "T": len(rows), "wins_net1": sum(x>0 for x in net1), "wins_net2": sum(x>0 for x in net2),
        "gross_total_bps": math.fsum(r["gross_bps"] for r in rows),
        "cost1_total_bps": math.fsum(r["cost_bps"] for r in rows),
        "net1_total_trade_bps": sum1, "net2_total_trade_bps": sum2,
        "net2_bps_per_trade": sum2/len(rows),
        "pf2_modeled": profit/loss if loss else None,
        "net2_winner_count_retention": sum(x>0 for x in net2),
        "top_k_winner_sensitivity_posthoc_not_strategy": removed,
        "exit_order_trade_bps_dd_not_nav": dd,
        "exit_order_loss_streak": longest,
        "by_entry_month_utc": dict(sorted(months.items())),
        "by_symbol": dict(sorted(symbols.items())),
    }


def analyze(source: dict, ssot: dict, src_sha256: str, ssot_sha256: str) -> dict:
    if ssot.get("formal_pass_authority") is not False or ssot.get("g5a_rows_reusable_for_g5b") is not False:
        raise ValueError("FORMAL_G5_AUTHORITY_CHANGED")
    g5 = ssot["lanes"]["Supertrend Momentum"]
    lane = source["lanes"]["supertrend_pullback_main"]
    if (g5.get("boundary_ms") != BOUNDARY
        or g5.get("child_id") != FROZEN_ID
        or lane.get("child_id") != FROZEN_ID):
        raise ValueError("DIFFERENT_SUPERTREND_LINEAGE")
    trades = lane.get("closed_trades", [])
    if len(trades) != COLLECTOR_T or lane.get("closed_T") != COLLECTOR_T:
        raise ValueError("COLLECTOR_T_MISMATCH")
    seen = set()
    for r in trades:
        valid_row(r)
        if r["closed_trade_id"] in seen:
            raise ValueError("DUPLICATE_TRADE_ID")
        seen.add(r["closed_trade_id"])
    post = [r for r in trades
            if r["signal_ts"] >= BOUNDARY and r["entry_ts"] >= BOUNDARY and r["exit_ts"] >= BOUNDARY]
    pre = [r for r in trades if r["entry_ts"] < BOUNDARY]
    if len(post) != G5_FRESH_T or g5.get("fresh_closed_T") != G5_FRESH_T or len(pre) != 13:
        raise ValueError("G5_COHORT_BOUNDARY_OR_COUNT_MISMATCH")
    if any(r["entry_ts"] >= BOUNDARY and r not in post for r in trades):
        raise ValueError("PARTIAL_WINDOW_CENSORED")
    results = summarize(post)
    old = summarize(pre)
    return {
        "schema": "zel.supertrend_g5_momentum.stage1_exact_aftercost_forensic.v1",
        "status": "G5_STAGE1_DIAGNOSTIC_PASS__SOURCE_FEATURE_CAUSAL_CHILD_NOT_AUTHORIZED",
        "strategy_id": FROZEN_ID,
        "source_git_blob": SOURCE_BLOB, "ssot_git_blob": SSOT_BLOB,
        "source_sha256": src_sha256, "ssot_sha256": ssot_sha256,
        "source_total_T": COLLECTOR_T,
        "post_boundary_start_utc": datetime.fromtimestamp(BOUNDARY/1000,timezone.utc).isoformat(),
        "post_boundary": results,
        "pre_boundary_used_context_T": len(pre),
        "pre_boundary_net1": old["net1_total_trade_bps"],
        "pre_boundary_net2": old["net2_total_trade_bps"],
        "integrity_state": g5.get("integrity",{}).get("state"),
        "formal_g5_pass": False,
        "new_candidate_count": 0, "economic_full_runs": 0, "actual_orders": 0,
        "gate": {
            "model_cost_only": True,
            "real_signed_funding_slippage_fills": "NOT_BOUND_TO_ROW",
            "entry_time_source_features_asof": "NOT_IN_THIS_SUMMARY",
            "new_child_test_on_same_26_fresh_trades": "FORBIDDEN_SELECTION_LEAKAGE",
            "required_next": "Recover independent pre-entry OHLC/feature/available_ts and source-exact frozen stop/exit, compare loss vs fat-tail wins on separate development population; freeze one distinct causal axis BEFORE new untouched prospective boundary. G5 source accounting/parity and H4/H5 must stay independent.",
        },
        "limitations": [
            "Recorded trade-bps sum is NOT account NAV or return percentage",
            "Net2=Gross-2x frozen 20bps modeled cost; not observed funding and slippage",
            "Contiguous 26 G5 post-boundary rows are reviewed, not untouched OOS for a new rule",
            "Top winner exclusion and month/symbol results are posthoc stress, not filters",
            "Exit-order trade-bps drawdown is not account MTM/intrabar DD",
            "Old 1h Supertrend Pullback terminated exit family is not this 4h replacement",
        ],
    }


def tests() -> int:
    sample = dict(child_id=FROZEN_ID,side="long",symbol="BTC-USDT",closed_trade_id="t1",
                  signal_ts=0,entry_ts=14400000,exit_ts=28800000,entry_px=100.0,
                  exit_px=102.0,cost_bps=20,gross_bps=200.0,net_bps=180.0)
    valid_row(sample)
    checks=1
    for update in ({"entry_ts":-1},{"net_bps":179.0},{"side":"short"},
                   {"cost_bps":None},{"signal_ts":30000000}):
        bad=dict(sample,**update)
        try: valid_row(bad)
        except ValueError: checks+=1
        else: raise AssertionError("INVALID_ROW_ACCEPTED:"+str(update))
    r=summarize([sample])
    assert r["T"]==1 and r["net2_total_trade_bps"]==160.0 and checks==6
    print(json.dumps({"synthetic_checks":checks+1,"result":"PASS","real_market_calls":0}))
    return 0


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path)
    parser.add_argument("--ssot",type=Path)
    parser.add_argument("--self-test",action="store_true")
    a=parser.parse_args()
    if a.self_test:return tests()
    if not a.source or not a.ssot:parser.error("both pinned source inputs are required")
    source,s_hash=pinned_json(a.source,SOURCE_BLOB)
    ssot,ssot_hash=pinned_json(a.ssot,SSOT_BLOB)
    print(json.dumps(analyze(source,ssot,s_hash,ssot_hash),
                     indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
