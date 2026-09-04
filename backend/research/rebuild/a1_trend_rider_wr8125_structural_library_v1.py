#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_frozen24_source_v1.json"
EXACT_PARENT = ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_exact_parent_v1.json"
SCHEMA = "zel.a1.trend_rider.wr8125.structural_library.v1"
EXPECTED_SOURCE_RECEIPT = "3e0f087a1b5536f0eb95532d5289dbee0171c1806805261c129838608534bec5"
BASE_T = 16
BASE_WINS = 13
BASE_WR = 0.8125
BASE_NET_BPS = 23297.769437281215
BASE_EXP_BPS = 1456.110589830076

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}

LIBRARY = [
    "EMA_STACK_SLOPE_9_21_55",
    "DONCHIAN_BREAKOUT_20",
    "PRIOR_RANGE_RECLAIM",
    "RSI50_RECLAIM_14",
    "VOLUME_MEDIAN20_EXPANSION",
    "ATR_COMPRESSION_EXPANSION_14_20",
    "EMA21_RECLAIM",
    "SWING_SEQUENCE_3",
    "MACD_ZERO_CROSS_12_26",
    "UTC_DAY_VWAP_SIDE",
]


def read_json(path: Path) -> dict[str, Any]:
    v = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def ema(values: list[float], period: int) -> list[float | None]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out: list[float | None] = [None] * len(values)
    acc = values[0]
    for i, x in enumerate(values):
        acc = x if i == 0 else alpha * x + (1.0 - alpha) * acc
        if i >= period - 1:
            out[i] = acc
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [0.0] * len(values)
    losses = [0.0] * len(values)
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains[i] = max(d, 0.0)
        losses[i] = max(-d, 0.0)
    avg_g = sum(gains[1:period + 1]) / period
    avg_l = sum(losses[1:period + 1]) / period
    for i in range(period, len(values)):
        if i > period:
            avg_g = (avg_g * (period - 1) + gains[i]) / period
            avg_l = (avg_l * (period - 1) + losses[i]) / period
        if avg_l == 0:
            out[i] = 100.0 if avg_g > 0 else 50.0
        else:
            rs = avg_g / avg_l
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def atr(bars: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    trs: list[float] = []
    for i, b in enumerate(bars):
        h, l = float(b["high"]), float(b["low"])
        if i == 0:
            tr = h - l
        else:
            pc = float(bars[i - 1]["close"])
            tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return ema(trs, period)


def direction_true(side: str, lhs: float, rhs: float, *, greater_for_long: bool = True) -> bool:
    if side == "long":
        return lhs > rhs if greater_for_long else lhs < rhs
    return lhs < rhs if greater_for_long else lhs > rhs


def feature_state(name: str, bars: list[dict[str, Any]], i: int, side: str) -> bool | None:
    if i < 60:
        return None
    closes = [float(b["close"]) for b in bars[: i + 1]]
    opens = [float(b["open"]) for b in bars[: i + 1]]
    highs = [float(b["high"]) for b in bars[: i + 1]]
    lows = [float(b["low"]) for b in bars[: i + 1]]
    vols = [float(b.get("volume") or 0.0) for b in bars[: i + 1]]

    if name == "EMA_STACK_SLOPE_9_21_55":
        e9, e21, e55 = ema(closes, 9), ema(closes, 21), ema(closes, 55)
        if None in (e9[i], e21[i], e55[i], e9[i - 1], e21[i - 1], e55[i - 1]):
            return None
        if side == "long":
            return bool(e9[i] > e21[i] > e55[i] and e9[i] > e9[i - 1] and e21[i] >= e21[i - 1])
        return bool(e9[i] < e21[i] < e55[i] and e9[i] < e9[i - 1] and e21[i] <= e21[i - 1])

    if name == "DONCHIAN_BREAKOUT_20":
        prior_hi = max(highs[i - 20:i])
        prior_lo = min(lows[i - 20:i])
        return closes[i] > prior_hi if side == "long" else closes[i] < prior_lo

    if name == "PRIOR_RANGE_RECLAIM":
        if side == "long":
            return lows[i] <= highs[i - 1] and closes[i] > highs[i - 1]
        return highs[i] >= lows[i - 1] and closes[i] < lows[i - 1]

    if name == "RSI50_RECLAIM_14":
        rs = rsi(closes, 14)
        if rs[i] is None or rs[i - 1] is None:
            return None
        if side == "long":
            return rs[i - 1] <= 50.0 < rs[i]
        return rs[i - 1] >= 50.0 > rs[i]

    if name == "VOLUME_MEDIAN20_EXPANSION":
        med = statistics.median(vols[i - 20:i])
        directional = closes[i] > opens[i] if side == "long" else closes[i] < opens[i]
        return vols[i] > med and directional

    if name == "ATR_COMPRESSION_EXPANSION_14_20":
        at = atr(bars[: i + 1], 14)
        if at[i] is None or at[i - 1] is None:
            return None
        prior_vals = [x for x in at[max(0, i - 21):i - 1] if x is not None]
        if len(prior_vals) < 10:
            return None
        prior_med = statistics.median(prior_vals)
        tr_now = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        directional = closes[i] > opens[i] if side == "long" else closes[i] < opens[i]
        return bool(at[i - 1] < prior_med and tr_now > at[i] and directional)

    if name == "EMA21_RECLAIM":
        e21 = ema(closes, 21)
        if e21[i] is None or e21[i - 1] is None:
            return None
        if side == "long":
            return closes[i - 1] <= e21[i - 1] and closes[i] > e21[i]
        return closes[i - 1] >= e21[i - 1] and closes[i] < e21[i]

    if name == "SWING_SEQUENCE_3":
        if side == "long":
            return lows[i] > lows[i - 1] > lows[i - 2] and closes[i] > opens[i]
        return highs[i] < highs[i - 1] < highs[i - 2] and closes[i] < opens[i]

    if name == "MACD_ZERO_CROSS_12_26":
        e12, e26 = ema(closes, 12), ema(closes, 26)
        if None in (e12[i], e26[i], e12[i - 1], e26[i - 1]):
            return None
        prev = float(e12[i - 1]) - float(e26[i - 1])
        cur = float(e12[i]) - float(e26[i])
        return prev <= 0.0 < cur if side == "long" else prev >= 0.0 > cur

    if name == "UTC_DAY_VWAP_SIDE":
        ts = int(bars[i]["ts_ms"])
        day = ts // 86_400_000
        js = i
        while js > 0 and int(bars[js - 1]["ts_ms"]) // 86_400_000 == day:
            js -= 1
        num = 0.0
        den = 0.0
        for b in bars[js:i + 1]:
            v = float(b.get("volume") or 0.0)
            typ = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
            num += typ * v
            den += v
        if den <= 0:
            return None
        vwap = num / den
        directional = closes[i] > opens[i] if side == "long" else closes[i] < opens[i]
        return (closes[i] > vwap if side == "long" else closes[i] < vwap) and directional

    raise KeyError(name)


def authority_check(source: dict[str, Any], exact: dict[str, Any]) -> list[str]:
    defects: list[str] = []
    if source.get("source_receipt_sha256") != EXPECTED_SOURCE_RECEIPT:
        defects.append("SOURCE_RECEIPT_SHA")
    if source.get("historical_union_allowed") is not False:
        defects.append("HISTORICAL_UNION")
    sm = source.get("wr8125_discovery_child") or {}
    em = exact.get("metrics") or {}
    if int(sm.get("trades") or -1) != BASE_T or int(sm.get("wins") or -1) != BASE_WINS:
        defects.append("SOURCE_BASE_COUNT")
    if abs(float(sm.get("net_pnl_bps") or 0.0) - BASE_NET_BPS) > 0.05:
        defects.append("SOURCE_BASE_NET")
    if int(em.get("completed_trades") or -1) != BASE_T or int(em.get("wins") or -1) != BASE_WINS:
        defects.append("EXACT_BASE_COUNT")
    if abs(float(em.get("net_pnl_bps") or 0.0) - BASE_NET_BPS) > 0.05:
        defects.append("EXACT_BASE_NET")
    return defects


def candidate_stats(selected: list[dict[str, Any]]) -> dict[str, Any]:
    wins_add = sum(1 for x in selected if float(x["net_bps"]) > 0)
    t = BASE_T + len(selected)
    wins = BASE_WINS + wins_add
    net = BASE_NET_BPS + sum(float(x["net_bps"]) for x in selected)
    return {
        "trades": t,
        "wins": wins,
        "win_rate": wins / t,
        "net_pnl_bps": net,
        "net_expectancy_bps": net / t,
        "winner_reintroduced": wins_add,
        "loser_reintroduced": len(selected) - wins_add,
    }


def run(out: Path) -> dict[str, Any]:
    source = read_json(SOURCE)
    exact = read_json(EXACT_PARENT)
    defects = authority_check(source, exact)
    if defects:
        result = {"schema_version": SCHEMA, "state": "HARD_HOLD_AUTHORITY_MISMATCH", "defects": defects, **AUTH}
        result["receipt_sha256"] = ev.stable_sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result

    restored = (source.get("identity_authority") or {}).get("reintroduced_us_trade") or {}
    rows = [dict(x) for x in (source.get("us_trade_attribution") or [])]
    remaining = [x for x in rows if not (x.get("symbol") == restored.get("symbol") and x.get("signal_ts") == restored.get("signal_ts") and x.get("side") == restored.get("side"))]

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for symbol in sorted({str(x["symbol"]) for x in remaining}):
        by_symbol[symbol] = [dict(b) for b in ev.fetch_bars(symbol, "1h", 1000)]

    states: dict[str, dict[str, bool | None]] = {}
    missing: list[dict[str, Any]] = []
    for row in remaining:
        symbol = str(row["symbol"])
        bars = by_symbol[symbol]
        idx = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
        i = idx.get(int(row["signal_ts"]))
        ident = f"{symbol}|{row['side']}|{row['signal_ts']}"
        if i is None:
            missing.append({"identity": ident, "reason": "SIGNAL_BAR_NOT_VISIBLE"})
            continue
        states[ident] = {name: feature_state(name, bars, i, str(row["side"])) for name in LIBRARY}

    candidates: list[dict[str, Any]] = []
    for name in LIBRARY:
        selected = []
        unavailable = []
        for row in remaining:
            ident = f"{row['symbol']}|{row['side']}|{row['signal_ts']}"
            state = (states.get(ident) or {}).get(name)
            if state is None:
                unavailable.append(ident)
            elif state:
                selected.append(row)
        stats = candidate_stats(selected)
        strict = (
            not unavailable
            and stats["winner_reintroduced"] >= 1
            and stats["loser_reintroduced"] == 0
            and stats["win_rate"] >= BASE_WR
            and stats["net_pnl_bps"] > BASE_NET_BPS
            and stats["net_expectancy_bps"] >= BASE_EXP_BPS
        )
        candidates.append({
            "axis": name,
            "selected_T": len(selected),
            "selected_identities": [f"{x['symbol']}|{x['side']}|{x['signal_ts']}" for x in selected],
            "unavailable_identities": unavailable,
            "metrics": stats,
            "strict_discovery_pass": strict,
            "preentry_only": True,
            "numeric_threshold_sweep": False,
            "outcome_used_at_runtime": False,
        })

    strict = [c for c in candidates if c["strict_discovery_pass"]]
    strict.sort(key=lambda c: (-float(c["metrics"]["net_expectancy_bps"]), -float(c["metrics"]["net_pnl_bps"]), str(c["axis"])))
    result = {
        "schema_version": SCHEMA,
        "state": "STRICT_STRUCTURAL_LIBRARY_CANDIDATE_FOUND" if strict else "STRUCTURAL_LIBRARY_EXHAUSTED_NO_STRICT_CANDIDATE",
        "strategy_id": "trend_rider",
        "base": {"trades": BASE_T, "wins": BASE_WINS, "win_rate": BASE_WR, "net_pnl_bps": BASE_NET_BPS, "net_expectancy_bps": BASE_EXP_BPS},
        "source_receipt_sha256": EXPECTED_SOURCE_RECEIPT,
        "library": LIBRARY,
        "candidate_count": len(candidates),
        "strict_candidate_count": len(strict),
        "recommended_discovery_candidate": strict[0] if strict else None,
        "candidates": candidates,
        "missing": missing,
        "historical_union_allowed": False,
        "historical_metrics_formal_credit": 0,
        "candidate_freeze_required": True,
        "new_fresh_boundary_required": True,
        "fresh_oos_required": True,
        "rr_exit_mutated": False,
        "next": "PREREGISTER_CHILD_THEN_FRESH" if strict else "ONE_BLOCKER_SCOPED_AI_ARCHITECTURE_CALL_ALLOWED",
        **AUTH,
    }
    result["receipt_sha256"] = ev.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    vals = [1.0] * 100
    assert len(ema(vals, 9)) == 100
    assert len(rsi(vals, 14)) == 100
    assert candidate_stats([{"net_bps": 100.0}])["trades"] == 17
    assert AUTH["order_authority"] == "BLOCKED" and AUTH["live_trade_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_WR8125_STRUCTURAL_LIBRARY_V1")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_wr8125_structural_library_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({"state": r.get("state"), "strict": r.get("strict_candidate_count"), "recommended": r.get("recommended_discovery_candidate"), "receipt": r.get("receipt_sha256")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
