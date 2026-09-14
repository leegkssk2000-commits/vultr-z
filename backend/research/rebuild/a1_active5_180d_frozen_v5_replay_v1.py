from __future__ import annotations

import importlib
import json
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, Mapping

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
ev: Any = importlib.import_module(
    "backend.research.rebuild.a1_exact25_generic_evaluator_three_lane_v1"
)
rt: Any = importlib.import_module(
    "backend.research.rebuild.a1_active5_runner_trailing_v1"
)
pk: Any = importlib.import_module("backend.research.rebuild.policy_kernel_v1")

ACTIVE5 = (
    "supertrend_pullback",
    "keltner_trend",
    "break_and_continue",
    "trend_ma_macd",
    "trend_rider",
)
EXTRA_SL_COOLDOWN = {"supertrend_pullback": 3, "keltner_trend": 3, "trend_rider": 1}


def local_1h_bars() -> dict[str, list[dict[str, float | int]]]:
    base = v2.util.load_5m()
    out: dict[str, list[dict[str, float | int]]] = {}
    for sym, df in base.items():
        x = v2.util.resample_frame(df, 12)
        out[sym] = [
            {
                "ts_ms": int(r.ts_ms),
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
            }
            for r in x.itertuples(index=False)
        ]
    return out


def quality_ok(sid: str, signal_bar: Mapping[str, Any], feature: Any) -> bool:
    atr = float(getattr(feature, "atr", 0.0) or 0.0)
    body = (
        abs(float(signal_bar["close"]) - float(signal_bar["open"])) / atr
        if atr > 0
        else 0.0
    )
    vals = getattr(feature, "values", {}) or {}
    chase = vals.get("chase_atr") if isinstance(vals, Mapping) else None
    if sid == "break_and_continue" and body < 0.40:
        return False
    if sid == "trend_rider" and body > 0.40:
        return False
    if sid == "trend_ma_macd" and (chase is None or float(chase) > 1.20):
        return False
    return True


def reserve(exit_ts: int, cooldown: int) -> int:
    return int(exit_ts) + max(0, cooldown) * 3_600_000


def replay_raw_strategy(
    sid: str,
    bars_by_symbol: Mapping[str, list[dict[str, float | int]]],
    costs: Mapping[str, float],
    inventory: Mapping[str, Any],
) -> list[dict[str, Any]]:
    module, _, policy_sha = ev.load_policy(sid, inventory)
    cfg = ev.config_instance(module)
    if not is_dataclass(cfg):
        raise RuntimeError(f"CONFIG_NOT_DATACLASS:{sid}")
    compute, build = ev.policy_functions(module, sid)
    trades: list[dict[str, Any]] = []
    for sym, bars in bars_by_symbol.items():
        blocked_until = -1
        warmup = int(
            getattr(cfg, "warmup_bars", max(64, int(getattr(cfg, "lookback", 20)) + 10))
        )
        for i in range(max(1, warmup), len(bars) - 1):
            try:
                history = bars[max(0, i + 1 - 1000) : i + 1]
                feature = compute(
                    history,
                    symbol=sym,
                    now_ts_ms=int(bars[i]["ts_ms"]),
                    config=cfg,
                )
                intent = build(
                    feature,
                    policy_source_sha=policy_sha,
                    verified_round_trip_cost_bps=float(costs[sym]),
                    config=cfg,
                )
            except ValueError as exc:
                if str(exc).startswith(("WARMUP_", "WINDOW_", "ATR_")):
                    continue
                raise
            if bool(getattr(intent, "no_trade")) or not quality_ok(
                sid, bars[i], feature
            ):
                continue
            side_name = str(getattr(intent, "side"))
            if side_name not in ("long", "short"):
                continue
            entry_bar = bars[i + 1]
            entry_ts = int(entry_bar["ts_ms"])
            owns, base_cd = ev.execution_ownership_policy(intent)
            if owns and entry_ts <= blocked_until:
                continue
            side = 1 if side_name == "long" else -1
            entry = float(entry_bar["open"])
            timeout = getattr(intent, "timeout", {}) or {}
            timeout_bars = int(timeout.get("bars", getattr(cfg, "timeout_bars", 1)))
            sl = getattr(intent, "sl", None)
            tp = getattr(intent, "tp", None)
            if sl is None and tp is None:
                continue
            last_j = min(len(bars) - 1, i + 1 + max(1, timeout_bars))
            exit_px = None
            exit_ts = None
            reason = "TIMEOUT"
            for j in range(i + 1, last_j + 1):
                bar = bars[j]
                low, high = float(bar["low"]), float(bar["high"])
                if sl is not None and (
                    (side == 1 and low <= float(sl))
                    or (side == -1 and high >= float(sl))
                ):
                    exit_px, exit_ts, reason = float(sl), int(bar["ts_ms"]), "SL"
                    break
                if tp is not None and (
                    (side == 1 and high >= float(tp))
                    or (side == -1 and low <= float(tp))
                ):
                    exit_px, exit_ts, reason = float(tp), int(bar["ts_ms"]), "TP"
                    break
            if exit_px is None:
                exit_px = float(bars[last_j]["close"])
                exit_ts = int(bars[last_j]["ts_ms"])
            assert exit_ts is not None and exit_px is not None
            if owns:
                cd = int(base_cd) + (
                    EXTRA_SL_COOLDOWN.get(sid, 0) if reason == "SL" else 0
                )
                blocked_until = max(blocked_until, reserve(int(exit_ts), cd))
            gross = side * (float(exit_px) - entry) / entry * 10_000.0
            cost = float(costs[sym])
            trades.append(
                {
                    "strategy_id": sid,
                    "symbol": sym,
                    "signal_ts": int(getattr(intent, "signal_ts")),
                    "entry_ts": entry_ts,
                    "exit_ts": int(exit_ts),
                    "side": side_name,
                    "entry": entry,
                    "exit": float(exit_px),
                    "reason": reason,
                    "gross_bps": gross,
                    "realized_cost_bps": cost,
                    "net_bps": gross - cost,
                    "intent_geometry": ev.sealed_intent_geometry(
                        intent, policy_sha=policy_sha
                    ),
                }
            )
    return sorted(trades, key=lambda t: (int(t["exit_ts"]), str(t["symbol"])))


def btc_context(
    btc: list[dict[str, float | int]]
) -> dict[int, tuple[float, float, float, float]]:
    closes = [float(b["close"]) for b in btc]
    ema50 = pk.ema(closes, 50)
    out: dict[int, tuple[float, float, float, float]] = {}
    for i, b in enumerate(btc):
        if i < 50:
            continue
        a = float(pk.atr(btc[max(0, i - 80) : i + 1], 14))
        out[int(b["ts_ms"])] = (
            closes[i],
            float(ema50[i]),
            float(ema50[i] - ema50[i - 1]),
            a,
        )
    return out


def weak_keep(
    t: Mapping[str, Any], ctx: Mapping[int, tuple[float, float, float, float]], d: float
) -> bool:
    value = ctx.get(int(t["signal_ts"]))
    if value is None:
        return False
    c, mean, slope, a = value
    q = 1 if str(t["side"]) == "long" else -1
    return not (
        (q == 1 and c < mean - d * a and slope < 0)
        or (q == -1 and c > mean + d * a and slope > 0)
    )


def aligned_keep(
    t: Mapping[str, Any], ctx: Mapping[int, tuple[float, float, float, float]]
) -> bool:
    value = ctx.get(int(t["signal_ts"]))
    if value is None:
        return False
    c, mean, slope, _ = value
    direction = 1 if c > mean and slope > 0 else (-1 if c < mean and slope < 0 else 0)
    side = 1 if str(t["side"]) == "long" else -1
    return direction == 0 or direction == side


def apply_v5(
    sid: str,
    trades: list[dict[str, Any]],
    bars_by_symbol: Mapping[str, list[dict[str, float | int]]],
    btc_ctx: Mapping[int, tuple[float, float, float, float]],
) -> tuple[list[dict[str, Any]], list[float]]:
    if sid == "supertrend_pullback":
        selected = [t for t in trades if weak_keep(t, btc_ctx, 1.25)]
    elif sid == "keltner_trend":
        selected = [t for t in trades if weak_keep(t, btc_ctx, 1.0)]
    elif sid in {"break_and_continue", "trend_ma_macd", "trend_rider"}:
        selected = [t for t in trades if aligned_keep(t, btc_ctx)]
    else:
        selected = list(trades)
    base_rule = dict(rt.SELECTED[sid][1])
    if base_rule.get("stale_bars"):
        base_rule["stale_frac"] = 0.50
    vals = [
        rt.simulate(t, bars_by_symbol[str(t["symbol"])], base_rule, {})
        for t in selected
    ]
    return selected, vals


def split_vals(vals: list[float]) -> dict[str, Any]:
    cut = int(len(vals) * 0.60)
    return {
        "full": rt.metrics(vals),
        "train60": rt.metrics(vals[:cut]),
        "holdout40": rt.metrics(vals[cut:]),
    }


def main() -> int:
    bars = local_1h_bars()
    inventory = ev.load_json(ev.INVENTORY_PATH)
    authority = ev.load_json(ev.COST_PATH)
    costs: dict[str, float] = {}
    snapshots: dict[str, Any] = {}
    for sym in v2.SYMS6:
        snap = ev.fetch_execution_snapshot(sym, authority)
        snapshots[sym] = snap
        costs[sym] = float(snap["pretrade_verified_cost_bps"])
    ctx = btc_context(bars["BTC-USDT"])
    report: dict[str, Any] = {
        "schema": "zel.a1.active5.180d_frozen_v5_replay.v1",
        "state": "RESEARCH_ONLY_180D_REPLAY",
        "window": "180d_exact_5m_cache_resampled_to_1h",
        "cost_note": "current verified round-trip cost snapshot charged per trade; historical funding path not reconstructed",
        "strategies": {},
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    agg_raw: list[tuple[int, str, float]] = []
    agg_v5: list[tuple[int, str, float]] = []
    for sid in ACTIVE5:
        raw = replay_raw_strategy(sid, bars, costs, inventory)
        selected, vals = apply_v5(sid, raw, bars, ctx)
        raw_vals = [float(t["net_bps"]) for t in raw]
        report["strategies"][sid] = {
            "raw": split_vals(raw_vals),
            "v5_frozen": split_vals(vals),
            "raw_T": len(raw),
            "v5_T": len(selected),
        }
        for t in raw:
            agg_raw.append((int(t["exit_ts"]), sid, float(t["net_bps"])))
        for t, val in zip(selected, vals):
            agg_v5.append((int(t["exit_ts"]), sid, float(val)))
        print(
            "ACTIVE5_180D_ROW="
            + json.dumps(
                {
                    "strategy_id": sid,
                    "raw": report["strategies"][sid]["raw"]["full"],
                    "v5": report["strategies"][sid]["v5_frozen"]["full"],
                    "v5_hold": report["strategies"][sid]["v5_frozen"]["holdout40"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    agg_raw.sort(key=lambda z: (z[0], z[1]))
    agg_v5.sort(key=lambda z: (z[0], z[1]))
    report["aggregate_raw"] = split_vals([v for _, _, v in agg_raw])
    report["aggregate_v5_frozen"] = split_vals([v for _, _, v in agg_v5])
    out = Path("/home/z/z/runtime/active5_180d_frozen_v5_replay_v1.json")
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        "ACTIVE5_180D_AGG="
        + json.dumps(
            {
                "raw": report["aggregate_raw"]["full"],
                "v5": report["aggregate_v5_frozen"]["full"],
                "v5_hold": report["aggregate_v5_frozen"]["holdout40"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
