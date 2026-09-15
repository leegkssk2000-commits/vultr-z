from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

rr: Any = importlib.import_module(
    "backend.research.rebuild.a1_keltner_holygrail_rr_opt_v10"
)
v2, sm, web6, v9 = rr.v2, rr.sm, rr.web6, rr.v9

TF = 1_800_000
COST_GATE = 4.5
FEE_BE_LOCK_NET_BPS = 2.0
COSTS = {
    "BTC-USDT": 14.0,
    "ETH-USDT": 14.0,
    "SOL-USDT": 14.0,
    "XRP-USDT": 15.058813437188807,
    "LINK-USDT": 15.561366061899777,
    "DOGE-USDT": 15.363228169680506,
}


def simulate_fee_be(
    signal: Any, frame: Any, cost_bps: float
) -> tuple[dict[str, Any] | None, int]:
    i = int(signal.index)
    if i + 1 >= len(frame):
        return None, i
    side = 1 if signal.side == "long" else -1
    entry = float(frame.iloc[i + 1]["open"])
    atr = max(float(frame.iloc[i]["atr"]), 1e-12)
    reference = float(signal.invalidation_ref)
    stop = reference - side * 0.10 * atr
    if (side == 1 and stop >= entry) or (side == -1 and stop <= entry):
        stop = entry - side * 1.2 * atr
    risk = abs(entry - stop)
    last = min(len(frame) - 1, i + 25)
    peak = entry
    mfe = 0.0
    remaining = 1.0
    parts: list[float] = []
    partial_done = False
    be_armed = False
    trail: float | None = None
    exit_j = last
    reason = "TIMEOUT"
    final = float(frame.iloc[last]["close"])
    for j in range(i + 1, last + 1):
        row = frame.iloc[j]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        fee_be = entry * (1 + side * (cost_bps + FEE_BE_LOCK_NET_BPS) / 10_000.0)
        active_stop = fee_be if be_armed else stop
        if (side == 1 and low <= active_stop) or (side == -1 and high >= active_stop):
            final = active_stop
            exit_j = j
            reason = "FEE_BE_STOP" if be_armed else "HARD_STOP"
            break
        if trail is not None and (
            (side == 1 and low <= trail) or (side == -1 and high >= trail)
        ):
            final = trail
            exit_j = j
            reason = "TRAIL"
            break
        favorable = (high - entry) / risk if side == 1 else (entry - low) / risk
        mfe = max(mfe, favorable)
        peak = max(peak, high) if side == 1 else min(peak, low)
        if mfe >= 1.0:
            be_armed = True
        if not partial_done and mfe >= 2.0:
            partial_px = entry + side * 2.0 * risk
            parts.append(0.10 * side * (partial_px - entry) / entry * 10_000.0)
            remaining -= 0.10
            partial_done = True
        if mfe >= 3.0:
            candidate = peak - side * 1.25 * risk
            trail = (
                max(trail if trail is not None else -1e99, candidate)
                if side == 1
                else min(trail if trail is not None else 1e99, candidate)
            )
        if j - (i + 1) + 1 >= 5 and mfe < 0.40:
            final = close
            exit_j = j
            reason = "SCRATCH"
            break
    parts.append(remaining * side * (final - entry) / entry * 10_000.0)
    gross = sum(parts)
    return {
        "symbol": "",
        "signal_ts": int(signal.signal_ts),
        "entry_ts": int(frame.iloc[i + 1]["ts_ms"]),
        "exit_ts": int(frame.iloc[exit_j]["ts_ms"]),
        "side": str(signal.side),
        "gross_bps": gross,
        "cost_bps": cost_bps,
        "net_bps": gross - cost_bps,
        "reason": reason,
    }, exit_j


def max_loss_streak(trades: list[dict[str, Any]]) -> int:
    current = 0
    maximum = 0
    for trade in sorted(trades, key=lambda t: (int(t["exit_ts"]), str(t["symbol"]))):
        current = current + 1 if float(trade["net_bps"]) < 0 else 0
        maximum = max(maximum, current)
    return maximum


def replay() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    v9.COST_GATE = COST_GATE
    all_spec = sm.load_spec()
    spec_all = web6.build_case_spec(all_spec, "keltner_trend", TF)
    frames_by_tf, _ = v2.prepare_frames(spec_all)
    spec = spec_all["children"]["keltner_trend"]
    trades: list[dict[str, Any]] = []
    for symbol in v2.SYMS6:
        frame = web6.enrich_web(frames_by_tf[TF][symbol])
        state = web6.WebState()
        i = 121
        while i < len(frame) - 1:
            signal = v9.rearm_signal(state, i, frame, spec, COSTS[symbol])
            if signal is None:
                i += 1
                continue
            trade, exit_j = simulate_fee_be(signal, frame, COSTS[symbol])
            if trade is not None:
                trade["symbol"] = symbol
                trades.append(trade)
            i = max(i + 1, exit_j + 1)
    trades.sort(key=lambda t: (int(t["exit_ts"]), str(t["symbol"])))
    cut = int(len(trades) * 0.60)
    full = rr.metrics(trades)
    holdout = rr.metrics(trades[cut:])
    full["MaxLossStreak"] = max_loss_streak(trades)
    holdout["MaxLossStreak"] = max_loss_streak(trades[cut:])
    return trades, full, holdout


def main() -> int:
    trades, full, holdout = replay()
    out = {
        "schema": "zel.a1.keltner_holygrail.streak_guard.v11",
        "state": "DEV_STREAK_GUARD_CANDIDATE_NOT_FRESH_OOS",
        "strategy_id": "keltner_trend",
        "timeframe": "30m",
        "entry_gate_atr_cost": COST_GATE,
        "rr_core": "0.10ATR stop buffer; +1R BE arm; +2R 10% partial; +3R runner trail 1.25R; scratch at 5 bars if MFE<0.40R",
        "change_only": "after +1R, move BE to verified round-trip cost plus 2bps net instead of raw entry",
        "full": full,
        "holdout40_dev": holdout,
        "trades": trades,
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "fresh_forward_required": True,
    }
    target = Path("/home/z/z/runtime/keltner_holygrail_streak_guard_v11.json")
    target.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "KELTNER_STREAK_V11="
        + json.dumps(
            {
                "T": full["T"],
                "WR": full["WR"],
                "NetExp_bps_T": full["Exp_bps_T"],
                "PF": full["PF"],
                "Payoff": full["Payoff"],
                "DD_bps": full["DD_bps"],
                "MaxLossStreak": full["MaxLossStreak"],
                "HoldT": holdout["T"],
                "HoldNetExp_bps_T": holdout["Exp_bps_T"],
                "HoldPF": holdout["PF"],
                "HoldMaxLossStreak": holdout["MaxLossStreak"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
