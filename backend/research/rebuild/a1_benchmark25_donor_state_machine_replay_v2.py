from __future__ import annotations

import argparse
from collections import Counter
import importlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

util: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_native_replay_v1"
)
sm: Any = importlib.import_module(
    "backend.research.rebuild.benchmark25_donor_state_machine_v2"
)
EntrySignal = sm.EntrySignal
MachineState = sm.MachineState
load_spec = sm.load_spec
step_machine = sm.step_machine
validate_coverage = sm.validate_coverage

cost_ev: Any = importlib.import_module(
    "backend.research.rebuild.a1_exact25_generic_evaluator_three_lane_v1"
)
ROOT = Path(__file__).resolve().parents[3]
COST_PATH = (
    ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
)
SYMS6 = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
MICRO_REQUIRED = {"liquidity_sweep", "scalp_snap", "vol_spike_fade", "vwap_revert"}
OUTLIER_RUNNERS = {
    "turtle_trend",
    "trend_rider",
    "keltner_trend",
    "supertrend_pullback",
    "trend_ma_macd",
}
PARTIAL_RUNNERS = OUTLIER_RUNNERS | {
    "break_and_continue",
    "squeeze_break",
    "ema_ribbon_scalp",
    "obv_trend",
    "session_bias",
    "sr_levels",
    "alpha_combo",
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def prepare_frames(
    spec: Mapping[str, Any]
) -> tuple[dict[int, dict[str, pd.DataFrame]], dict[str, pd.DataFrame]]:
    base = util.load_5m()
    micro = util.load_micro()
    by_tf: dict[int, dict[str, pd.DataFrame]] = {}
    for tf in sorted({int(v["timeframe_ms"]) for v in spec["children"].values()}):
        factor = tf // 300_000
        frames = {}
        for sym, df in base.items():
            x = util.enrich(util.resample_frame(df, factor))
            macd = (
                x["close"].ewm(span=12, adjust=False).mean()
                - x["close"].ewm(span=26, adjust=False).mean()
            )
            x["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
            x = (
                util.micro_columns(x, micro.get(sym))
                if tf == 300_000
                else util.micro_columns(x, None)
            )
            frames[sym] = x
        by_tf[tf] = frames
    return by_tf, micro


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(t["net_bps"]) for t in trades]
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    eq = peak = dd = 0.0
    for v in vals:
        eq += v
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "T": len(vals),
        "WR": len(wins) / len(vals) if vals else None,
        "Gross_bps": sum(float(t["gross_bps"]) for t in trades),
        "Cost_bps": sum(float(t["cost_bps"]) for t in trades),
        "Net_bps": sum(vals),
        "Exp_bps_T": sum(vals) / len(vals) if vals else None,
        "GrossExp_bps_T": (
            sum(float(t["gross_bps"]) for t in trades) / len(trades) if trades else None
        ),
        "PF": sum(wins) / sum(losses) if losses else None,
        "DD_bps": dd,
    }


def split_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda t: (int(t["exit_ts"]), str(t["symbol"])))
    cut = int(len(ordered) * 0.60)
    return {"train60": metrics(ordered[:cut]), "holdout40": metrics(ordered[cut:])}


def initial_stop(
    signal: Any, row: pd.Series, entry: float, spec: Mapping[str, Any]
) -> float:
    side = 1 if signal.side == "long" else -1
    a = max(float(row["atr"]), 1e-12)
    risk_spec = spec["risk"]
    fallback = entry - side * float(risk_spec["stop_atr_mult"]) * a
    mode = str(risk_spec["stop_mode"])
    candidate = fallback
    if mode == "event_extreme_plus_atr_buffer" and signal.event_extreme is not None:
        candidate = (
            float(signal.event_extreme) - 0.15 * a
            if side == 1
            else float(signal.event_extreme) + 0.15 * a
        )
    elif (
        mode == "reference_failure_plus_atr_buffer"
        and signal.invalidation_ref is not None
    ):
        candidate = (
            float(signal.invalidation_ref) - 0.20 * a
            if side == 1
            else float(signal.invalidation_ref) + 0.20 * a
        )
    if (
        not np.isfinite(candidate)
        or (side == 1 and candidate >= entry)
        or (side == -1 and candidate <= entry)
    ):
        candidate = fallback
    if (side == 1 and candidate >= entry) or (side == -1 and candidate <= entry):
        raise RuntimeError("STATE_MACHINE_STOP_NOT_ADVERSE")
    return float(candidate)


def target_price(
    signal: Any,
    row: pd.Series,
    entry: float,
    risk: float,
    spec: Mapping[str, Any],
) -> float | None:
    side = 1 if signal.side == "long" else -1
    life = spec["lifecycle"]
    mode = str(life["target_mode"])
    if mode == "runner_no_fixed_tp":
        return None
    if mode == "rolling_mean20":
        target = float(row["mean20"])
    elif mode == "vwap20":
        target = float(row["vwap20"])
    elif mode == "vwap50":
        target = float(row["vwap50"])
    else:
        rr = life.get("target_r")
        return None if rr is None else entry + side * float(rr) * risk
    if (
        not np.isfinite(target)
        or (side == 1 and target <= entry)
        or (side == -1 and target >= entry)
    ):
        rr = float(life.get("target_r") or 1.0)
        target = entry + side * rr * risk
    return float(target)


def adverse_micro(row: pd.Series, side: int) -> bool:
    ti = float(row.get("m_trade_imbalance", np.nan))
    im = float(row.get("m_imbalance_delta", np.nan))
    if not np.isfinite(ti) or not np.isfinite(im):
        return False
    return (ti < -0.20 and im < 0) if side == 1 else (ti > 0.20 and im > 0)


def simulate_trade(
    sid: str,
    signal: Any,
    x: pd.DataFrame,
    cost_bps: float,
    spec: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, int]:
    i = signal.index
    if i + 1 >= len(x):
        return None, i
    side = 1 if signal.side == "long" else -1
    signal_row = x.iloc[i]
    entry_row = x.iloc[i + 1]
    entry = float(entry_row["open"])
    entry_ts = int(entry_row["ts_ms"])
    stop = initial_stop(signal, signal_row, entry, spec)
    risk = abs(entry - stop)
    if risk <= 0:
        return None, i
    tp = target_price(signal, signal_row, entry, risk, spec)
    life = spec["lifecycle"]
    timeout = int(life["timeout_bars"])
    scratch_b = int(life["scratch_after_bars"])
    scratch_r = float(life["scratch_if_mfe_below_r"])
    trail_activate = life.get("trail_activate_r")
    trail_mult = life.get("trail_atr_mult")
    partial_trigger = 2.0 if sid in OUTLIER_RUNNERS else 1.5
    partial_fraction = 0.20 if sid in OUTLIER_RUNNERS else 0.25
    remaining = 1.0
    gross_parts: list[float] = []
    mfe = 0.0
    peak = entry
    trail = None
    partial_done = False
    last = min(len(x) - 1, i + 1 + timeout)
    exit_j = last
    reason = "TIMEOUT"
    final_px = float(x.iloc[last]["close"])
    for j in range(i + 1, last + 1):
        row = x.iloc[j]
        hi = float(row["high"])
        lo = float(row["low"])
        close = float(row["close"])
        a = max(float(row["atr"]), 1e-12)
        if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
            final_px = stop
            exit_j = j
            reason = "HARD_STOP"
            break
        if signal.invalidation_ref is not None:
            ref = float(signal.invalidation_ref)
            invalid = (
                (close < ref - 0.15 * a) if side == 1 else (close > ref + 0.15 * a)
            )
            if invalid:
                final_px = close
                exit_j = j
                reason = "STRUCTURE_INVALIDATION"
                break
        if sid in MICRO_REQUIRED and adverse_micro(row, side):
            final_px = close
            exit_j = j
            reason = "FLOW_OPINION_CHANGE"
            break
        if trail is not None and (
            (side == 1 and lo <= trail) or (side == -1 and hi >= trail)
        ):
            final_px = float(trail)
            exit_j = j
            reason = "TRAIL"
            break
        if tp is not None and ((side == 1 and hi >= tp) or (side == -1 and lo <= tp)):
            final_px = float(tp)
            exit_j = j
            reason = "TARGET"
            break
        fav = (hi - entry) / risk if side == 1 else (entry - lo) / risk
        mfe = max(mfe, fav)
        peak = max(peak, hi) if side == 1 else min(peak, lo)
        if sid in PARTIAL_RUNNERS and not partial_done and mfe >= partial_trigger:
            px = entry + side * partial_trigger * risk
            gross_parts.append(partial_fraction * side * (px - entry) / entry * 10_000)
            remaining -= partial_fraction
            partial_done = True
        activate = (
            max(1.5, float(trail_activate)) if trail_activate is not None else None
        )
        if activate is not None and trail_mult is not None and mfe >= activate:
            cand = (
                peak - float(trail_mult) * a
                if side == 1
                else peak + float(trail_mult) * a
            )
            trail = (
                max(trail if trail is not None else -np.inf, cand)
                if side == 1
                else min(trail if trail is not None else np.inf, cand)
            )
        if sid == "turtle_trend" and j >= 10:
            don = (
                float(x.iloc[j - 9 : j + 1]["low"].min())
                if side == 1
                else float(x.iloc[j - 9 : j + 1]["high"].max())
            )
            trail = (
                max(trail if trail is not None else -np.inf, don)
                if side == 1
                else min(trail if trail is not None else np.inf, don)
            )
        if j - (i + 1) + 1 >= scratch_b and mfe < scratch_r:
            final_px = close
            exit_j = j
            reason = "NO_PROGRESS_SCRATCH"
            break
    gross_parts.append(remaining * side * (float(final_px) - entry) / entry * 10_000)
    gross = sum(gross_parts)
    net = gross - cost_bps
    return {
        "strategy_id": sid,
        "child_id": signal.child_id,
        "symbol": "",
        "side": signal.side,
        "mode": signal.mode,
        "signal_ts": signal.signal_ts,
        "entry_ts": entry_ts,
        "exit_ts": int(x.iloc[exit_j]["ts_ms"]),
        "entry": entry,
        "exit": float(final_px),
        "reason": reason,
        "gross_bps": gross,
        "cost_bps": cost_bps,
        "net_bps": net,
        "mfe_r": mfe,
        "partial_done": partial_done,
        "remaining_at_terminal": remaining,
        "event_trace": list(signal.event_trace),
        "benchmark_ids": list(signal.benchmark_ids),
        "transfer": list(signal.transfer),
        "entry_source": "DONOR_STATE_MACHINE_V2",
        "exit_source": "DONOR_STATE_MACHINE_V2",
        "parent_entry_reused": False,
        "parent_exit_reused": False,
    }, int(exit_j)


def replay_strategy(
    sid: str,
    frames: Mapping[str, pd.DataFrame],
    cost_by_symbol: Mapping[str, float],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    signal_count = 0
    symbols = ("BTC-USDT", "ETH-USDT") if spec["microstructure_required"] else SYMS6
    for sym in symbols:
        x = frames[sym]
        state = MachineState()
        i = 101
        while i < len(x) - 1:
            sig = step_machine(sid, state, x, i, spec)
            state_counts[f"stage_{state.stage}"] += 1
            if sig is None:
                i += 1
                continue
            signal_count += 1
            trade, exit_j = simulate_trade(
                sid, sig, x, float(cost_by_symbol[sym]), spec
            )
            if trade is not None:
                trade["symbol"] = sym
                trades.append(trade)
            state.reset()
            i = max(i + 1, exit_j + 1)
    full = metrics(trades)
    split = split_metrics(trades)
    hold = split["holdout40"]
    gross_ok = bool(
        (full.get("GrossExp_bps_T") or -1e9)
        > (full.get("Cost_bps") or 0) / max(1, full.get("T") or 1)
    )
    economic = bool(
        (full.get("Net_bps") or 0) > 0
        and (full.get("PF") or 0) > 1
        and (hold.get("Net_bps") or 0) > 0
        and (hold.get("PF") or 0) > 1
        and (full.get("T") or 0) >= 30
    )
    return {
        "schema": "zel.a1.benchmark25.donor_state_machine_replay.v2",
        "state": (
            "PASS_DONOR_STATE_MACHINE_ECONOMIC"
            if economic
            else "FAIL_DONOR_STATE_MACHINE_ECONOMIC"
        ),
        "strategy_id": sid,
        "child_id": spec["child_id"],
        "timeframe": spec["timeframe"],
        "event_sequence": spec["event_sequence"],
        "parent_reuse": spec["parent_reuse"],
        "signals": signal_count,
        "metrics": full,
        "split": split,
        "gross_cost_gate": gross_ok,
        "exit_reasons": dict(Counter(t["reason"] for t in trades)),
        "partials": sum(bool(t["partial_done"]) for t in trades),
        "trades": trades,
        "research_only": True,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=1)
    p.add_argument("--only")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    validate_coverage()
    spec_all = load_spec()
    if args.self_test:
        return 0
    frames_by_tf, _ = prepare_frames(spec_all)
    authority = read_json(COST_PATH)
    snap_cache = {}

    def cost(sym: str) -> float:
        if sym not in snap_cache:
            snap_cache[sym] = cost_ev.fetch_execution_snapshot(sym, authority)
        return float(snap_cache[sym]["pretrade_verified_cost_bps"])

    costs = {s: cost(s) for s in SYMS6}
    ids = list(spec_all["children"])
    ids = (
        [args.only]
        if args.only
        else [s for n, s in enumerate(ids) if n % args.shard_count == args.shard_index]
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    errors = []
    for sid in ids:
        try:
            spec = spec_all["children"][sid]
            r = replay_strategy(
                sid, frames_by_tf[int(spec["timeframe_ms"])], costs, spec
            )
            out = args.out_dir / f"{sid}.json"
            out.write_text(json.dumps(r, indent=2, sort_keys=True) + "\n")
            rows.append(r)
            print(
                "SMV2_ROW="
                + json.dumps(
                    {
                        "strategy_id": sid,
                        "state": r["state"],
                        "metrics": r["metrics"],
                        "holdout": r["split"]["holdout40"],
                        "signals": r["signals"],
                        "partials": r["partials"],
                        "exit_reasons": r["exit_reasons"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as exc:
            err = {"strategy_id": sid, "error": f"{type(exc).__name__}:{exc}"}
            errors.append(err)
            print("SMV2_ERROR=" + json.dumps(err, sort_keys=True), flush=True)
    summary = {
        "schema": "zel.a1.benchmark25.donor_state_machine_shard.v2",
        "state": "PASS" if rows and not errors else "PARTIAL",
        "success_count": len(rows),
        "error_count": len(errors),
        "errors": errors,
        "strategies": [
            {
                "strategy_id": r["strategy_id"],
                "state": r["state"],
                "metrics": r["metrics"],
                "holdout": r["split"]["holdout40"],
            }
            for r in rows
        ],
    }
    (args.out_dir / "REPORT.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(
        "SMV2_DONE="
        + json.dumps(
            {"success": len(rows), "errors": len(errors), "shard": args.shard_index},
            sort_keys=True,
        )
    )
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
