from __future__ import annotations

import importlib.util
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


ROOT = Path("/home/z/z")
DEFAULT_REPLAY = ROOT / "tools" / "q4r3_route_a_a2_oos_replay.py"
REPLAY_FILE = Path(os.environ.get("Q4R3_A2_REPLAY_FILE", str(DEFAULT_REPLAY)))
PREV = ROOT / "runtime" / "q4r3_route_a_a2_oos_replay_latest.json"
OUT = ROOT / "runtime" / "q4r3_route_a_a2_forensic_decomposition_latest.json"

HORIZONS = (15, 30, 60)
COST_PCT = 0.10
MIN_GROUP_EVENTS = 8

# Predeclared before observing this forensic output. These are structural
# hypotheses, not a parameter grid.
TRIAL_REGISTRY = (
    "baseline",
    "long_only",
    "short_only",
    "beam_only",
    "reclaim_only",
    "persistent_regime_only",
    "ensemble_votes_ge_2",
    "trigger_specific_progress_stop",
)


def load_replay_module() -> Any:
    if not REPLAY_FILE.exists():
        raise FileNotFoundError(str(REPLAY_FILE))

    spec = importlib.util.spec_from_file_location(
        "q4r3_route_a_a2_oos_replay_runtime",
        REPLAY_FILE,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("REPLAY_MODULE_SPEC_FAILED")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def atr_series(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    previous = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(
        alpha=1.0 / max(length, 1),
        adjust=False,
        min_periods=max(length, 1),
    ).mean()


def efficiency_ratio(close: pd.Series, lookback: int = 20) -> float:
    if len(close) < lookback + 1:
        return 0.0
    segment = close.iloc[-(lookback + 1) :]
    direction = abs(float(segment.iloc[-1] - segment.iloc[0]))
    travel = float(segment.diff().abs().sum())
    return direction / travel if travel > 0 else 0.0


def volatility_percentile(frame: pd.DataFrame, lookback: int = 120) -> float:
    atr = atr_series(frame, 14)
    atr_pct = atr / frame["close"].replace(0, np.nan) * 100.0
    values = atr_pct.dropna().iloc[-lookback:]
    if values.empty:
        return 0.5
    current = float(values.iloc[-1])
    return float((values <= current).mean())


def directional_persistence(
    close: pd.Series,
    side: str,
    lookback: int = 8,
) -> float:
    returns = close.pct_change().dropna().iloc[-lookback:]
    if returns.empty:
        return 0.0
    if side == "long":
        return float((returns > 0).mean())
    return float((returns < 0).mean())


def ema_stack_vote(
    close: pd.Series,
    side: str,
    fast: int,
    mid: int,
    slow: int,
    slope_lookback: int = 3,
) -> bool:
    minimum = slow + slope_lookback + 2
    if len(close) < minimum:
        return False

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_mid = close.ewm(span=mid, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()

    fast_now = float(ema_fast.iloc[-1])
    mid_now = float(ema_mid.iloc[-1])
    slow_now = float(ema_slow.iloc[-1])
    fast_then = float(ema_fast.iloc[-1 - slope_lookback])
    mid_then = float(ema_mid.iloc[-1 - slope_lookback])

    if side == "long":
        return (
            fast_now > mid_now > slow_now
            and fast_now > fast_then
            and mid_now > mid_then
        )

    return (
        fast_now < mid_now < slow_now
        and fast_now < fast_then
        and mid_now < mid_then
    )


def ensemble_votes(close: pd.Series, side: str) -> int:
    speeds = (
        (5, 13, 34),
        (8, 21, 55),
        (13, 34, 89),
    )
    return sum(
        ema_stack_vote(close, side, fast, mid, slow)
        for fast, mid, slow in speeds
    )


def classify_regime(
    frame: pd.DataFrame,
    side: str,
    votes: int,
) -> Dict[str, Any]:
    er20 = efficiency_ratio(frame["close"], 20)
    vol_pct = volatility_percentile(frame, 120)
    persistence = directional_persistence(frame["close"], side, 8)

    if er20 >= 0.35 and persistence >= 0.625 and votes >= 2:
        label = "TREND_PERSISTENT"
    elif vol_pct >= 0.80 and er20 < 0.30:
        label = "VOLATILE_REVERSAL"
    else:
        label = "RANGE_NOISE"

    return {
        "regime": label,
        "efficiency_ratio_20": round(er20, 8),
        "volatility_percentile_120": round(vol_pct, 8),
        "directional_persistence_8": round(persistence, 8),
        "ensemble_votes": int(votes),
    }


def collect_enriched_signals(
    replay: Any,
    symbol: str,
    frame_1m: pd.DataFrame,
    bars_15m: pd.DataFrame,
    a2: Any,
) -> Dict[str, Any]:
    columns = ["ts", "open", "high", "low", "close", "volume"]
    signals: List[Dict[str, Any]] = []
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    errors: List[Dict[str, Any]] = []

    for end_i in range(replay.WINDOW_15M, len(bars_15m) + 1):
        window = bars_15m.iloc[end_i - replay.WINDOW_15M : end_i]

        if not replay.contiguous(window):
            counts["gap_reject"] += 1
            continue
        if not replay.strict_oos(window):
            counts["tuning_overlap_reject"] += 1
            continue

        strategy_frame = window[columns].copy()

        try:
            result = replay.invoke(a2, strategy_frame)
        except Exception as exc:
            counts["strategy_error"] += 1
            if len(errors) < 20:
                errors.append({"end_i": end_i, "error": repr(exc)})
            continue

        counts["windows"] += 1
        reason = str(result.get("why", "UNKNOWN"))
        reasons[reason] += 1

        side = replay.active_side(result)
        if not side:
            counts["hold"] += 1
            continue

        signal_bar = window.iloc[-1]
        entry_i = int(signal_bar["raw_end_idx"]) + 1
        if entry_i >= len(frame_1m):
            counts["missing_next_open"] += 1
            continue

        entry_row = frame_1m.iloc[entry_i]
        expected = signal_bar["ts_dt"] + pd.Timedelta(minutes=1)
        if entry_row["ts_dt"] != expected:
            counts["entry_alignment_error"] += 1
            continue

        levels = replay.levels_rebased(
            result,
            float(entry_row["open"]),
            side,
        )
        if levels is None:
            counts["invalid_native_levels"] += 1
            continue

        votes = ensemble_votes(strategy_frame["close"], side)
        regime = classify_regime(strategy_frame, side, votes)
        trigger = "beam" if bool(result.get("beam", False)) else "reclaim"

        counts["signals"] += 1
        counts[f"signal_{side}"] += 1
        counts[f"trigger_{trigger}"] += 1
        counts[f"regime_{regime['regime']}"] += 1
        counts[f"ensemble_votes_{votes}"] += 1

        signals.append(
            {
                "symbol": symbol,
                "side": side,
                "trigger": trigger,
                "signal_ts": str(signal_bar["ts_dt"]),
                "entry_i": entry_i,
                "entry_ts": str(entry_row["ts_dt"]),
                "entry_epoch": float(entry_row["ts_dt"].timestamp()),
                "entry_hour_utc": int(entry_row["ts_dt"].hour),
                "entry": levels["entry"],
                "sl": levels["sl"],
                "tp": levels["tp"],
                "risk_pct": levels["risk_pct"],
                "reward_pct": levels["reward_pct"],
                "rr": levels["rr"],
                "why": reason,
                "atr_pct": safe_float(result.get("atr_pct")),
                "ribbon_width_atr": safe_float(
                    result.get("ribbon_width_atr")
                ),
                "expansion_ratio": safe_float(
                    result.get("expansion_ratio")
                ),
                "fast_slope_atr": safe_float(
                    result.get("fast_slope_atr")
                ),
                "mid_slope_atr": safe_float(
                    result.get("mid_slope_atr")
                ),
                **regime,
            }
        )

    return {
        "signals": signals,
        "counts": dict(counts),
        "reason_top20": reasons.most_common(20),
        "errors": errors,
    }


def signed_return_pct(side: str, entry: float, price: float) -> float:
    if side == "long":
        return (price / entry - 1.0) * 100.0
    return (entry / price - 1.0) * 100.0


def simulate_one_enriched(
    frame: pd.DataFrame,
    signal: Dict[str, Any],
    timeout_min: int,
) -> Dict[str, Any]:
    entry_i = int(signal["entry_i"])
    entry = float(signal["entry"])
    sl = float(signal["sl"])
    tp = float(signal["tp"])
    side = str(signal["side"])
    risk_pct = float(signal["risk_pct"])

    last_i = min(len(frame) - 1, entry_i + timeout_min - 1)
    mfe_pct = 0.0
    mae_pct = 0.0
    ambiguity = False
    snapshots: Dict[str, Any] = {}

    for index in range(entry_i, last_i + 1):
        row = frame.iloc[index]
        high = float(row["high"])
        low = float(row["low"])

        if side == "long":
            mfe_pct = max(mfe_pct, (high / entry - 1.0) * 100.0)
            mae_pct = min(mae_pct, (low / entry - 1.0) * 100.0)
            tp_hit = high >= tp
            sl_hit = low <= sl
        else:
            mfe_pct = max(mfe_pct, (entry / low - 1.0) * 100.0)
            mae_pct = min(mae_pct, (entry / high - 1.0) * 100.0)
            tp_hit = low <= tp
            sl_hit = high >= sl

        elapsed = index - entry_i + 1
        if elapsed in HORIZONS:
            close_now = float(row["close"])
            current_pct = signed_return_pct(side, entry, close_now)
            snapshots[str(elapsed)] = {
                "current_R": round(current_pct / risk_pct, 8),
                "mfe_R": round(mfe_pct / risk_pct, 8),
                "mae_R": round(mae_pct / risk_pct, 8),
                "close": close_now,
            }

        if tp_hit and sl_hit:
            result = "BOTH_SAME_1M_BAR_SL"
            gross_pct = -risk_pct
            ambiguity = True
            exit_i = index
            break
        if sl_hit:
            result = "SL"
            gross_pct = -risk_pct
            exit_i = index
            break
        if tp_hit:
            result = "TP"
            gross_pct = float(signal["reward_pct"])
            exit_i = index
            break
    else:
        exit_i = last_i
        exit_close = float(frame.iloc[exit_i]["close"])
        gross_pct = signed_return_pct(side, entry, exit_close)
        result = "TIMEOUT"

    for horizon in HORIZONS:
        key = str(horizon)
        if key not in snapshots:
            snapshots[key] = None

    net_pct = gross_pct - COST_PCT

    return {
        **signal,
        "exit_i": exit_i,
        "exit_ts": str(frame.iloc[exit_i]["ts_dt"]),
        "result": result,
        "gross_pct": round(gross_pct, 8),
        "net_pct": round(net_pct, 8),
        "net_R": round(net_pct / risk_pct, 8),
        "mfe_pct": round(mfe_pct, 8),
        "mae_pct": round(mae_pct, 8),
        "mfe_R": round(mfe_pct / risk_pct, 8),
        "mae_R": round(mae_pct / risk_pct, 8),
        "bars_1m": exit_i - entry_i + 1,
        "same_1m_bar_ambiguity": ambiguity,
        "progress": snapshots,
    }


def simulate_portfolio(
    replay: Any,
    frames: Dict[str, pd.DataFrame],
    signals: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        grouped[str(signal["symbol"])].append(signal)

    trades: List[Dict[str, Any]] = []

    for symbol, symbol_signals in grouped.items():
        next_allowed = 0
        for signal in sorted(
            symbol_signals,
            key=lambda row: int(row["entry_i"]),
        ):
            if int(signal["entry_i"]) < next_allowed:
                continue

            trade = simulate_one_enriched(
                frames[symbol],
                signal,
                replay.TIMEOUT_MIN,
            )
            trades.append(trade)
            next_allowed = int(signal["entry_i"]) + max(
                replay.COOLDOWN_MIN,
                int(trade["bars_1m"]),
            )

    return sorted(trades, key=lambda row: float(row["entry_epoch"]))


def max_drawdown_r(trades: Iterable[Dict[str, Any]]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0

    for trade in sorted(trades, key=lambda row: float(row["entry_epoch"])):
        equity += float(trade["net_R"])
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)

    return maximum


def summarize(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {
            "events": 0,
            "avg_net_R": 0.0,
            "net_sum_R": 0.0,
            "positive_rate_pct": 0.0,
            "profit_factor_R": 0.0,
            "max_drawdown_R": 0.0,
            "positive_symbols": 0,
        }

    values = [float(trade["net_R"]) for trade in trades]
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    by_symbol_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for trade in trades:
        by_symbol_rows[str(trade["symbol"])].append(trade)

    positive_symbols = sum(
        sum(float(row["net_R"]) for row in rows) > 0
        for rows in by_symbol_rows.values()
    )

    count = len(trades)
    return {
        "events": count,
        "avg_net_R": round(sum(values) / count, 8),
        "median_net_R": round(statistics.median(values), 8),
        "net_sum_R": round(sum(values), 8),
        "positive_rate_pct": round(
            sum(value > 0 for value in values) / count * 100.0,
            3,
        ),
        "tp_rate_pct": round(
            sum(trade["result"] == "TP" for trade in trades)
            / count
            * 100.0,
            3,
        ),
        "sl_rate_pct": round(
            sum(
                trade["result"] in {"SL", "BOTH_SAME_1M_BAR_SL"}
                for trade in trades
            )
            / count
            * 100.0,
            3,
        ),
        "timeout_rate_pct": round(
            sum(trade["result"] == "TIMEOUT" for trade in trades)
            / count
            * 100.0,
            3,
        ),
        "profit_factor_R": (
            round(gains / losses, 6) if losses > 0 else 999.0
        ),
        "max_drawdown_R": round(max_drawdown_r(trades), 8),
        "positive_symbols": positive_symbols,
        "ambiguity_count": sum(
            bool(trade["same_1m_bar_ambiguity"]) for trade in trades
        ),
    }


def grouped_summary(
    trades: List[Dict[str, Any]],
    key: str,
) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[str(trade.get(key, "UNKNOWN"))].append(trade)

    return {
        name: summarize(rows)
        for name, rows in sorted(groups.items())
    }


def progress_bucket_summary(
    trades: List[Dict[str, Any]],
    horizon: int,
) -> Dict[str, Any]:
    available = [
        trade for trade in trades
        if trade["progress"].get(str(horizon)) is not None
    ]
    stalled = [
        trade for trade in available
        if float(trade["progress"][str(horizon)]["mfe_R"]) < 0.35
        and float(trade["progress"][str(horizon)]["current_R"]) <= 0.0
    ]
    progressing = [trade for trade in available if trade not in stalled]

    return {
        "available": len(available),
        "stalled": summarize(stalled),
        "progressing": summarize(progressing),
    }


def apply_progress_stop(
    frames: Dict[str, pd.DataFrame],
    trades: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []

    for trade in trades:
        trigger = str(trade["trigger"])
        horizon = 30 if trigger == "beam" else 60
        snapshot = trade["progress"].get(str(horizon))

        should_stop = (
            snapshot is not None
            and int(trade["bars_1m"]) > horizon
            and float(snapshot["mfe_R"]) < (
                0.35 if trigger == "beam" else 0.50
            )
            and float(snapshot["current_R"]) <= 0.0
        )

        if not should_stop:
            output.append(dict(trade))
            continue

        frame = frames[str(trade["symbol"])]
        exit_i = int(trade["entry_i"]) + horizon - 1
        exit_close = float(frame.iloc[exit_i]["close"])
        gross_pct = signed_return_pct(
            str(trade["side"]),
            float(trade["entry"]),
            exit_close,
        )
        net_pct = gross_pct - COST_PCT
        replaced = dict(trade)
        replaced.update(
            {
                "exit_i": exit_i,
                "exit_ts": str(frame.iloc[exit_i]["ts_dt"]),
                "result": f"PROGRESS_STOP_{horizon}M",
                "gross_pct": round(gross_pct, 8),
                "net_pct": round(net_pct, 8),
                "net_R": round(
                    net_pct / float(trade["risk_pct"]),
                    8,
                ),
                "bars_1m": horizon,
            }
        )
        output.append(replaced)

    return sorted(output, key=lambda row: float(row["entry_epoch"]))


def filter_trials(
    trades: List[Dict[str, Any]],
    frames: Dict[str, pd.DataFrame],
) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "baseline": list(trades),
        "long_only": [
            trade for trade in trades if trade["side"] == "long"
        ],
        "short_only": [
            trade for trade in trades if trade["side"] == "short"
        ],
        "beam_only": [
            trade for trade in trades if trade["trigger"] == "beam"
        ],
        "reclaim_only": [
            trade for trade in trades if trade["trigger"] == "reclaim"
        ],
        "persistent_regime_only": [
            trade
            for trade in trades
            if trade["regime"] == "TREND_PERSISTENT"
        ],
        "ensemble_votes_ge_2": [
            trade
            for trade in trades
            if int(trade["ensemble_votes"]) >= 2
        ],
        "trigger_specific_progress_stop": apply_progress_stop(
            frames,
            trades,
        ),
    }


def candidate_assessment(
    baseline: Dict[str, Any],
    trial: Dict[str, Any],
) -> Dict[str, Any]:
    events = int(trial["events"])
    mdd_base = float(baseline["max_drawdown_R"])
    mdd_trial = float(trial["max_drawdown_R"])
    mdd_reduction = (
        (mdd_base - mdd_trial) / mdd_base * 100.0
        if mdd_base > 0
        else 0.0
    )

    hard_gate = (
        events >= 50
        and float(trial["avg_net_R"]) >= 0.15
        and float(trial["profit_factor_R"]) >= 1.20
        and mdd_trial <= 8.0
        and int(trial["positive_symbols"]) >= 3
    )
    promising = (
        events >= 50
        and float(trial["avg_net_R"])
        >= float(baseline["avg_net_R"]) + 0.10
        and float(trial["profit_factor_R"]) >= 1.10
        and mdd_reduction >= 25.0
        and int(trial["positive_symbols"]) >= 3
    )

    return {
        "hard_gate": hard_gate,
        "promising_hypothesis": promising,
        "mdd_reduction_pct": round(mdd_reduction, 3),
        "sample_retention_pct": round(
            events / max(int(baseline["events"]), 1) * 100.0,
            3,
        ),
    }


def main() -> None:
    replay = load_replay_module()
    a2 = replay.load_a2_module()

    frames: Dict[str, pd.DataFrame] = {}
    all_signals: List[Dict[str, Any]] = []
    audits: Dict[str, Any] = {}
    hard_fail: List[str] = []

    for symbol in replay.SYMBOLS:
        try:
            frame = replay.load_1m(symbol)
            bars = replay.make_15m(frame)
            pack = collect_enriched_signals(
                replay,
                symbol,
                frame,
                bars,
                a2,
            )
        except Exception as exc:
            hard_fail.append(f"{symbol}:{repr(exc)}")
            continue

        frames[symbol] = frame
        all_signals.extend(pack["signals"])
        audits[symbol] = {
            "rows_1m": len(frame),
            "counts": pack["counts"],
            "reason_top20": pack["reason_top20"],
            "errors": pack["errors"],
        }
        if pack["errors"]:
            hard_fail.append(f"{symbol}:STRATEGY_RUNTIME_ERROR")

    trades = simulate_portfolio(replay, frames, all_signals)
    baseline = summarize(trades)

    previous = json.loads(PREV.read_text()) if PREV.exists() else {}
    expected = previous.get("a2_standalone", {}).get("summary", {})
    parity = {
        "events_expected": expected.get("events"),
        "events_actual": baseline["events"],
        "avg_R_expected": expected.get("avg_net_R"),
        "avg_R_actual": baseline["avg_net_R"],
        "net_sum_R_expected": expected.get("net_sum_R"),
        "net_sum_R_actual": baseline["net_sum_R"],
    }
    parity["pass"] = (
        parity["events_expected"] == parity["events_actual"]
        and parity["avg_R_expected"] is not None
        and abs(
            float(parity["avg_R_expected"])
            - float(parity["avg_R_actual"])
        )
        <= 1e-6
        and parity["net_sum_R_expected"] is not None
        and abs(
            float(parity["net_sum_R_expected"])
            - float(parity["net_sum_R_actual"])
        )
        <= 1e-6
    )

    if not parity["pass"]:
        hard_fail.append("BASELINE_PARITY_FAIL")
    if baseline.get("ambiguity_count", 0):
        hard_fail.append("ONE_MINUTE_AMBIGUITY")

    trials = filter_trials(trades, frames)
    trial_summaries: Dict[str, Any] = {}

    for name in TRIAL_REGISTRY:
        summary = summarize(trials[name])
        trial_summaries[name] = {
            "summary": summary,
            "assessment": candidate_assessment(baseline, summary),
        }

    hard_gate_names = [
        name
        for name, row in trial_summaries.items()
        if name != "baseline" and row["assessment"]["hard_gate"]
    ]
    promising_names = [
        name
        for name, row in trial_summaries.items()
        if name != "baseline"
        and row["assessment"]["promising_hypothesis"]
    ]

    if hard_fail:
        verdict = "HOLD_A2_FORENSIC_TECHNICAL_FAIL"
    elif hard_gate_names:
        verdict = "A2_V2_CANDIDATE_REQUIRES_FROZEN_LONGER_OOS"
    elif promising_names:
        verdict = "A2_V2_PROMISING_HYPOTHESIS_REQUIRES_FROZEN_OOS"
    else:
        verdict = "A2_V2_NO_ROBUST_HYPOTHESIS_YET"

    payload = {
        "status": (
            "PASS_Q4R3_ROUTE_A_A2_FORENSIC_DECOMPOSITION"
            if not hard_fail
            else "HOLD_Q4R3_ROUTE_A_A2_FORENSIC_DECOMPOSITION"
        ),
        "verdict": verdict,
        "hard_fail": sorted(set(hard_fail)),
        "scope": (
            "A2 baseline parity + side/trigger/symbol/regime/"
            "multi-speed/progress decomposition; diagnostic only"
        ),
        "trial_registry": {
            "count": len(TRIAL_REGISTRY),
            "names": list(TRIAL_REGISTRY),
            "predeclared": True,
            "selection_warning": (
                "No trial may be promoted on this same 30-day sample. "
                "Any candidate must be frozen and tested on longer unseen data."
            ),
        },
        "baseline_parity": parity,
        "baseline": baseline,
        "decomposition": {
            "by_symbol": grouped_summary(trades, "symbol"),
            "by_side": grouped_summary(trades, "side"),
            "by_trigger": grouped_summary(trades, "trigger"),
            "by_regime": grouped_summary(trades, "regime"),
            "by_ensemble_votes": grouped_summary(
                trades,
                "ensemble_votes",
            ),
            "by_entry_hour_utc": grouped_summary(
                trades,
                "entry_hour_utc",
            ),
            "progress_15m": progress_bucket_summary(trades, 15),
            "progress_30m": progress_bucket_summary(trades, 30),
            "progress_60m": progress_bucket_summary(trades, 60),
        },
        "trials": trial_summaries,
        "hard_gate_candidates": hard_gate_names,
        "promising_candidates": promising_names,
        "per_symbol_signal_audit": audits,
        "review_trades": {
            "best": sorted(
                trades,
                key=lambda row: float(row["net_R"]),
                reverse=True,
            )[:5],
            "worst": sorted(
                trades,
                key=lambda row: float(row["net_R"]),
            )[:5],
            "stalled_30m": [
                trade
                for trade in trades
                if trade["progress"].get("30") is not None
                and float(trade["progress"]["30"]["mfe_R"]) < 0.35
                and float(trade["progress"]["30"]["current_R"]) <= 0.0
            ][:10],
        },
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "paper_request_written": False,
        "live_execution_allowed": False,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": payload["status"],
                "verdict": verdict,
                "hard_fail": payload["hard_fail"],
                "baseline_parity": parity,
                "baseline": baseline,
                "by_symbol": payload["decomposition"]["by_symbol"],
                "by_side": payload["decomposition"]["by_side"],
                "by_trigger": payload["decomposition"]["by_trigger"],
                "by_regime": payload["decomposition"]["by_regime"],
                "progress_30m": payload["decomposition"]["progress_30m"],
                "progress_60m": payload["decomposition"]["progress_60m"],
                "trials": trial_summaries,
                "hard_gate_candidates": hard_gate_names,
                "promising_candidates": promising_names,
                "out": str(OUT),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
