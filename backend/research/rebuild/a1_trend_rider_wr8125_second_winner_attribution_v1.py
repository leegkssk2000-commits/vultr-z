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
from backend.research.rebuild.policy_kernel_v1 import atr, ema, f

SCHEMA = "zel.a1.trend_rider.wr8125.second_winner_attribution.v1"
FROZEN_COUNT = 24
EXPECTED_BASE_TRADES = 16
EXPECTED_BASE_WINS = 13
EXPECTED_BASE_WR = 0.8125
EXPECTED_BASE_NET_BPS = 23297.769437281215
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _extra_enrich(receipt: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    interval = str((receipt.get("source") or {}).get("interval") or "1h")
    cfg = parent.TrendRiderTransitionFreshnessConfig()
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, interval, 1000)]
        idx = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
        closes = [f(b, "close") for b in bars]
        trend = ema(closes, cfg.ema_trend_len)
        fast = ema(closes, cfg.ema_fast_len)
        slow = ema(closes, cfg.ema_slow_len)
        for row in [x for x in rows if str(x["symbol"]) == symbol]:
            i = idx.get(int(row["signal_ts"]))
            if i is None or i < 3:
                row["extra_feature_missing"] = True
                continue
            side = str(row["side"])
            sign = 1.0 if side == "long" else -1.0
            a0 = atr(bars[: i + 1], cfg.atr_len)
            a1 = atr(bars[:i], cfg.atr_len)
            a2 = atr(bars[: i - 1], cfg.atr_len)
            slope0 = sign * (trend[i] - trend[i - 1]) / max(a0, 1e-12)
            slope1 = sign * (trend[i - 1] - trend[i - 2]) / max(a1, 1e-12)
            spread0 = abs(fast[i] - slow[i]) / max(a0, 1e-12)
            spread1 = abs(fast[i - 1] - slow[i - 1]) / max(a1, 1e-12)
            body0 = abs(f(bars[i], "close") - f(bars[i], "open")) / max(a0, 1e-12)
            body1 = abs(f(bars[i - 1], "close") - f(bars[i - 1], "open")) / max(a1, 1e-12)
            range0 = (f(bars[i], "high") - f(bars[i], "low")) / max(a0, 1e-12)
            range1 = (f(bars[i - 1], "high") - f(bars[i - 1], "low")) / max(a1, 1e-12)
            vol0 = float(bars[i].get("volume") or 0.0)
            vol1 = float(bars[i - 1].get("volume") or 0.0)
            prog0 = sign * (f(bars[i], "close") - f(bars[i - 1], "close")) / max(a0, 1e-12)
            prog1 = sign * (f(bars[i - 1], "close") - f(bars[i - 2], "close")) / max(a1, 1e-12)
            atr_d0 = a0 - a1
            atr_d1 = a1 - a2
            hi, lo, close = f(bars[i], "high"), f(bars[i], "low"), f(bars[i], "close")
            location = (close - lo) / max(hi - lo, 1e-12)
            side_close_favored = location >= 0.5 if side == "long" else location <= 0.5
            row.update({
                "ema_slope_state": "ACCELERATING_SIDE" if slope0 > slope1 else "DECELERATING_OR_FLAT_SIDE",
                "ema_spread_state": "EXPANDING" if spread0 > spread1 else "COOLING_OR_FLAT",
                "body_state": "EXPANDING" if body0 > body1 else "COOLING_OR_FLAT",
                "range_state": "EXPANDING" if range0 > range1 else "COOLING_OR_FLAT",
                "volume_state": "EXPANDING" if vol0 > vol1 else "COOLING_OR_FLAT",
                "directional_progress_state": "WITH_SIDE" if prog0 > 0 else "AGAINST_OR_FLAT",
                "directional_impulse_state": "ACCELERATING_SIDE" if prog0 > prog1 else "DECELERATING_OR_FLAT_SIDE",
                "atr_accel_state": "ACCELERATING" if atr_d0 > atr_d1 else "DECELERATING_OR_FLAT",
                "side_close_location": "FAVORED_HALF" if side_close_favored else "UNFAVORED_HALF",
                "extra_feature_missing": False,
            })


def run(out: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="trend_wr8125_second_") as td:
        receipt = diag._run_receipt("trend_rider", Path(td) / "trend.json")
    rows = [dict(x) for x in (receipt.get("trades") or [])]
    rows.sort(key=lambda x: (int(x.get("entry_ts") or 0), str(x.get("symbol") or "")))
    if len(rows) < FROZEN_COUNT:
        raise RuntimeError(f"FROZEN_24_UNAVAILABLE:{len(rows)}")
    rows = rows[:FROZEN_COUNT]
    first._enrich(receipt, rows)
    _extra_enrich(receipt, rows)
    if any(bool(x.get("feature_missing")) or bool(x.get("extra_feature_missing")) for x in rows):
        raise RuntimeError("TREND_SECOND_WINNER_FEATURE_MISSING")

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
            "state": "HOLD_WR8125_BASE_AUTHORITY_MISMATCH",
            "base": base_stats,
            "authority_match": False,
            "next": "DO_NOT_SELECT_SECOND_RESTORE_CHILD",
            **AUTH,
        }
        result["receipt_sha256"] = ev.stable_sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    remaining = [x for x in rows if x["session"] == "US" and x["chase_state"] != "COOLING_OR_FLAT"]
    axes = (
        "ema_slope_state", "ema_spread_state", "body_state", "range_state", "volume_state",
        "directional_progress_state", "directional_impulse_state", "atr_accel_state", "side_close_location",
    )
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
                "winner_pnl_bps": sum(float(x["net_bps"]) for x in winners),
                "loser_pnl_bps": sum(float(x["net_bps"]) for x in losers),
                "preentry_only": True,
                "ordinal_only": True,
                "numeric_threshold_sweep": False,
            })
    strict = [c for c in candidates if float(c["candidate"]["win_rate"]) >= EXPECTED_BASE_WR and float(c["candidate"]["net_pnl_bps"]) > EXPECTED_BASE_NET_BPS]
    strict.sort(key=lambda c: (-float(c["candidate"]["net_pnl_bps"]), -float(c["candidate"]["win_rate"]), str(c["axis"]), str(c["value"])))
    recommended = strict[0] if strict else None
    state = "SECOND_STRICT_WR_PRESERVING_WINNER_RESTORE_FOUND" if recommended else "NO_SECOND_STRICT_RESTORE_ON_INDEPENDENT_ORDINAL_AXES"
    compact = [{k: x.get(k) for k in ("symbol", "side", "signal_ts", "net_bps", "chase_state") + axes} for x in remaining]
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "authority_match": True,
        "base_wr8125": base_stats,
        "remaining_us_trade_count": len(remaining),
        "remaining_us_winner_count": sum(1 for x in remaining if float(x.get("net_bps") or 0.0) > 0),
        "remaining_us_loser_count": sum(1 for x in remaining if float(x.get("net_bps") or 0.0) <= 0),
        "discovery_axes": list(axes),
        "candidate_count": len(candidates),
        "strict_candidates": strict,
        "recommended_discovery_child": recommended,
        "remaining_us_attribution": compact,
        "outcome_used_for_discovery_only": True,
        "outcome_used_at_runtime": False,
        "fresh_proof_required": True,
        "numeric_threshold_sweep": False,
        "parent_incumbent_mutated": False,
        "next": f"PREREGISTER_FRESH_SECOND_US_REENABLE:{recommended['axis']}:{recommended['value']}" if recommended else "PRESERVE_WR8125_AND_DO_NOT_OVERFIT",
        **AUTH,
    }
    result["receipt_sha256"] = ev.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    base = first._stats([{"net_bps": 1.0}] * 13 + [{"net_bps": -1.0}] * 3)
    assert base["trades"] == 16 and base["wins"] == 13 and abs(float(base["win_rate"]) - 0.8125) < 1e-12
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_TREND_RIDER_WR8125_SECOND_WINNER_ATTRIBUTION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_wr8125_second_winner_attribution_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({"state": r["state"], "base": r.get("base_wr8125"), "recommended": r.get("recommended_discovery_child"), "next": r["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
