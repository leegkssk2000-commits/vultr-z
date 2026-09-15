from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
sm: Any = importlib.import_module(
    "backend.research.rebuild.benchmark25_donor_state_machine_v2"
)
web6: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark_web_gmma_holygrail_v6"
)
v9: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark_web_holygrail_rearm_v9"
)

TF = 1_800_000
ENTRY_COST_GATE = 4.5
SYMS = tuple(v2.SYMS6)


@dataclass(frozen=True)
class ExitVariant:
    name: str
    stop_buffer_atr: float
    target_r: float | None
    scratch_bars: int
    scratch_mfe_r: float
    partial_r: float | None = None
    partial_frac: float = 0.0
    trail_arm_r: float | None = None
    trail_gap_r: float | None = None
    trail_atr_mult: float | None = None
    timeout_bars: int = 20


VARIANTS = (
    ExitVariant("BASE_EXACT_020_TP2", 0.20, 2.0, 6, 0.45, None, 0.0, 1.5, None, 1.8),
    ExitVariant("S015_TP2_ATR18", 0.15, 2.0, 6, 0.45, None, 0.0, 1.5, None, 1.8),
    ExitVariant("S010_TP2_ATR18", 0.10, 2.0, 6, 0.45, None, 0.0, 1.5, None, 1.8),
    ExitVariant("S005_TP2_ATR18", 0.05, 2.0, 6, 0.45, None, 0.0, 1.5, None, 1.8),
    ExitVariant("S010_TP25_ATR18", 0.10, 2.5, 6, 0.45, None, 0.0, 1.5, None, 1.8),
    ExitVariant("S010_TP3_ATR18", 0.10, 3.0, 6, 0.45, None, 0.0, 1.5, None, 1.8),
    ExitVariant("S010_TP3_ATR20", 0.10, 3.0, 6, 0.45, None, 0.0, 1.5, None, 2.0),
    ExitVariant("S010_TP3_ATR22", 0.10, 3.0, 6, 0.45, None, 0.0, 1.5, None, 2.2),
    ExitVariant("S010_SCR4_TP3_ATR20", 0.10, 3.0, 4, 0.30, None, 0.0, 1.5, None, 2.0),
    ExitVariant("S015_RUN_A15_ATR18", 0.15, None, 6, 0.45, None, 0.0, 1.5, None, 1.8),
    ExitVariant("S015_RUN_A20_ATR20", 0.15, None, 6, 0.45, None, 0.0, 2.0, None, 2.0),
    ExitVariant("S015_P20_2R_RUN", 0.15, None, 6, 0.45, 2.0, 0.20, 2.0, None, 2.0),
    ExitVariant("S010_RUN_T20", 0.10, None, 6, 0.45, None, 0.0, 1.5, None, 1.8, 20),
    ExitVariant("S010_RUN_T24", 0.10, None, 6, 0.45, None, 0.0, 1.5, None, 1.8, 24),
    ExitVariant("S010_RUN_T32", 0.10, None, 6, 0.45, None, 0.0, 1.5, None, 1.8, 32),
)


def cost_map() -> dict[str, float]:
    source = Path("/home/z/z/runtime/benchmark_web_holygrail_rearm_v9.json")
    if source.exists():
        data = json.loads(source.read_text(encoding="utf-8"))
        out: dict[str, float] = {}
        for trade in data.get("result", {}).get("trades", []):
            out[str(trade["symbol"])] = float(trade["cost_bps"])
        if all(sym in out for sym in SYMS):
            return out
    authority = v2.read_json(v2.COST_PATH)
    out = {}
    for sym in SYMS:
        snap = v2.cost_ev.fetch_execution_snapshot(sym, authority)
        out[sym] = float(snap["pretrade_verified_cost_bps"])
    return out


def build_inputs() -> tuple[dict[str, pd.DataFrame], dict[str, Any], dict[str, float]]:
    all_spec = sm.load_spec()
    spec_all = web6.build_case_spec(all_spec, "keltner_trend", TF)
    frames_by_tf, _ = v2.prepare_frames(spec_all)
    frames = {sym: web6.enrich_web(df) for sym, df in frames_by_tf[TF].items()}
    return frames, spec_all["children"]["keltner_trend"], cost_map()


def frozen_signals(
    frames: Mapping[str, pd.DataFrame],
    spec: Mapping[str, Any],
    costs: Mapping[str, float],
) -> list[tuple[str, Any]]:
    old_gate = float(v9.COST_GATE)
    v9.COST_GATE = ENTRY_COST_GATE
    out: list[tuple[str, Any]] = []
    try:
        for sym in SYMS:
            x = frames[sym]
            state = web6.WebState()
            i = 121
            while i < len(x) - 1:
                sig = v9.rearm_signal(state, i, x, spec, float(costs[sym]))
                if sig is None:
                    i += 1
                    continue
                trade, exit_j = v2.simulate_trade(
                    "keltner_trend", sig, x, float(costs[sym]), spec
                )
                if trade is not None:
                    out.append((sym, sig))
                i = max(i + 1, exit_j + 1)
    finally:
        v9.COST_GATE = old_gate
    return sorted(out, key=lambda z: (int(z[1].signal_ts), z[0]))


def stop_price(
    sig: Any, row: pd.Series, entry: float, side: int, variant: ExitVariant
) -> float:
    atr = max(float(row["atr"]), 1e-12)
    ref = sig.invalidation_ref
    fallback = entry - side * 1.2 * atr
    if ref is None or not np.isfinite(float(ref)):
        return fallback
    stop = (
        float(ref) - variant.stop_buffer_atr * atr
        if side == 1
        else float(ref) + variant.stop_buffer_atr * atr
    )
    if (side == 1 and stop >= entry) or (side == -1 and stop <= entry):
        return fallback
    return stop


def simulate_exit(
    sym: str,
    sig: Any,
    x: pd.DataFrame,
    cost_bps: float,
    variant: ExitVariant,
) -> tuple[dict[str, Any] | None, int]:
    i = int(sig.index)
    if i + 1 >= len(x):
        return None, i
    side = 1 if sig.side == "long" else -1
    signal_row = x.iloc[i]
    entry = float(x.iloc[i + 1]["open"])
    entry_ts = int(x.iloc[i + 1]["ts_ms"])
    stop = stop_price(sig, signal_row, entry, side, variant)
    risk = abs(entry - stop)
    if risk <= 0 or not np.isfinite(risk):
        return None, i
    target = (
        None if variant.target_r is None else entry + side * variant.target_r * risk
    )
    last = min(len(x) - 1, i + 1 + int(variant.timeout_bars))
    remaining = 1.0
    parts: list[float] = []
    peak = entry
    mfe_r = 0.0
    partial_done = False
    trail: float | None = None
    final_px = float(x.iloc[last]["close"])
    exit_j = last
    reason = "TIMEOUT"
    for j in range(i + 1, last + 1):
        row = x.iloc[j]
        hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
        atr = max(float(row["atr"]), 1e-12)
        if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
            final_px, exit_j, reason = stop, j, "HARD_STOP"
            break
        if sig.invalidation_ref is not None:
            ref = float(sig.invalidation_ref)
            invalid = (
                close < ref - 0.15 * atr if side == 1 else close > ref + 0.15 * atr
            )
            if invalid:
                final_px, exit_j, reason = close, j, "STRUCTURE_INVALIDATION"
                break
        if trail is not None and (
            (side == 1 and lo <= trail) or (side == -1 and hi >= trail)
        ):
            final_px, exit_j, reason = trail, j, "TRAIL"
            break
        if target is not None and (
            (side == 1 and hi >= target) or (side == -1 and lo <= target)
        ):
            final_px, exit_j, reason = target, j, "TARGET"
            break
        fav = (hi - entry) / risk if side == 1 else (entry - lo) / risk
        mfe_r = max(mfe_r, fav)
        peak = max(peak, hi) if side == 1 else min(peak, lo)
        if (
            variant.partial_r is not None
            and not partial_done
            and mfe_r >= variant.partial_r
        ):
            px = entry + side * variant.partial_r * risk
            parts.append(variant.partial_frac * side * (px - entry) / entry * 10_000.0)
            remaining -= variant.partial_frac
            partial_done = True
        if (
            variant.trail_arm_r is not None
            and variant.trail_gap_r is not None
            and mfe_r >= variant.trail_arm_r
        ):
            gap = variant.trail_gap_r * risk
            cand = peak - gap if side == 1 else peak + gap
            trail = (
                max(trail if trail is not None else -np.inf, cand)
                if side == 1
                else min(trail if trail is not None else np.inf, cand)
            )
        held = j - (i + 1) + 1
        if held >= variant.scratch_bars and mfe_r < variant.scratch_mfe_r:
            final_px, exit_j, reason = close, j, "NO_PROGRESS_SCRATCH"
            break
    parts.append(remaining * side * (float(final_px) - entry) / entry * 10_000.0)
    gross = sum(parts)
    return {
        "strategy_id": "keltner_trend",
        "symbol": sym,
        "side": sig.side,
        "signal_ts": int(sig.signal_ts),
        "entry_ts": entry_ts,
        "exit_ts": int(x.iloc[exit_j]["ts_ms"]),
        "entry": entry,
        "exit": float(final_px),
        "reason": reason,
        "gross_bps": gross,
        "cost_bps": cost_bps,
        "net_bps": gross - cost_bps,
        "risk_bps": risk / entry * 10_000.0,
        "mfe_r": mfe_r,
        "partial_done": partial_done,
    }, exit_j


def rr_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(t["net_bps"]) for t in trades]
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    eq = peak = dd = 0.0
    streak = max_streak = 0
    for v in vals:
        eq += v
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        if v < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    return {
        "T": len(vals),
        "WR": len(wins) / len(vals) if vals else None,
        "Net_bps": sum(vals),
        "NetExp_bps_T": sum(vals) / len(vals) if vals else None,
        "PF": sum(wins) / sum(losses) if losses else None,
        "DD_bps": dd,
        "avg_win_bps": avg_win,
        "avg_loss_bps": avg_loss,
        "net_payoff": (
            avg_win / avg_loss if avg_win is not None and avg_loss else None
        ),
        "max_loss_streak": max_streak,
        "avg_risk_bps": (
            sum(float(t["risk_bps"]) for t in trades) / len(trades) if trades else None
        ),
    }


def replay_variant(
    signals: list[tuple[str, Any]],
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    variant: ExitVariant,
    boundary_ts: int,
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    busy_until = {sym: -1 for sym in SYMS}
    overlap_skips = 0
    for sym, sig in signals:
        x = frames[sym]
        entry_ts = int(x.iloc[int(sig.index) + 1]["ts_ms"])
        if entry_ts <= busy_until[sym]:
            overlap_skips += 1
            continue
        trade, _ = simulate_exit(sym, sig, x, float(costs[sym]), variant)
        if trade is None:
            continue
        trades.append(trade)
        busy_until[sym] = int(trade["exit_ts"])
    train = [t for t in trades if int(t["signal_ts"]) <= boundary_ts]
    hold = [t for t in trades if int(t["signal_ts"]) > boundary_ts]
    return {
        "variant": variant.__dict__,
        "T_retention": len(trades) / max(1, len(signals)),
        "overlap_skips": overlap_skips,
        "full": rr_metrics(trades),
        "train60_fixed": rr_metrics(train),
        "holdout40_fixed": rr_metrics(hold),
        "exit_reasons": dict(
            __import__("collections").Counter(t["reason"] for t in trades)
        ),
        "trades": trades,
    }


def choose_by_train(rows: list[dict[str, Any]]) -> str:
    eligible = [
        r
        for r in rows
        if r["T_retention"] >= 0.80
        and int(r["train60_fixed"]["T"]) >= 40
        and float(r["train60_fixed"]["PF"] or 0.0) > 1.0
        and float(r["train60_fixed"]["NetExp_bps_T"] or -1e9) > 0.0
    ]
    if not eligible:
        return "BASE_EXACT_020_TP2"
    best = max(
        eligible,
        key=lambda r: (
            float(r["train60_fixed"]["NetExp_bps_T"] or -1e9),
            float(r["train60_fixed"]["net_payoff"] or 0.0),
            float(r["train60_fixed"]["PF"] or 0.0),
            float(r["T_retention"]),
        ),
    )
    return str(best["variant"]["name"])


def main() -> int:
    frames, spec, costs = build_inputs()
    signals = frozen_signals(frames, spec, costs)
    if len(signals) < 80:
        raise RuntimeError(f"FROZEN_SIGNAL_SET_TOO_SMALL:{len(signals)}")
    ordered_ts = sorted(int(sig.signal_ts) for _, sig in signals)
    boundary = ordered_ts[max(0, int(len(ordered_ts) * 0.60) - 1)]
    rows = [replay_variant(signals, frames, costs, v, boundary) for v in VARIANTS]
    chosen = choose_by_train(rows)
    for r in rows:
        f, tr, h = r["full"], r["train60_fixed"], r["holdout40_fixed"]
        print(
            "KELTNER_RR_V10="
            + json.dumps(
                {
                    "name": r["variant"]["name"],
                    "T": f["T"],
                    "retention": r["T_retention"],
                    "WR": f["WR"],
                    "NetExp": f["NetExp_bps_T"],
                    "PF": f["PF"],
                    "payoff": f["net_payoff"],
                    "avg_win": f["avg_win_bps"],
                    "avg_loss": f["avg_loss_bps"],
                    "train_NetExp": tr["NetExp_bps_T"],
                    "train_PF": tr["PF"],
                    "train_payoff": tr["net_payoff"],
                    "hold_T": h["T"],
                    "hold_NetExp": h["NetExp_bps_T"],
                    "hold_PF": h["PF"],
                    "hold_payoff": h["net_payoff"],
                    "chosen_by_train": r["variant"]["name"] == chosen,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    report = {
        "schema": "zel.a1.benchmark.keltner_rr_lifecycle.v10",
        "state": "DEV_RR_OPTIMIZATION_COMPLETE",
        "entry_child": "KELTNER_HOLYGRAIL_GMMA_REARM_30M",
        "entry_cost_gate": ENTRY_COST_GATE,
        "frozen_signal_count": len(signals),
        "selection_boundary_signal_ts": boundary,
        "selection_rule": "train60 only; T retention>=80%; train T>=40; PF>1; NetExp>0; rank NetExp/payoff/PF",
        "chosen_variant": chosen,
        "holdout_note": "development validation only; the 180d history was previously inspected during entry research and is not pristine OOS",
        "rows": rows,
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    out = Path("/home/z/z/runtime/benchmark_keltner_rr_lifecycle_v10.json")
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
