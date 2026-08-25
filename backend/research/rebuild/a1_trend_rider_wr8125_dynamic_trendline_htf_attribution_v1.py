#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as diag
from backend.research.rebuild import a1_trend_rider_wr80_winner_restore_attribution_v1 as first
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as parent
from backend.research.rebuild.policy_kernel_v1 import ema, f

SCHEMA = "zel.a1.trend_rider.wr8125.dynamic_trendline_htf_attribution.v1"
FROZEN_COUNT = 24
EXPECTED_BASE_TRADES = 16
EXPECTED_BASE_WINS = 13
EXPECTED_BASE_WR = 0.8125
EXPECTED_BASE_NET_BPS = 23297.769437281215

# Evaluator-owned structural constants only. No creator numeric threshold import and no outcome sweep.
FAST_HTF_EMA = 48
SLOW_HTF_EMA = 192
TREND_SLOPE_LAG = 4
SWING_WINDOW = 12
SWING_LAG = 6

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _rolling_min(xs: list[float], end: int, n: int) -> float | None:
    start = end - n + 1
    if start < 0 or end < 0 or end >= len(xs):
        return None
    return min(xs[start : end + 1])


def _rolling_max(xs: list[float], end: int, n: int) -> float | None:
    start = end - n + 1
    if start < 0 or end < 0 or end >= len(xs):
        return None
    return max(xs[start : end + 1])


def _structure_states(bars: list[dict[str, Any]], i: int, side: str) -> dict[str, str] | None:
    if i < max(SLOW_HTF_EMA + TREND_SLOPE_LAG, SWING_WINDOW + SWING_LAG):
        return None
    closes = [f(b, "close") for b in bars]
    highs = [f(b, "high") for b in bars]
    lows = [f(b, "low") for b in bars]
    fast = ema(closes, FAST_HTF_EMA)
    slow = ema(closes, SLOW_HTF_EMA)
    sign = 1.0 if side == "long" else -1.0

    htf_aligned = sign * (fast[i] - slow[i]) > 0 and sign * (fast[i] - fast[i - TREND_SLOPE_LAG]) > 0
    price_aligned = sign * (closes[i] - fast[i]) > 0

    cur_support = _rolling_min(lows, i, SWING_WINDOW)
    prev_support = _rolling_min(lows, i - SWING_LAG, SWING_WINDOW)
    cur_resistance = _rolling_max(highs, i, SWING_WINDOW)
    prev_resistance = _rolling_max(highs, i - SWING_LAG, SWING_WINDOW)
    if None in (cur_support, prev_support, cur_resistance, prev_resistance):
        return None

    if side == "long":
        dynamic_ok = float(cur_support) > float(prev_support)
        dynamic_state = "RISING_SUPPORT" if dynamic_ok else "NON_RISING_SUPPORT"
    else:
        dynamic_ok = float(cur_resistance) < float(prev_resistance)
        dynamic_state = "FALLING_RESISTANCE" if dynamic_ok else "NON_FALLING_RESISTANCE"

    return {
        "dynamic_trendline_state": dynamic_state,
        "htf_alignment_state": "ALIGNED" if htf_aligned else "NOT_ALIGNED",
        "price_vs_htf_state": "ALIGNED" if price_aligned else "NOT_ALIGNED",
        "dynamic_htf_combo": "ALIGNED" if dynamic_ok and htf_aligned and price_aligned else "NOT_ALIGNED",
    }


def _enrich(receipt: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    interval = str((receipt.get("source") or {}).get("interval") or "1h")
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, interval, 1000)]
        idx = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
        for row in [x for x in rows if str(x["symbol"]) == symbol]:
            i = idx.get(int(row["signal_ts"]))
            states = None if i is None else _structure_states(bars, i, str(row["side"]))
            if states is None:
                row["dynamic_htf_feature_missing"] = True
                continue
            row.update(states)
            row["dynamic_htf_feature_missing"] = False


def run(out: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="trend_wr8125_dynamic_htf_") as td:
        receipt = diag._run_receipt("trend_rider", Path(td) / "trend.json")
    rows = [dict(x) for x in (receipt.get("trades") or [])]
    rows.sort(key=lambda x: (int(x.get("entry_ts") or 0), str(x.get("symbol") or "")))
    if len(rows) < FROZEN_COUNT:
        raise RuntimeError(f"FROZEN_24_UNAVAILABLE:{len(rows)}")
    rows = rows[:FROZEN_COUNT]
    first._enrich(receipt, rows)
    _enrich(receipt, rows)
    if any(bool(x.get("feature_missing")) or bool(x.get("dynamic_htf_feature_missing")) for x in rows):
        raise RuntimeError("TREND_DYNAMIC_HTF_FEATURE_MISSING")

    # Exact WR81.25 canonical discovery head: non-US plus US chase-cooling/flat only.
    base = [x for x in rows if x["session"] != "US" or x["chase_state"] == "COOLING_OR_FLAT"]
    base_stats = first._stats(base)
    authority_ok = (
        int(base_stats["trades"]) == EXPECTED_BASE_TRADES
        and int(base_stats["wins"]) == EXPECTED_BASE_WINS
        and abs(float(base_stats["win_rate"]) - EXPECTED_BASE_WR) <= 1e-12
        and abs(float(base_stats["net_pnl_bps"]) - EXPECTED_BASE_NET_BPS) <= 0.05
    )
    if not authority_ok:
        result = {
            "schema_version": SCHEMA,
            "state": "HOLD_WR8125_CANONICAL_AUTHORITY_MISMATCH",
            "strategy_id": "trend_rider",
            "base_wr8125": base_stats,
            "authority_match": False,
            "next": "DO_NOT_RUN_DYNAMIC_TRENDLINE_HTF_ABLATION",
            **AUTH,
        }
        result["receipt_sha256"] = ev.stable_sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    remaining = [x for x in rows if x["session"] == "US" and x["chase_state"] != "COOLING_OR_FLAT"]
    axes = ("dynamic_trendline_state", "htf_alignment_state", "price_vs_htf_state", "dynamic_htf_combo")
    candidates: list[dict[str, Any]] = []
    for axis in axes:
        for value in sorted({str(x.get(axis)) for x in remaining}):
            selected = [x for x in remaining if str(x.get(axis)) == value]
            stats = first._stats(base + selected)
            winners = [x for x in selected if float(x.get("net_bps") or 0.0) > 0]
            losers = [x for x in selected if float(x.get("net_bps") or 0.0) <= 0]
            candidates.append({
                "axis": axis,
                "value": value,
                "candidate": stats,
                "delta_wr": float(stats["win_rate"]) - float(base_stats["win_rate"]),
                "delta_net_pnl_bps": float(stats["net_pnl_bps"]) - float(base_stats["net_pnl_bps"]),
                "remaining_us_selected": len(selected),
                "winner_reintroduced": len(winners),
                "loser_reintroduced": len(losers),
                "preentry_only": True,
                "ordinal_only": True,
                "numeric_threshold_sweep": False,
                "creator_numeric_threshold_imported": False,
                "creator_performance_claim_imported": False,
            })

    strict = [
        c for c in candidates
        if c["winner_reintroduced"] >= 1
        and c["loser_reintroduced"] == 0
        and float(c["candidate"]["win_rate"]) >= EXPECTED_BASE_WR
        and float(c["candidate"]["net_pnl_bps"]) > EXPECTED_BASE_NET_BPS
    ]
    strict.sort(key=lambda c: (-float(c["candidate"]["net_pnl_bps"]), -float(c["candidate"]["win_rate"]), str(c["axis"]), str(c["value"])))
    recommended = strict[0] if strict else None
    state = "DYNAMIC_TRENDLINE_HTF_STRICT_RESTORE_FOUND" if recommended else "NO_STRICT_DYNAMIC_TRENDLINE_HTF_RESTORE"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "canonical_head": "trend_rider_wr80_us_chase_cooling_v1",
        "authority_match": True,
        "base_wr8125": base_stats,
        "remaining_us_trade_count": len(remaining),
        "axes": list(axes),
        "candidate_count": len(candidates),
        "strict_candidate_count": len(strict),
        "recommended_discovery_child": recommended,
        "candidates": candidates,
        "evaluator_constants": {
            "fast_htf_ema": FAST_HTF_EMA,
            "slow_htf_ema": SLOW_HTF_EMA,
            "trend_slope_lag": TREND_SLOPE_LAG,
            "swing_window": SWING_WINDOW,
            "swing_lag": SWING_LAG,
        },
        "parameter_provenance": "evaluator-owned structural constants; no creator numeric threshold import; no outcome threshold sweep",
        "named_channel_mechanism_class": "DYNAMIC_TRENDLINE_AND_HTF_STRUCTURE",
        "development_only": True,
        "fresh_oos_required": True,
        "outcome_used_for_discovery_only": True,
        "outcome_used_at_runtime": False,
        "parent_incumbent_mutated": False,
        "numeric_threshold_sweep": False,
        "creator_numeric_threshold_imported": False,
        "creator_performance_claim_imported": False,
        "next": "PREREGISTER_RECOMMENDED_CHILD_THEN_FRESH_OOS" if recommended else "TRY_NEXT_NAMED_CHANNEL_STRUCTURAL_AXIS",
        **AUTH,
    }
    result["receipt_sha256"] = ev.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    bars: list[dict[str, Any]] = []
    for i in range(240):
        px = 100.0 + 0.2 * i
        bars.append({"ts_ms": i * 3600000, "open": px - 0.05, "high": px + 0.2, "low": px - 0.2, "close": px, "volume": 1000.0 + i})
    x = _structure_states(bars, 230, "long")
    assert x is not None
    assert x["dynamic_trendline_state"] == "RISING_SUPPORT"
    assert x["htf_alignment_state"] == "ALIGNED"
    assert x["price_vs_htf_state"] == "ALIGNED"
    assert x["dynamic_htf_combo"] == "ALIGNED"
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_WR8125_DYNAMIC_TRENDLINE_HTF_ATTRIBUTION_V1")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_wr8125_dynamic_trendline_htf_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result.get("state"),
        "authority_match": result.get("authority_match"),
        "strict_candidate_count": result.get("strict_candidate_count"),
        "recommended": result.get("recommended_discovery_child"),
        "receipt": result.get("receipt_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())