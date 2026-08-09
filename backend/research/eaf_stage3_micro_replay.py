#!/usr/bin/env python3
"""Isolated EAF Stage3 structural micro-replay.

Scope:
- validates canonical 15m OHLCV snapshots and manifest hashes;
- replays only the three Stage3 BASE candidates;
- uses closed-bar signals and next-bar-open fills;
- contains no tunable numeric indicator thresholds;
- reports gross structural diagnostics only until a sourced SSOT cost model exists.

It does not import, mutate, or route through the Structural Premium V2 engine.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

BAR_MS = 15 * 60 * 1000
REQ = ("timestamp_ms", "open", "high", "low", "close", "volume")
STRATEGIES = ("EAF_TM_V1", "EAF_VB_V1", "EAF_RMR_V1")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(path: Path) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    duplicate = 0
    gap_count = 0
    seen: set[int] = set()
    last = None
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if tuple(r.fieldnames or ()) != REQ:
            raise SystemExit(f"BAD_SCHEMA:{path}:{r.fieldnames}")
        for line, x in enumerate(r, 2):
            if any(x.get(k, "") == "" for k in REQ):
                raise SystemExit(f"MISSING_FIELD:{path}:{line}")
            try:
                ts = int(x["timestamp_ms"])
                o, h, l, c, v = (float(x[k]) for k in REQ[1:])
            except Exception as exc:
                raise SystemExit(f"BAD_ROW:{path}:{line}:{exc}")
            vals = (o, h, l, c, v)
            if not all(math.isfinite(z) for z in vals):
                raise SystemExit(f"NONFINITE:{path}:{line}")
            if ts in seen:
                duplicate += 1
            if last is not None:
                if ts <= last:
                    raise SystemExit(f"NON_MONOTONIC:{path}:{line}")
                if ts - last != BAR_MS:
                    gap_count += 1
            if not (h >= max(o, c, l) and l <= min(o, c, h)):
                raise SystemExit(f"BAD_OHLC:{path}:{line}")
            if v < 0:
                raise SystemExit(f"BAD_VOLUME:{path}:{line}")
            seen.add(ts); last = ts
            rows.append({"timestamp_ms": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})
    if not rows:
        raise SystemExit(f"EMPTY:{path}")
    integrity = {
        "rows": len(rows),
        "first_timestamp_ms": rows[0]["timestamp_ms"],
        "last_timestamp_ms": rows[-1]["timestamp_ms"],
        "duplicate_timestamps": duplicate,
        "gap_count": gap_count,
        "sha256": sha256(path),
        "state": "PASS" if duplicate == 0 and gap_count == 0 else "HOLD",
    }
    return rows, integrity


def hour_bars(rows: list[dict]) -> tuple[list[dict], dict[int, int]]:
    groups: dict[int, list[dict]] = {}
    for x in rows:
        key = x["timestamp_ms"] // (60 * 60 * 1000)
        groups.setdefault(key, []).append(x)
    complete = []
    for key in sorted(groups):
        g = groups[key]
        if len(g) != 4:
            continue
        complete.append({
            "hour_key": key,
            "open": g[0]["open"], "high": max(z["high"] for z in g),
            "low": min(z["low"] for z in g), "close": g[-1]["close"],
            "first_ts": g[0]["timestamp_ms"], "last_ts": g[-1]["timestamp_ms"],
        })
    idx = {x["hour_key"]: i for i, x in enumerate(complete)}
    return complete, idx


def prior_hours(ts: int, hb: list[dict], hidx: dict[int, int]) -> tuple[dict | None, dict | None]:
    current_key = ts // (60 * 60 * 1000)
    prior_keys = [k for k in hidx if k < current_key]
    if not prior_keys:
        return None, None
    k1 = max(prior_keys); i = hidx[k1]
    h1 = hb[i]
    h2 = hb[i - 1] if i > 0 else None
    return h1, h2


def tm_signal(rows: list[dict], i: int, ctx: dict) -> tuple[bool, bool, dict]:
    if i < 2:
        return False, False, {}
    cur, prev = rows[i], rows[i - 1]
    h1, _ = prior_hours(cur["timestamp_ms"], ctx["hour_bars"], ctx["hour_idx"])
    if not h1:
        return False, False, {}
    htf_positive = h1["close"] > h1["open"]
    controlled_retracement = prev["close"] < prev["open"] and prev["low"] > h1["low"]
    resumption = cur["close"] > prev["high"] and cur["close"] > cur["open"]
    enter = htf_positive and controlled_retracement and resumption
    exit_ = (not htf_positive) or cur["close"] < prev["low"]
    return enter, exit_, {"htf_hour_key": h1["hour_key"]}


def vb_signal(rows: list[dict], i: int, ctx: dict) -> tuple[bool, bool, dict]:
    if i < 1:
        return False, False, {}
    cur, prev = rows[i], rows[i - 1]
    h1, _ = prior_hours(cur["timestamp_ms"], ctx["hour_bars"], ctx["hour_idx"])
    if not h1:
        return False, False, {}
    tr = cur["high"] - cur["low"]
    ptr = prev["high"] - prev["low"]
    enter = cur["close"] > h1["high"] and tr > ptr
    exit_ = cur["close"] < h1["low"]
    return enter, exit_, {"breakout_boundary": h1["high"], "opposite_boundary": h1["low"]}


def rmr_signal(rows: list[dict], i: int, ctx: dict) -> tuple[bool, bool, dict]:
    cur = rows[i]
    h1, h2 = prior_hours(cur["timestamp_ms"], ctx["hour_bars"], ctx["hour_idx"])
    if not h1 or not h2:
        return False, False, {}
    nontrend_inside = h1["high"] <= h2["high"] and h1["low"] >= h2["low"]
    boundary_reclaim = cur["low"] < h1["low"] and cur["close"] > h1["low"] and cur["close"] > cur["open"]
    enter = nontrend_inside and boundary_reclaim
    # Position-specific target/invalidation are evaluated by replay() using entry metadata.
    return enter, False, {"lower_boundary": h1["low"], "range_reference": (h1["high"] + h1["low"]) / 2.0}


@dataclass
class Position:
    entry_i: int
    entry_ts: int
    entry_price: float
    meta: dict


def replay(rows: list[dict], strategy: str) -> dict:
    hb, hidx = hour_bars(rows)
    ctx = {"hour_bars": hb, "hour_idx": hidx}
    fn: Callable = {"EAF_TM_V1": tm_signal, "EAF_VB_V1": vb_signal, "EAF_RMR_V1": rmr_signal}[strategy]
    pos: Position | None = None
    pending_entry: dict | None = None
    pending_exit = False
    trades = []
    exposure_bars = 0
    signals = 0

    for i, bar in enumerate(rows):
        # Orders created from the previous closed bar are filled at THIS bar open.
        if pending_exit and pos is not None:
            ret = bar["open"] / pos.entry_price - 1.0
            trades.append({"entry_ts": pos.entry_ts, "exit_ts": bar["timestamp_ms"], "entry": pos.entry_price, "exit": bar["open"], "gross_return": ret, "bars_held": i - pos.entry_i})
            pos = None
            pending_exit = False
        if pending_entry is not None and pos is None:
            pos = Position(i, bar["timestamp_ms"], bar["open"], pending_entry)
            pending_entry = None
        if pos is not None:
            exposure_bars += 1

        enter, exit_, meta = fn(rows, i, ctx)
        if strategy == "EAF_RMR_V1" and pos is not None:
            exit_ = bar["close"] >= pos.meta["range_reference"] or bar["close"] < pos.meta["lower_boundary"]
        if pos is not None and exit_ and i + 1 < len(rows):
            pending_exit = True
        elif pos is None and enter and i + 1 < len(rows):
            pending_entry = meta
            signals += 1

    rets = [t["gross_return"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (None if not gross_profit else "INF")
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        equity *= 1.0 + r
        peak = max(peak, equity)
        max_dd = max(max_dd, 1.0 - equity / peak)
    return {
        "strategy": strategy,
        "side": "LONG_ONLY_STAGE3_BASE",
        "signal_count": signals,
        "closed_trades": len(trades),
        "open_position_at_end": pos is not None,
        "gross_win_rate": (len(wins) / len(rets)) if rets else None,
        "gross_compound_return": equity - 1.0 if rets else 0.0,
        "gross_expectancy_per_trade": (sum(rets) / len(rets)) if rets else None,
        "gross_profit_factor": pf,
        "realized_max_drawdown": max_dd,
        "turnover_round_trips": len(trades),
        "exposure_fraction": exposure_bars / len(rows),
        "economic_metrics_valid": False,
        "net_return": None,
        "net_expectancy": None,
        "net_profit_factor": None,
        "reason_net_blocked": "SSOT all-in fee/slippage/funding cost model not found in repository; costs are mandatory before economic verdict",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ns = ap.parse_args()
    manifest = json.loads(ns.manifest.read_text(encoding="utf-8"))
    expected = {x["symbol"]: x for x in manifest["symbols"]}
    all_results = []
    integrity = {}
    for symbol in sorted(expected):
        path = ns.data_dir / f"{symbol}.csv"
        rows, integ = load_csv(path)
        exp = expected[symbol]
        integ["manifest_rows_match"] = len(rows) == exp["rows"]
        integ["manifest_sha_match"] = integ["sha256"] == exp["market_sha256"]
        integ["manifest_range_match"] = rows[0]["timestamp_ms"] == exp["first_timestamp_ms"] and rows[-1]["timestamp_ms"] == exp["last_timestamp_ms"]
        if not (integ["state"] == "PASS" and integ["manifest_rows_match"] and integ["manifest_sha_match"] and integ["manifest_range_match"]):
            raise SystemExit(f"DATA_INTEGRITY_HOLD:{symbol}:{json.dumps(integ, sort_keys=True)}")
        integrity[symbol] = integ
        for strategy in STRATEGIES:
            r = replay(rows, strategy); r["symbol"] = symbol; all_results.append(r)

    receipt = {
        "schema_version": "zel.eaf.stage3.micro_replay.v1",
        "state": "PASS_STAGE3_ADAPTER_STRUCTURAL_SMOKE_HOLD_ECONOMICS",
        "research_only": True,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "selection_authority": False,
        "promotion_authority": False,
        "stage3_unlocked": False,
        "baseline_engine_mutated": False,
        "dataset": {
            "ref": "strategy11-data-stream-v1",
            "source": "BingX USDT-M 15m collector snapshot",
            "symbols": sorted(expected),
            "manifest_state": manifest.get("state"),
            "available_non_overlap_bars": manifest.get("available_non_overlap_bars"),
            "first_evaluation_ms": manifest.get("first_evaluation_ms"),
            "latest_closed_end_ms": manifest.get("latest_closed_end_ms"),
        },
        "integrity": integrity,
        "fill_contract": {"signal": "closed_bar_t", "fill": "open_t_plus_1", "same_bar_fill": False},
        "base_contract": {
            "candidates": list(STRATEGIES),
            "side": "LONG_ONLY_STAGE3_BASE",
            "numeric_indicator_thresholds": 0,
            "indicator_additions": 0,
            "session_clock_enabled": False,
            "rule_provenance": "Stage2 structural BASE semantics only; no tunable numeric threshold or parameter selection",
        },
        "cost_model": {
            "state": "HOLD_MISSING_SSOT_COST_MODEL",
            "fee_bps": None,
            "slippage_bps": None,
            "funding_application": None,
            "economic_verdict_allowed": False,
        },
        "results": all_results,
        "survivor_selection_performed": False,
        "micro_smoke_is_survivor_proof": False,
        "next": "bind sourced SSOT all-in fee/slippage/funding model and minimum effective sample; rerun identical BASE rules before any ablation",
    }
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))

if __name__ == "__main__":
    main()
