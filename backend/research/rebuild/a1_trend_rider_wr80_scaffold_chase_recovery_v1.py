#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as exact
from backend.research.rebuild import trend_policy_batch_v1 as canonical
from backend.research.rebuild import trend_rider_transition_freshness_non_us_chase_cooling_reentry_child_policy_v1 as child

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "backend/research/rebuild/trend_rider_trigger32623644328_incumbent_context_v1.json"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("OBJECT_REQUIRED")
    return value


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def session(ts: int) -> str:
    h = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).hour
    return "APAC" if h < 8 else "EU" if h < 16 else "US"


def max_dd(rows: list[dict[str, Any]]) -> float:
    equity = peak = worst = 0.0
    for row in rows:
        equity += float(row["net_bps"])
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_bps"]) for row in rows]
    wins = sum(x > 0 for x in values)
    losses = sum(x < 0 for x in values)
    return {
        "trades": len(rows),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(rows) if rows else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(rows) if rows else None,
        "max_drawdown_bps": max_dd(rows),
    }


def true_ranges(bars: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    previous_close = None
    for bar in bars:
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        out.append(high - low if previous_close is None else max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = close
    return out


def wilder_series(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < length:
        return out
    current = sum(values[:length]) / length
    out[length - 1] = current
    for i in range(length, len(values)):
        current = ((length - 1) * current + values[i]) / length
        out[i] = current
    return out


def ema_series(values: list[float], length: int) -> list[float]:
    alpha = 2.0 / (length + 1.0)
    out = [float(values[0])]
    for value in values[1:]:
        out.append(alpha * float(value) + (1.0 - alpha) * out[-1])
    return out


def chase_atr_series(bars: list[dict[str, Any]]) -> list[float | None]:
    if not bars:
        return []
    closes = [float(bar["close"]) for bar in bars]
    ema50 = ema_series(closes, 50)
    atr14 = wilder_series(true_ranges(bars), 14)
    out: list[float | None] = [None] * len(bars)
    for i, atr in enumerate(atr14):
        if atr is not None and float(atr) > 0:
            out[i] = abs(closes[i] - ema50[i]) / float(atr)
    return out


def parity_self_test() -> None:
    bars: list[dict[str, Any]] = []
    price = 100.0
    for i in range(80):
        open_px = price
        close_px = price * (1.0 + (0.002 if i % 5 else -0.001))
        high = max(open_px, close_px) * 1.003
        low = min(open_px, close_px) * 0.997
        bars.append({"ts_ms": i * 3_600_000, "open": open_px, "high": high, "low": low, "close": close_px, "volume": 1000 + i})
        price = close_px
    fast = chase_atr_series(bars)
    cfg = canonical.TrendPolicyConfig()
    current = canonical.compute_trend_rider_feature(bars, symbol="BTC-USDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=cfg)
    prior = canonical.compute_trend_rider_feature(bars[:-1], symbol="BTC-USDT", now_ts_ms=int(bars[-2]["ts_ms"]), config=cfg)
    assert fast[-1] is not None and fast[-2] is not None
    assert math.isclose(float(fast[-1]), float(current.values["chase_atr"]), rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(float(fast[-2]), float(prior.values["chase_atr"]), rel_tol=0.0, abs_tol=1e-12)


def run(out: Path) -> dict[str, Any]:
    fixture = read(FIXTURE)
    rows = [dict(row) for row in fixture["rows"]]
    if len(rows) != 24 or int(fixture["trade_count"]) != 24:
        raise RuntimeError("FROZEN_CONTEXT_COUNT_MISMATCH")

    parent = metrics(rows)
    if abs(float(parent["net_pnl_bps"]) - 24812.448723667734) > 1e-6:
        raise RuntimeError("FROZEN_PARENT_PNL_MISMATCH")
    if abs(float(parent["win_rate"]) - 14 / 24) > 1e-12:
        raise RuntimeError("FROZEN_PARENT_WR_MISMATCH")

    scaffold_rows = [row for row in rows if session(int(row["signal_ts"])) != "US"]
    scaffold = metrics(scaffold_rows)
    if len(scaffold_rows) != 15 or abs(float(scaffold["win_rate"]) - 0.8) > 1e-12:
        raise RuntimeError("WR80_SCAFFOLD_REPRO_FAIL")
    if abs(float(scaffold["net_pnl_bps"]) - 21196.60152461874) > 1e-6:
        raise RuntimeError("WR80_SCAFFOLD_PNL_REPRO_FAIL")

    retained: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    defects: list[str] = []
    bars_meta: dict[str, Any] = {}

    for symbol in sorted({str(row["symbol"]) for row in rows}):
        bars = exact.fetch_bars(symbol, "1h", 1000)
        index = {int(bar["ts_ms"]): i for i, bar in enumerate(bars)}
        chase = chase_atr_series(bars)
        bars_meta[symbol] = {
            "bars": len(bars),
            "first_ts": int(bars[0]["ts_ms"]) if bars else None,
            "last_ts": int(bars[-1]["ts_ms"]) if bars else None,
        }
        for row in [x for x in rows if x["symbol"] == symbol]:
            ts = int(row["signal_ts"])
            i = index.get(ts)
            sess = session(ts)
            if i is None or i < 64 or chase[i] is None or chase[i - 1] is None:
                defects.append(f"{symbol}:{ts}:BAR_OR_WARMUP_MISSING")
                continue
            cooling = float(chase[i]) <= float(chase[i - 1])
            us_reentry = bool(sess == "US" and cooling)
            keep = bool(sess != "US" or us_reentry)
            if keep:
                retained.append(row)
            decisions.append({
                "symbol": symbol,
                "signal_ts": ts,
                "side": str(row["side"]),
                "net_bps": float(row["net_bps"]),
                "session": sess,
                "retained": keep,
                "chase_atr_current": float(chase[i]),
                "chase_atr_prior_closed_bar": float(chase[i - 1]),
                "chase_atr_cooling": cooling,
                "us_chase_cooling_reentry_allowed": us_reentry,
            })

    recovery = metrics(retained)
    if defects:
        state = "HOLD_TARGETED_REPLAY_INTEGRITY"
    elif recovery["win_rate"] is not None and float(recovery["win_rate"]) >= 0.8 and float(recovery["net_pnl_bps"]) > float(scaffold["net_pnl_bps"]):
        state = "PASS_WR_SCAFFOLD_PNL_RECOVERY"
    else:
        state = "HOLD_WR80_SCAFFOLD_TRY_NEXT_PNL_RECOVERY_AXIS"

    result = {
        "schema_version": "zel.a1.trend_rider.wr80_scaffold_chase_recovery.v1",
        "state": state,
        "strategy_id": "trend_rider",
        "generation": 2,
        "changed_axis": child.AXIS,
        "trigger_run_id": int(fixture["trigger_run_id"]),
        "method": "IMMUTABLE_24_TRADE_OVERLAY_PREENTRY_TARGETED_REPLAY_LINEAR_CHASE_PARITY",
        "parent_context": parent,
        "parked_wr80_scaffold": scaffold,
        "recovery_candidate": recovery,
        "deltas_vs_scaffold": {
            "win_rate_pp": None if recovery["win_rate"] is None else 100.0 * (float(recovery["win_rate"]) - 0.8),
            "net_pnl_bps": float(recovery["net_pnl_bps"]) - float(scaffold["net_pnl_bps"]),
            "max_drawdown_bps": float(recovery["max_drawdown_bps"]) - float(scaffold["max_drawdown_bps"]),
            "trades": int(recovery["trades"]) - 15,
        },
        "pnl_gap_to_parent_bps": float(parent["net_pnl_bps"]) - float(recovery["net_pnl_bps"]),
        "re_admitted_us": [d for d in decisions if d["session"] == "US" and d["retained"]],
        "blocked_us": [d for d in decisions if d["session"] == "US" and not d["retained"]],
        "decisions": decisions,
        "bars": bars_meta,
        "integrity_defects": defects,
        "historical_regression_is_promotion_evidence": False,
        "fresh_25_h4_h5_still_required": True,
        "scaffold_must_not_be_discarded_if_this_axis_fails": True,
        "next": "PREREGISTER_RECOVERY_CHILD_FRESH25_THEN_H4_H5" if state == "PASS_WR_SCAFFOLD_PNL_RECOVERY" else "KEEP_WR80_SCAFFOLD_AND_ROUTE_NEXT_DISTINCT_US_REENTRY_MECHANISM",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": state,
        "scaffold": scaffold,
        "recovery": recovery,
        "delta": result["deltas_vs_scaffold"],
        "re_admitted_us": result["re_admitted_us"],
        "next": result["next"],
    }, sort_keys=True, allow_nan=False))
    return result


def self_test() -> int:
    fixture = read(FIXTURE)
    assert fixture["trade_count"] == 24 and fixture["trigger_run_id"] == 32623644328
    assert session(15 * 3600 * 1000) == "EU" and session(16 * 3600 * 1000) == "US"
    assert child.AXIS == "NON_US_SCAFFOLD_PLUS_US_CHASE_ATR_COOLING_REENTRY"
    parity_self_test()
    print("PASS_A1_TREND_RIDER_WR80_SCAFFOLD_CHASE_RECOVERY_V1_SELF_TEST")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_wr80_scaffold_chase_recovery_latest.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    run(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
