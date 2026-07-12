from __future__ import annotations

import html
import importlib.util
import itertools
import json
import math
import os
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
WORKTREE = Path(os.environ.get("Q4R3_ROUTE_A_WORKTREE", "/tmp/q4r3-route-a-v3-2r-rescue"))
V2_PATH = WORKTREE / "tools" / "q4r3_route_a_raschke_v2_entry_exit_tournament.py"

RESULT_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_2r_rescue_tournament_latest.json"
TRADES_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_2r_rescue_trades_latest.json"
ROBUSTNESS_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_2r_rescue_robustness_latest.json"
DECISION_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_2r_rescue_decision_latest.json"
TRIAL_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_2r_rescue_trial_registration_latest.json"
HTML_OUT = ROOT / "runtime" / "raschke_v3_2r_rescue_tournament_latest.html"

WINDOWS = ("prior_holdout_90d", "second_holdout_90d")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
SIDES = ("long", "short")
MINUTE_MS = 60_000
TIMEOUT_MIN = 480
COOLDOWN_MIN = 60
LOSS_CAP_R = 0.50
COST_PRIMARY = 0.15
COST_STRESS = 0.20
BASELINE = "baseline_fixed_2R"
BOOTSTRAP_REPS = 600
BOOTSTRAP_BLOCK = 5

FEATURE_KEYS = (
    "ema_distance_atr",
    "ema_slope_atr",
    "adx",
    "candle_body_atr",
    "close_location",
    "volume_ratio",
    "macd_signal_spread_atr",
    "macd_signal_spread_prev_atr",
    "chop_score",
    "return_4h",
    "return_24h",
    "realized_vol_24h",
    "range_atr_6h",
    "volume_z_24h",
    "ema50_slope_atr_6h",
    "ema200_slope_atr_6h",
    "atr_percentile_120h",
)

GATE = {
    "retention_pct_min": 65.0,
    "combined_avg_R_improvement_min": 0.03,
    "prior_avg_R_min": 0.0,
    "second_avg_R_min": 0.0,
    "cost_0.20_avg_R_min_exclusive": 0.0,
    "profit_factor_min": 1.30,
    "mdd_vs_baseline_max_ratio": 1.05,
    "positive_symbols_min": 3,
    "positive_month_ratio_min": 0.50,
    "bootstrap_second_lower_min": -0.10,
}

POLICIES: Dict[str, Dict[str, Any]] = {
    BASELINE: {"kind": "fixed", "target_r": 2.0},
    "full_exit_1_5R": {"kind": "fixed", "target_r": 1.5},
    "full_exit_1_75R": {"kind": "fixed", "target_r": 1.75},
    "partial25_1R_runner_2R": {
        "kind": "partials",
        "target_r": 2.0,
        "partials": [(1.0, 0.25)],
    },
    "partial25_1_25R_runner_2R": {
        "kind": "partials",
        "target_r": 2.0,
        "partials": [(1.25, 0.25)],
    },
    "partial30_1_5R_runner_2R": {
        "kind": "partials",
        "target_r": 2.0,
        "partials": [(1.5, 0.30)],
    },
    "ladder20_1R_20_1_5R_runner_2R": {
        "kind": "partials",
        "target_r": 2.0,
        "partials": [(1.0, 0.20), (1.5, 0.20)],
    },
    "ratchet_BE_1R_lock_1R_at_1_5R": {
        "kind": "ratchet",
        "target_r": 2.0,
        "ratchets": [(1.0, 0.0), (1.5, 1.0)],
    },
    "trail_0_75R_after_1R": {
        "kind": "trail",
        "target_r": 2.0,
        "activate_r": 1.0,
        "trail_distance_r": 0.75,
    },
    "swing15_trail_after_1R": {
        "kind": "swing_trail",
        "target_r": 2.0,
        "activate_r": 1.0,
        "lookback_min": 15,
    },
    "speed_1_5R_hold_2R_if_le120m": {
        "kind": "speed_gate",
        "trigger_r": 1.5,
        "target_r": 2.0,
        "max_trigger_min": 120,
    },
    "momentum15_1_5R_hold_2R": {
        "kind": "momentum_gate",
        "trigger_r": 1.5,
        "target_r": 2.0,
        "lookback_min": 15,
    },
    "time_stop_120m_unless_1R": {
        "kind": "time_stop",
        "target_r": 2.0,
        "time_stop_min": 120,
        "required_mfe_r": 1.0,
    },
    "time_stop_240m_unless_1R": {
        "kind": "time_stop",
        "target_r": 2.0,
        "time_stop_min": 240,
        "required_mfe_r": 1.0,
    },
    "volatility_adaptive_target": {
        "kind": "vol_target",
        "target_r": 2.0,
        "low_target_r": 1.5,
        "mid_target_r": 2.0,
        "high_target_r": 2.5,
    },
    "side_target_long2_short1_5": {
        "kind": "side_target",
        "target_map": {"long": 2.0, "short": 1.5},
    },
    "fast_1_5R_momentum_3R_ratchet": {
        "kind": "conditional_3R",
        "trigger_r": 1.5,
        "fallback_exit_r": 1.5,
        "target_r": 3.0,
        "max_trigger_min": 120,
        "lookback_min": 15,
        "runner_stop_r": 1.0,
    },
}

TARGET_GRID = (1.25, 1.50, 1.75, 2.00, 2.25, 2.50)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V2 = load_module("q4r3_raschke_v3_2r_rescue_v2", V2_PATH)
Config = V2.Config
strategy = V2.strategy


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def directional_r(side: str, price: float, entry: float, risk: float) -> float:
    return (price - entry) / risk if side == "long" else (entry - price) / risk


def raw_path(window: str, symbol: str) -> Path:
    return V2.raw_path(window, symbol)


def path_contiguous(raw: pd.DataFrame, start: int, end: int) -> bool:
    path = raw.iloc[start : end + 1]
    if len(path) < 2:
        return True
    return bool((path["ts"].diff().dropna() == MINUTE_MS).all())


def feature_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    return {key: result.get(key) for key in FEATURE_KEYS if key in result}


def generate_signals(raw: pd.DataFrame, symbol: str, window_name: str) -> List[Dict[str, Any]]:
    bars = V2.BASE.make_bars(raw, V2.TIMEFRAME_MIN)
    config = Config(confirmation_mode="candle_direction")
    signals: List[Dict[str, Any]] = []
    for end_i in range(V2.WINDOW_BARS, len(bars)):
        frame = bars.iloc[end_i - V2.WINDOW_BARS : end_i]
        if not V2.window_is_contiguous(frame):
            continue
        signal_bar = bars.iloc[end_i - 1]
        next_raw_idx = int(signal_bar["raw_end_idx"]) + 1
        if next_raw_idx >= len(raw):
            continue
        result = strategy(
            frame[["ts", "open", "high", "low", "close", "volume"]].copy(),
            config=config,
        )
        if not isinstance(result, dict) or str(result.get("action", "")).lower() != "enter":
            continue
        if not V2.entry_pass("v2_proximity_guard", result):
            continue
        side = str(result.get("side", "")).lower()
        if side not in SIDES:
            continue
        entry = safe_float(result.get("entry"))
        stop = safe_float(result.get("sl"))
        if entry is None or stop is None or abs(entry - stop) <= 1e-12:
            continue
        signals.append(
            {
                "event_id": f"{window_name}|{symbol}|{side}|{int(signal_bar['ts'])}",
                "window": window_name,
                "symbol": symbol,
                "side": side,
                "signal_ts": int(signal_bar["ts"]),
                "entry_idx": next_raw_idx,
                "entry_ts": int(raw.iloc[next_raw_idx]["ts"]),
                "signal_entry": entry,
                "native_stop": stop,
                "features": feature_payload(result),
            }
        )
    return signals


def policy_target(policy: Dict[str, Any], signal: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    kind = str(policy["kind"])
    detail: Dict[str, Any] = {}
    if kind == "side_target":
        target = float(policy["target_map"][str(signal["side"])])
        return target, {"target_source": "side_map"}
    if kind == "vol_target":
        percentile = safe_float(signal.get("features", {}).get("atr_percentile_120h"))
        if percentile is None:
            return float(policy["mid_target_r"]), {"target_source": "fallback_mid", "atr_percentile_120h": None}
        if percentile < 33.0:
            target = float(policy["low_target_r"])
            band = "low"
        elif percentile < 67.0:
            target = float(policy["mid_target_r"])
            band = "mid"
        else:
            target = float(policy["high_target_r"])
            band = "high"
        return target, {"target_source": "atr_percentile", "atr_percentile_120h": percentile, "vol_band": band}
    if kind == "trained_side_target":
        target = float(policy["target_map"][str(signal["side"])])
        return target, {"target_source": "prior_trained_side_map"}
    return float(policy.get("target_r", 2.0)), detail


def close_momentum_r(raw: pd.DataFrame, current: int, lookback: int, side: str, entry: float, risk: float) -> Optional[float]:
    start = current - lookback
    if start < 0:
        return None
    first = float(raw.iloc[start]["close"])
    last = float(raw.iloc[current]["close"])
    return directional_r(side, last, first, risk)


def swing_stop_r(raw: pd.DataFrame, current: int, lookback: int, side: str, entry: float, risk: float) -> Optional[float]:
    start = max(0, current - lookback + 1)
    frame = raw.iloc[start : current + 1]
    if frame.empty:
        return None
    if side == "long":
        price = float(frame["low"].min())
    else:
        price = float(frame["high"].max())
    return directional_r(side, price, entry, risk)


def simulate_policy(raw: pd.DataFrame, signal: Dict[str, Any], policy_name: str, policy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    entry_idx = int(signal["entry_idx"])
    if entry_idx < 0 or entry_idx >= len(raw):
        return None
    entry = float(raw.iloc[entry_idx]["open"])
    risk = abs(float(signal["signal_entry"]) - float(signal["native_stop"]))
    if not math.isfinite(risk) or risk <= 0:
        return None
    side = str(signal["side"])
    target_r, target_detail = policy_target(policy, signal)
    kind = str(policy["kind"])
    last_idx = min(len(raw) - 1, entry_idx + TIMEOUT_MIN - 1)
    if not path_contiguous(raw, entry_idx, last_idx):
        return None

    stop_r = -LOSS_CAP_R
    remaining = 1.0
    realized_r = 0.0
    fired: set[float] = set()
    peak_r = 0.0
    max_mfe_r = 0.0
    pending_momentum_idx: Optional[int] = None
    pending_trigger_idx: Optional[int] = None
    activated = False
    ambiguity = False
    outcome = "TIMEOUT"
    exit_idx = last_idx
    exit_r = directional_r(side, float(raw.iloc[last_idx]["close"]), entry, risk)

    for current in range(entry_idx, last_idx + 1):
        elapsed = current - entry_idx
        bar = raw.iloc[current]
        open_r = directional_r(side, float(bar["open"]), entry, risk)
        high_price = float(bar["high"] if side == "long" else bar["low"])
        low_price = float(bar["low"] if side == "long" else bar["high"])
        high_r = directional_r(side, high_price, entry, risk)
        low_r = directional_r(side, low_price, entry, risk)

        if pending_momentum_idx is not None and current == pending_momentum_idx:
            trigger_idx = int(pending_trigger_idx if pending_trigger_idx is not None else current - 1)
            momentum = close_momentum_r(
                raw,
                trigger_idx,
                int(policy.get("lookback_min", 15)),
                side,
                entry,
                risk,
            )
            if momentum is None or momentum <= 0:
                outcome = "MOMENTUM_GATE_EXIT"
                exit_idx = current
                exit_r = open_r
                break
            pending_momentum_idx = None
            pending_trigger_idx = None
            activated = True

        stop_hit = low_r <= stop_r
        target_hit = high_r >= target_r
        if stop_hit and target_hit:
            ambiguity = True
            outcome = "STOP_TARGET_AMBIGUOUS"
            exit_idx = current
            exit_r = stop_r
            break
        if stop_hit:
            outcome = "RATCHET_STOP" if stop_r > -LOSS_CAP_R else "SL"
            exit_idx = current
            exit_r = stop_r
            break

        partials = list(policy.get("partials", []))
        crossed = sorted(
            (float(level), float(fraction))
            for level, fraction in partials
            if float(level) <= high_r and float(level) not in fired
        )
        for level, fraction in crossed:
            actual = min(fraction, remaining)
            if actual <= 0:
                continue
            realized_r += actual * level
            remaining -= actual
            fired.add(level)

        if target_hit:
            outcome = "TP"
            exit_idx = current
            exit_r = target_r
            break

        if kind == "speed_gate" and not activated and high_r >= float(policy["trigger_r"]):
            if elapsed > int(policy["max_trigger_min"]):
                outcome = "SLOW_TRIGGER_EXIT"
                exit_idx = current
                exit_r = float(policy["trigger_r"])
                break
            activated = True

        if kind == "momentum_gate" and not activated and pending_momentum_idx is None and high_r >= float(policy["trigger_r"]):
            if current + 1 > last_idx:
                outcome = "MOMENTUM_GATE_END_EXIT"
                exit_idx = current
                exit_r = float(policy["trigger_r"])
                break
            pending_trigger_idx = current
            pending_momentum_idx = current + 1

        if kind == "conditional_3R" and not activated and high_r >= float(policy["trigger_r"]):
            momentum = close_momentum_r(raw, current, int(policy["lookback_min"]), side, entry, risk)
            fast = elapsed <= int(policy["max_trigger_min"])
            if not fast or momentum is None or momentum <= 0:
                outcome = "CONDITIONAL_3R_FALLBACK_EXIT"
                exit_idx = current
                exit_r = float(policy["fallback_exit_r"])
                break
            activated = True
            stop_r = max(stop_r, float(policy["runner_stop_r"]))

        if kind == "time_stop" and elapsed >= int(policy["time_stop_min"]) and max_mfe_r < float(policy["required_mfe_r"]):
            outcome = "TIME_STOP"
            exit_idx = current
            exit_r = directional_r(side, float(bar["close"]), entry, risk)
            break

        # Ratchets and trails are applied for the next bar only. This prevents
        # using the current bar high to create a stop that the same bar low then hits.
        if kind == "ratchet":
            for trigger, new_stop in sorted(policy.get("ratchets", [])):
                if high_r >= float(trigger):
                    stop_r = max(stop_r, float(new_stop))
                    activated = True
        elif kind == "trail":
            if high_r >= float(policy["activate_r"]):
                activated = True
            if activated:
                stop_r = max(stop_r, max(peak_r, high_r) - float(policy["trail_distance_r"]))
        elif kind == "swing_trail":
            if high_r >= float(policy["activate_r"]):
                activated = True
            if activated:
                candidate = swing_stop_r(raw, current, int(policy["lookback_min"]), side, entry, risk)
                if candidate is not None:
                    stop_r = max(stop_r, min(candidate, high_r - 0.05))

        peak_r = max(peak_r, high_r)
        max_mfe_r = max(max_mfe_r, high_r)

    gross_r = realized_r + remaining * exit_r
    return {
        "event_id": signal["event_id"],
        "window": signal["window"],
        "symbol": signal["symbol"],
        "side": side,
        "signal_ts": int(signal["signal_ts"]),
        "entry_ts": int(raw.iloc[entry_idx]["ts"]),
        "exit_ts": int(raw.iloc[exit_idx]["ts"]),
        "entry": entry,
        "base_risk": risk,
        "risk_pct": float(risk / entry * 100.0),
        "gross_r": float(gross_r),
        "outcome": outcome,
        "policy": policy_name,
        "target_r": target_r,
        "stop_r_final": stop_r,
        "remaining_fraction": remaining,
        "partial_realized_r": realized_r,
        "triggered": activated or bool(fired),
        "ambiguity": ambiguity,
        "duration_min": int(exit_idx - entry_idx),
        "mfe_R_observed": float(max_mfe_r),
        "features": signal.get("features", {}),
        **target_detail,
    }


def replay_policy(
    raw: pd.DataFrame,
    signals: Sequence[Dict[str, Any]],
    policy_name: str,
    policy: Dict[str, Any],
    *,
    side_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    blocked_until = -1
    for signal in sorted(signals, key=lambda row: int(row["entry_ts"])):
        if side_filter is not None and str(signal["side"]) != side_filter:
            continue
        if int(signal["entry_ts"]) <= blocked_until:
            continue
        trade = simulate_policy(raw, signal, policy_name, policy)
        if trade is None:
            continue
        rows.append(trade)
        blocked_until = int(trade["exit_ts"]) + COOLDOWN_MIN * MINUTE_MS
    return rows


def cost_r(row: Dict[str, Any], cost_pct: float) -> float:
    return float(row["entry"]) * (float(cost_pct) / 100.0) / max(float(row["base_risk"]), 1e-12)


def net_r(row: Dict[str, Any], cost_pct: float) -> float:
    return float(row["gross_r"]) - cost_r(row, cost_pct)


def max_drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return float(worst)


def metrics(rows: Sequence[Dict[str, Any]], cost_pct: float) -> Dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (int(row["entry_ts"]), str(row["symbol"])))
    values = [net_r(row, cost_pct) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    by_symbol: Dict[str, List[float]] = defaultdict(list)
    by_side: Dict[str, List[float]] = defaultdict(list)
    by_month: Dict[str, List[float]] = defaultdict(list)
    outcomes = Counter()
    target_hits = 0
    for row, value in zip(ordered, values):
        by_symbol[str(row["symbol"])].append(value)
        by_side[str(row["side"])].append(value)
        month = pd.to_datetime(int(row["entry_ts"]), unit="ms", utc=True).strftime("%Y-%m")
        by_month[month].append(value)
        outcomes[str(row["outcome"])] += 1
        target_hits += int(str(row["outcome"]) == "TP")
    gross_profit = float(sum(wins))
    gross_loss = abs(float(sum(losses)))
    month_net = {key: float(sum(group)) for key, group in sorted(by_month.items())}
    return {
        "events": len(values),
        "avg_net_R": float(statistics.fmean(values)) if values else 0.0,
        "median_net_R": float(statistics.median(values)) if values else 0.0,
        "net_sum_R": float(sum(values)),
        "positive_rate_pct": float(len(wins) / len(values) * 100.0) if values else 0.0,
        "profit_factor_R": float(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "max_drawdown_R": max_drawdown(values),
        "positive_symbols": sum(1 for group in by_symbol.values() if sum(group) > 0),
        "by_symbol_net_R": {key: float(sum(group)) for key, group in sorted(by_symbol.items())},
        "by_side_net_R": {key: float(sum(group)) for key, group in sorted(by_side.items())},
        "by_month_net_R": month_net,
        "positive_month_ratio": float(sum(1 for value in month_net.values() if value > 0) / len(month_net)) if month_net else 0.0,
        "worst_month_R": min(month_net.values()) if month_net else 0.0,
        "target_hit_pct": float(target_hits / len(values) * 100.0) if values else 0.0,
        "outcome_counts": dict(sorted(outcomes.items())),
        "ambiguity_count": sum(int(bool(row.get("ambiguity"))) for row in ordered),
    }


def block_bootstrap_mean_ci(rows: Sequence[Dict[str, Any]], cost_pct: float, seed: int) -> Dict[str, Any]:
    values = [net_r(row, cost_pct) for row in sorted(rows, key=lambda row: int(row["entry_ts"]))]
    n = len(values)
    if n < 5:
        return {"n": n, "lower_95": None, "median": None, "upper_95": None}
    rng = random.Random(seed)
    block = min(BOOTSTRAP_BLOCK, n)
    samples: List[float] = []
    for _ in range(BOOTSTRAP_REPS):
        generated: List[float] = []
        while len(generated) < n:
            start = rng.randrange(0, n)
            for offset in range(block):
                generated.append(values[(start + offset) % n])
                if len(generated) >= n:
                    break
        samples.append(float(statistics.fmean(generated)))
    samples.sort()
    return {
        "n": n,
        "block_length": block,
        "repetitions": BOOTSTRAP_REPS,
        "lower_95": samples[int(0.025 * (len(samples) - 1))],
        "median": samples[int(0.50 * (len(samples) - 1))],
        "upper_95": samples[int(0.975 * (len(samples) - 1))],
    }


def choose_prior_side_targets(
    raw_cache: Dict[Tuple[str, str], pd.DataFrame],
    signals_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]],
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    selected: Dict[str, float] = {}
    audit: Dict[str, Any] = {}
    for side in SIDES:
        rows: List[Dict[str, Any]] = []
        for target in TARGET_GRID:
            trades: List[Dict[str, Any]] = []
            policy = {"kind": "fixed", "target_r": target}
            for symbol in SYMBOLS:
                key = (WINDOWS[0], symbol)
                trades.extend(
                    replay_policy(raw_cache[key], signals_by_key[key], f"train_target_{target}", policy, side_filter=side)
                )
            report = metrics(trades, COST_STRESS)
            shrinkage = 0.50 / math.sqrt(max(int(report["events"]), 1))
            score = float(report["avg_net_R"]) - shrinkage
            rows.append({"target_r": target, "score": score, "metrics_cost_0.20": report})
        rows.sort(key=lambda row: (float(row["score"]), float(row["metrics_cost_0.20"]["profit_factor_R"])), reverse=True)
        selected[side] = float(rows[0]["target_r"])
        audit[side] = {"selected_target_r": selected[side], "ranking": rows}
    return selected, audit


def pbo_month_blocks(policy_rows: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    months = sorted(
        {
            pd.to_datetime(int(row["entry_ts"]), unit="ms", utc=True).strftime("%Y-%m")
            for rows in policy_rows.values()
            for row in rows
        }
    )
    if len(months) < 4:
        return {"available": False, "months": months, "reason": "fewer_than_four_month_blocks"}
    matrix: Dict[str, Dict[str, float]] = {}
    for policy, rows in policy_rows.items():
        groups: Dict[str, List[float]] = defaultdict(list)
        for row in rows:
            month = pd.to_datetime(int(row["entry_ts"]), unit="ms", utc=True).strftime("%Y-%m")
            groups[month].append(net_r(row, COST_PRIMARY))
        matrix[policy] = {
            month: (float(statistics.fmean(groups[month])) if groups.get(month) else 0.0)
            for month in months
        }
    half = len(months) // 2
    combinations = list(itertools.combinations(months, half))
    overfit = 0
    records: List[Dict[str, Any]] = []
    selection = Counter()
    policies = sorted(policy_rows)
    for in_months_tuple in combinations:
        in_months = set(in_months_tuple)
        out_months = [month for month in months if month not in in_months]
        in_score = {
            policy: float(statistics.fmean(matrix[policy][month] for month in in_months))
            for policy in policies
        }
        selected = max(policies, key=lambda policy: (in_score[policy], policy))
        selection[selected] += 1
        out_score = {
            policy: float(statistics.fmean(matrix[policy][month] for month in out_months))
            for policy in policies
        }
        ranked = sorted(policies, key=lambda policy: (out_score[policy], policy))
        percentile = float(ranked.index(selected) / max(len(ranked) - 1, 1))
        is_overfit = percentile < 0.50
        overfit += int(is_overfit)
        records.append(
            {
                "selected_policy": selected,
                "in_months": sorted(in_months),
                "out_months": out_months,
                "in_score": in_score[selected],
                "out_score": out_score[selected],
                "out_rank_percentile": percentile,
                "below_median_out_of_sample": is_overfit,
            }
        )
    return {
        "available": True,
        "months": months,
        "splits": len(records),
        "pbo_estimate": float(overfit / len(records)) if records else None,
        "selection_frequency": dict(selection.most_common()),
        "records": records,
        "interpretation": "diagnostic_only_small_month_block_cscv",
    }


def gate_report(report: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    combined = report["combined_cost_0.15"]
    prior = report["prior_cost_0.15"]
    second = report["second_cost_0.15"]
    stress = report["combined_cost_0.20"]
    lower = report["bootstrap_second_cost_0.15"].get("lower_95")
    retention = float(combined["events"] / max(int(baseline["combined_cost_0.15"]["events"]), 1) * 100.0)
    checks = {
        "retention": retention >= GATE["retention_pct_min"],
        "combined_improvement": float(combined["avg_net_R"]) - float(baseline["combined_cost_0.15"]["avg_net_R"]) >= GATE["combined_avg_R_improvement_min"],
        "prior_nonnegative": float(prior["avg_net_R"]) >= GATE["prior_avg_R_min"],
        "second_nonnegative": float(second["avg_net_R"]) >= GATE["second_avg_R_min"],
        "cost_0.20_survival": float(stress["avg_net_R"]) > GATE["cost_0.20_avg_R_min_exclusive"],
        "profit_factor": float(combined["profit_factor_R"]) >= GATE["profit_factor_min"],
        "mdd_control": float(combined["max_drawdown_R"]) <= float(baseline["combined_cost_0.15"]["max_drawdown_R"]) * GATE["mdd_vs_baseline_max_ratio"],
        "symbol_breadth": int(combined["positive_symbols"]) >= GATE["positive_symbols_min"],
        "month_stability": float(combined["positive_month_ratio"]) >= GATE["positive_month_ratio_min"],
        "bootstrap_second": lower is not None and float(lower) >= GATE["bootstrap_second_lower_min"],
    }
    return {
        "gate_pass": all(checks.values()),
        "checks": checks,
        "failed_checks": [key for key, value in checks.items() if not value],
        "retention_pct": retention,
        "avg_R_improvement": float(combined["avg_net_R"]) - float(baseline["combined_cost_0.15"]["avg_net_R"]),
        "worst_window_avg_R": min(float(prior["avg_net_R"]), float(second["avg_net_R"])),
    }


def write_html(result: Dict[str, Any], robustness: Dict[str, Any], decision: Dict[str, Any]) -> None:
    rows = []
    for item in result["ranking"]:
        report = result["reports"][item["policy"]]
        combined = report["combined_cost_0.15"]
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['policy'])}</td>"
            f"<td>{report['gate']['gate_pass']}</td>"
            f"<td>{combined['events']}</td>"
            f"<td>{combined['avg_net_R']:.4f}</td>"
            f"<td>{report['second_cost_0.15']['avg_net_R']:.4f}</td>"
            f"<td>{combined['profit_factor_R']:.3f}</td>"
            f"<td>{combined['max_drawdown_R']:.3f}</td>"
            f"<td>{combined['positive_month_ratio']:.2f}</td>"
            f"<td>{html.escape(', '.join(report['gate']['failed_checks']))}</td>"
            "</tr>"
        )
    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Raschke 2R rescue tournament</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #334155;padding:7px}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>Raschke v3 multidimensional 2R rescue tournament</h1>",
            "<table><thead><tr><th>Policy</th><th>Gate</th><th>N</th><th>Avg R</th><th>Second Avg R</th><th>PF</th><th>MDD</th><th>Positive months</th><th>Failed checks</th></tr></thead><tbody>",
            "".join(rows),
            "</tbody></table><h2>Decision</h2><pre>",
            html.escape(json.dumps(decision, ensure_ascii=False, indent=2)),
            "</pre><h2>PBO diagnostic</h2><pre>",
            html.escape(json.dumps(robustness.get("pbo_month_blocks"), ensure_ascii=False, indent=2)),
            "</pre></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    raw_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
    raw_integrity: Dict[str, Any] = {}
    signals_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for window in WINDOWS:
        for symbol in SYMBOLS:
            key = (window, symbol)
            raw, integrity = V2.load_raw(raw_path(window, symbol))
            raw_cache[key] = raw
            raw_integrity[f"{window}|{symbol}"] = integrity
            signals_by_key[key] = generate_signals(raw, symbol, window)

    target_map, target_training_audit = choose_prior_side_targets(raw_cache, signals_by_key)
    policies = dict(POLICIES)
    policies["prior_trained_side_target"] = {
        "kind": "trained_side_target",
        "target_map": target_map,
        "training_window": WINDOWS[0],
    }

    trades_by_policy: Dict[str, List[Dict[str, Any]]] = {policy: [] for policy in policies}
    for policy_name, policy in policies.items():
        for window in WINDOWS:
            for symbol in SYMBOLS:
                key = (window, symbol)
                trades_by_policy[policy_name].extend(
                    replay_policy(raw_cache[key], signals_by_key[key], policy_name, policy)
                )

    reports: Dict[str, Any] = {}
    for index, (policy_name, rows) in enumerate(trades_by_policy.items()):
        prior = [row for row in rows if row["window"] == WINDOWS[0]]
        second = [row for row in rows if row["window"] == WINDOWS[1]]
        reports[policy_name] = {
            "policy": policies[policy_name],
            "prior_cost_0.15": metrics(prior, COST_PRIMARY),
            "second_cost_0.15": metrics(second, COST_PRIMARY),
            "combined_cost_0.15": metrics(rows, COST_PRIMARY),
            "combined_cost_0.20": metrics(rows, COST_STRESS),
            "bootstrap_prior_cost_0.15": block_bootstrap_mean_ci(prior, COST_PRIMARY, 1000 + index),
            "bootstrap_second_cost_0.15": block_bootstrap_mean_ci(second, COST_PRIMARY, 2000 + index),
        }

    baseline_report = reports[BASELINE]
    for policy_name, report in reports.items():
        report["gate"] = gate_report(report, baseline_report)

    ranking = sorted(
        (
            {
                "policy": policy_name,
                "gate_pass": bool(report["gate"]["gate_pass"]),
                "worst_window_avg_R": float(report["gate"]["worst_window_avg_R"]),
                "combined_avg_R": float(report["combined_cost_0.15"]["avg_net_R"]),
                "profit_factor_R": float(report["combined_cost_0.15"]["profit_factor_R"]),
                "max_drawdown_R": float(report["combined_cost_0.15"]["max_drawdown_R"]),
            }
            for policy_name, report in reports.items()
        ),
        key=lambda row: (
            bool(row["gate_pass"]),
            float(row["worst_window_avg_R"]),
            float(row["combined_avg_R"]),
            float(row["profit_factor_R"]),
            -float(row["max_drawdown_R"]),
        ),
        reverse=True,
    )

    pbo = pbo_month_blocks(trades_by_policy)
    robustness = {
        "status": "PASS_Q4R3_RASCHKE_V3_2R_RESCUE_ROBUSTNESS",
        "bootstrap_contract": {
            "repetitions": BOOTSTRAP_REPS,
            "block_length_trades": BOOTSTRAP_BLOCK,
            "chronological_circular_blocks": True,
        },
        "pbo_month_blocks": pbo,
        "multiple_testing_note": "PBO is diagnostic because only about six monthly blocks exist; no policy is promoted on ranking alone.",
        "target_training_audit": target_training_audit,
    }
    promising = [row["policy"] for row in ranking if bool(row["gate_pass"])]
    best = ranking[0]["policy"] if ranking else None
    decision = {
        "status": "PASS_Q4R3_RASCHKE_V3_2R_RESCUE_DECISION",
        "verdict": (
            "ROBUST_2R_RESCUE_CANDIDATE_FOUND_OBSERVER_ONLY"
            if promising
            else "NO_ROBUST_2R_RESCUE_GATE_PASS_RETAIN_BEST_AS_OBSERVER"
        ),
        "promising_policy_candidates": promising,
        "best_policy_by_preregistered_ranking": best,
        "prior_trained_side_target_map": target_map,
        "pbo_estimate": pbo.get("pbo_estimate"),
        "next_modules": (
            [
                "INDEPENDENT_EXPANDED_HISTORY_REPLAY",
                "THIRD_HOLDOUT_ONLY_AFTER_SAMPLE_AND_TRIAL_GATE",
                "SKILL_LEVEL_ENSEMBLE_WITHOUT_STRATEGY_MUTATION",
            ]
            if promising
            else [
                "FORWARD_OBSERVER_COLLECTION",
                "SAFE_NONRESERVED_HISTORY_ACQUISITION",
                "ENSEMBLE_OR_SKILL_LAYER_VALUE_ADD_TEST",
            ]
        ),
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
            "production_strategy_modified": False,
            "final_holdout_opened": False,
        },
    }
    result = {
        "status": "PASS_Q4R3_RASCHKE_V3_2R_RESCUE_TOURNAMENT",
        "verdict": "MULTIDIMENSIONAL_EXIT_AND_TARGET_RESCUE_COMPLETE_NO_STRATEGY_MUTATION",
        "entry_lane": "v2_proximity_guard_fixed",
        "loss_cap_R": LOSS_CAP_R,
        "timeout_min": TIMEOUT_MIN,
        "cooldown_min": COOLDOWN_MIN,
        "cost_levels_pct": [COST_PRIMARY, COST_STRESS],
        "policy_count": len(policies),
        "policies": policies,
        "prior_trained_side_target_map": target_map,
        "reports": reports,
        "ranking": ranking,
        "promising_policy_candidates": promising,
        "raw_integrity": raw_integrity,
        "signal_counts": {
            f"{window}|{symbol}": len(signals_by_key[(window, symbol)])
            for window in WINDOWS
            for symbol in SYMBOLS
        },
        "authority": decision["authority"],
    }
    trial = {
        "status": "PASS_Q4R3_RASCHKE_V3_2R_RESCUE_TRIAL_REGISTRATION",
        "trial_id": "q4r3_raschke_v3_2r_rescue_tournament_001",
        "pre_registered_before_result_review": True,
        "entry_lane": "v2_proximity_guard",
        "policies": list(policies),
        "gate": GATE,
        "ranking_order": [
            "gate_pass",
            "worst_window_avg_R",
            "combined_avg_R",
            "profit_factor_R",
            "negative_max_drawdown_R",
        ],
        "selection_controls": {
            "no_threshold_search": True,
            "prior_only_training_for_side_target": True,
            "second_window_never_used_to_select_side_target": True,
            "bootstrap": True,
            "month_block_pbo_diagnostic": True,
            "no_synthetic_oversampling": True,
            "no_final_holdout_access": True,
        },
    }

    write_html(result, robustness, decision)
    atomic_json(RESULT_OUT, result)
    atomic_json(TRADES_OUT, {"status": "PASS", "trades": trades_by_policy})
    atomic_json(ROBUSTNESS_OUT, robustness)
    atomic_json(DECISION_OUT, decision)
    atomic_json(TRIAL_OUT, trial)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    print(json.dumps({"ranking": ranking[:10]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
