#!/usr/bin/env python3
"""K117/Squeeze saved-DEV timestamp-only occupancy diagnostic; never an economic replay.

The original outcome-based EXIT times are held constant solely to inspect
contention. Thus this is NOT executable portfolio evidence, NAV, or PnL.
"""
from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

K_SHA = "7cba96a0627dbec42459f344a6e8e7dd70d97f87d71dfb573e10975153d7d0a7"
S_SHA = "354c44a6004888ae69a37d2f3e51672e9e8ab05424e30b5797c61427807ac3f6"
K_ID = "scalp7_k126_veto_objective_completed_fresh_touch_v1"
S_ID = "scalp7_squeeze_panic_plus_trend_disperse_utc30m_v1"


def read_pinned(path: Path, sha256: str) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("SOURCE_BYTES_CHANGED")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("SOURCE_NOT_OBJECT")
    return value


def prepare(data: list[dict], lane: str) -> list[dict]:
    result = []
    for source in data:
        if not isinstance(source, dict):
            raise ValueError("BAD_TRADE")
        if lane == "K":
            if source.get("management_comparison_identity") != K_ID:
                raise ValueError("NOT_FROZEN_K117")
        elif source.get("identity") != S_ID:
            raise ValueError("NOT_SAVED_SQUEEZE_OVERLAY")
        if source.get("timeframe_min") != 30:
            raise ValueError("WRONG_TIMEFRAME")
        sym = source.get("symbol")
        side = source.get("side")
        e, x = source.get("entry_ts_ms"), source.get("exit_ts_ms")
        if (not isinstance(sym, str) or not sym.endswith("-USDT")
            or type(side) is not int or side not in (-1, 1)
            or type(e) is not int or type(x) is not int
            or e < 0 or x <= e or e % 60000 or x % 60000):
            raise ValueError("BAD_BAR_OR_POSITION")
        result.append(dict(lane=lane, symbol=sym, side=side, entry=e, exit=x))
    return result


def intersect(a: dict, b: dict) -> bool:
    return max(a["entry"], b["entry"]) < min(a["exit"], b["exit"])


def peak_concurrency(rows: list[dict]) -> dict:
    calendar = collections.defaultdict(lambda: {"enter": [], "exit": []})
    for n, row in enumerate(rows):
        calendar[row["entry"]]["enter"].append(n)
        calendar[row["exit"]]["exit"].append(n)
    active = set()
    peak = 0
    peak_ts = []
    duration_by_concurrency_ms = collections.Counter()
    last = None
    for when in sorted(calendar):
        if last is not None:
            duration_by_concurrency_ms[len(active)] += when - last
        # Half-open interval: exit at T no longer occupies the T entry.
        for n in calendar[when]["exit"]:
            if n not in active:
                raise ValueError("CLOSE_WITHOUT_OPEN")
            active.remove(n)
        active.update(calendar[when]["enter"])
        if len(active) > peak:
            peak = len(active)
            peak_ts = [when]
        elif len(active) == peak:
            peak_ts.append(when)
        last = when
    if active:
        raise ValueError("UNRESOLVED_SOURCE_INTERVAL")
    return {
        "peak_static_open_count": peak,
        "first_peak_utc": datetime.fromtimestamp(peak_ts[0] / 1000, timezone.utc).isoformat() if peak_ts else None,
        "hours_with_two_or_more_static_positions": round(
            sum(ms for count, ms in duration_by_concurrency_ms.items() if count >= 2) / 3600000, 3),
    }


def admission(rows: list[dict], max_positions: int, same_symbol_limit: bool, priority: str) -> dict:
    if type(max_positions) is not int or max_positions < 1 or priority not in ("K", "S"):
        raise ValueError("BAD_SCENARIO")
    # This does not make or resimulate any trade: only fixed original intervals.
    ordered = sorted(rows, key=lambda r: (r["entry"], r["lane"] != priority, r["symbol"], r["side"]))
    active: list[dict] = []
    admitted = []
    rejection = collections.Counter()
    for candidate in ordered:
        active = [a for a in active if a["exit"] > candidate["entry"]]
        if len(active) >= max_positions:
            rejection["global_capacity"] += 1
            continue
        if same_symbol_limit and any(a["symbol"] == candidate["symbol"] for a in active):
            rejection["same_symbol"] += 1
            continue
        active.append(candidate)
        admitted.append(candidate)
    by_lane = collections.Counter(r["lane"] for r in admitted)
    return {
        "max_simultaneous_positions_assumption": max_positions,
        "one_open_per_symbol_assumption": same_symbol_limit,
        "same_bar_tie_priority_assumption": priority,
        "admitted_K": by_lane["K"], "admitted_S": by_lane["S"],
        "admitted_total": len(admitted),
        "rejected_total": len(rows) - len(admitted),
        "rejection_reasons": dict(rejection),
        "historical_245_day_admission_density": round(len(admitted) / 245, 6),
        "cash_or_NAV_simulated": False,
    }


def compare(k: list[dict], s: list[dict]) -> dict:
    unique = [(r["symbol"], r["side"], r["entry"]) for r in k + s]
    kset = set((r["symbol"], r["side"], r["entry"]) for r in k)
    sset = set((r["symbol"], r["side"], r["entry"]) for r in s)
    if len(set(unique)) != len(unique):
        raise ValueError("SAME_SOURCE_EVENT_KEY_DUPLICATED")
    matched = [(a, b) for a in k for b in s if intersect(a, b)]
    result = {
        "classification": "FROZEN_USED_DEV_STATIC_CAPACITY_DIAGNOSTIC_ONLY",
        "frozen_source_SHA256": {"K117_ROWS": K_SHA, "SQUEEZE_OLD_OVERLAY57": S_SHA},
        "not_new_signal_low_FULL": True,
        "source_trades": {"K": len(k), "S": len(s), "total": len(k) + len(s)},
        "exact_cross_lane_event_duplicates": len(kset & sset),
        "cross_lane_interval_overlap_pairs": len(matched),
        "same_symbol_side_overlap_pairs": sum(
            a["symbol"] == b["symbol"] and a["side"] == b["side"] for a, b in matched),
        "peak_source_independent_scenario": peak_concurrency(k + s),
        "historical_scenario_only": [
            admission(k + s, cap, one_symbol, priority)
            for cap in (1, 2, 4, 8)
            for one_symbol in (False, True)
            for priority in ("K", "S")
        ],
        "limitations": [
            "Historical exit bar times are frozen; blocked-trade opportunity reallocation not replayed.",
            "Scenario caps are illustrative assumptions, NOT authorized account limits.",
            "The 57 S trades are PREDECESSOR overlay, NOT the unrun signal-low successor.",
            "No funding, slippage, account NAV, actual fill, shared capital or economic PnL measured.",
            "The admission counts cannot establish true executable opportunities or strategy independence.",
        ],
        "economic_FULL": 0, "market_API": 0, "order_calls": 0,
    }
    return result


def tests() -> int:
    def row(lane: str, symbol: str, start: int, end: int) -> dict:
        return dict(lane=lane, symbol=symbol, side=1, entry=start, exit=end)
    k = [row("K", "BTC-USDT", 0, 600000)]
    s = [row("S", "BTC-USDT", 120000, 480000)]
    assert intersect(k[0], s[0])
    assert compare(k, s)["cross_lane_interval_overlap_pairs"] == 1
    assert compare(k, s)["same_symbol_side_overlap_pairs"] == 1
    assert admission(k + s, 1, False, "K")["admitted_total"] == 1
    assert admission(k + s, 2, False, "K")["admitted_total"] == 2
    assert admission(k + s, 2, True, "K")["admitted_total"] == 1
    assert peak_concurrency(k + s)["peak_static_open_count"] == 2
    assert not intersect(k[0], row("S", "BTC-USDT", 600000, 1200000))
    try:
        prepare([dict(lane="K",symbol="BTC-USDT",side=1,entry_ts_ms=10,exit_ts_ms=5,
                      timeframe_min=30,management_comparison_identity=K_ID)], "K")
    except ValueError:
        pass
    else:
        raise AssertionError("noncausal timestamp not rejected")
    print(json.dumps({"synthetic_checks": 8, "result": "PASS"}))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--k-file", type=Path)
    p.add_argument("--s-file", type=Path)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return tests()
    if not args.k_file or not args.s_file:
        p.error("both immutable source inputs required")
    kdoc = read_pinned(args.k_file, K_SHA)
    sdoc = read_pinned(args.s_file, S_SHA)
    if sdoc.get("child_identity") != S_ID or sdoc.get("used_dev_only") is not True:
        raise ValueError("S_SOURCE_CONTRACT_MISMATCH")
    k = prepare(kdoc["trades"], "K")
    s = prepare(sdoc["trade_rows"], "S")
    if len(k) != 117 or len(s) != 57:
        raise ValueError("WRONG_TRADE_COHORT")
    print(json.dumps(compare(k, s), indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
