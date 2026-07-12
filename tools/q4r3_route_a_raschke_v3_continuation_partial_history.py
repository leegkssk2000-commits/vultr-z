from __future__ import annotations

import html
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
DATA_ROOT = ROOT / "data"
LEDGER_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_all_signal_ledger_latest.json"
TRANSITION_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_transition_giveback_latest.json"
BOCPD_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_bocpd_observer_latest.json"
INVENTORY_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_sample_inventory_latest.json"

CONTINUATION_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_15r_to_2r_continuation_latest.json"
POLICY_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_partial_runner_replay_latest.json"
HISTORY_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_safe_history_integrity_latest.json"
BOCPD_MONTH_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_bocpd_month_validation_latest.json"
DECISION_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_continuation_decision_latest.json"
TRIAL_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_partial_runner_trial_registration_latest.json"
HTML_OUT = ROOT / "runtime" / "raschke_v3_continuation_partial_history_latest.html"

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
WINDOWS = ("prior_holdout_90d", "second_holdout_90d")
MINUTE_MS = 60_000
TIMEOUT_MIN = 480
COOLDOWN_MIN = 60
LOSS_CAP_R = 0.50
COST_LEVELS = (0.15, 0.20)

RAW_PATHS = {
    "prior_holdout_90d": ROOT / "data" / "oos_a2" / "frozen_pre30d",
    "second_holdout_90d": ROOT / "data" / "oos_a3" / "raschke_second_holdout",
}
RAW_SUFFIX = {
    "prior_holdout_90d": "_1m_90d_pre30d.json",
    "second_holdout_90d": "_1m_90d_pre90d.json",
}

POLICIES: Dict[str, Dict[str, Any]] = {
    "baseline_fixed_2R": {
        "target_R": 2.0,
        "trigger_R": None,
        "partial_fraction": 0.0,
        "move_stop_to_R": None,
        "role": "control",
    },
    "full_exit_1_5R": {
        "target_R": 1.5,
        "trigger_R": None,
        "partial_fraction": 0.0,
        "move_stop_to_R": None,
        "role": "diagnostic_ceiling",
    },
    "partial30_at_1_5R_keep_stop": {
        "target_R": 2.0,
        "trigger_R": 1.5,
        "partial_fraction": 0.30,
        "move_stop_to_R": None,
        "role": "partial_runner_original_risk",
    },
    "partial30_at_1_5R_be_runner": {
        "target_R": 2.0,
        "trigger_R": 1.5,
        "partial_fraction": 0.30,
        "move_stop_to_R": 0.0,
        "role": "partial_runner_breakeven",
    },
}

POLICY_GATE = {
    "retention_pct_min": 70.0,
    "combined_avg_R_improvement_min": 0.03,
    "second_avg_R_floor": -0.05,
    "cost_0.20_avg_R_min_exclusive": 0.0,
    "profit_factor_min": 1.25,
    "positive_symbols_min": 3,
    "nonnegative_month_ratio_min": 2.0 / 3.0,
    "mdd_not_worse": True,
}

RESERVED_PATH_TOKENS = (
    "third",
    "holdout3",
    "holdout_3",
    "oos_a4",
    "oos_a5",
    "final",
    "sealed",
    "untouched",
    "forward",
    "paper",
    "live",
    "shadow",
)
MAX_HISTORY_GROUPS = 10
MAX_GAP_RANGES = 1
MAX_MISSING_MINUTES = 5
MAX_SYMBOL_SPAN_SKEW_MS = 86_400_000

PRE_ENTRY_FEATURES = (
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

RESEARCH_CONTRACT = {
    "continuation": "Separate reaching 1.5R from converting 1.5R to the final 2R endpoint.",
    "exit_replay": "Every exit policy is replayed from all raw signals with its own exit time and 60-minute cooldown; no post-hoc deletion is allowed.",
    "history": "History inspection is read-only. Reserved/final/forward/shadow paths, overlapping periods and non-contiguous data are ineligible.",
    "selection": "Four exit policies and all gates are pre-registered; no threshold search is performed.",
    "safety": "No strategy, registry, paper, live, order, execution or final-holdout mutation is permitted.",
}


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    payload = json.loads(path.read_text(errors="ignore"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"INVALID_JSON_OBJECT:{path}")
    return payload


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


def timestamp_ms(value: Any) -> int:
    stamp = int(float(value))
    return stamp * 1000 if abs(stamp) < 100_000_000_000 else stamp


def raw_path(window: str, symbol: str) -> Path:
    return RAW_PATHS[window] / f"{symbol}{RAW_SUFFIX[window]}"


def load_raw(path: Path) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    payload = load_json(path)
    rows = payload.get("rows", [])
    records: List[Dict[str, Any]] = []
    malformed = 0
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            malformed += 1
            continue
        try:
            records.append(
                {
                    "ts": timestamp_ms(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        except (TypeError, ValueError, OverflowError):
            malformed += 1
    frame = pd.DataFrame(records)
    if frame.empty:
        raise RuntimeError(f"EMPTY_RAW:{path}")
    before = len(frame)
    frame = frame.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
    frame["raw_idx"] = range(len(frame))
    diffs = frame["ts"].diff().dropna()
    gaps = diffs[diffs != MINUTE_MS]
    missing = int(sum(max(int(diff // MINUTE_MS) - 1, 0) for diff in gaps.tolist()))
    return frame, {
        "path": str(path),
        "rows": len(frame),
        "duplicates": before - len(frame),
        "malformed": malformed,
        "start_ts": int(frame.iloc[0]["ts"]),
        "end_ts": int(frame.iloc[-1]["ts"]),
        "gap_ranges": int(len(gaps)),
        "missing_minutes": missing,
        "strict_or_sparse_valid": bool(len(gaps) <= MAX_GAP_RANGES and missing <= MAX_MISSING_MINUTES),
    }


def path_contiguous(raw: pd.DataFrame, start_idx: int, end_idx: int) -> bool:
    path = raw.iloc[start_idx : end_idx + 1]
    return True if len(path) < 2 else bool((path["ts"].diff().dropna() == MINUTE_MS).all())


def class_name(event: Dict[str, Any]) -> str:
    label = str(event.get("label", event.get("outcome", "UNKNOWN")))
    if label in {"TP_FIRST", "TP", "PARTIAL_TP"}:
        return "TP"
    if label.startswith("SL_FIRST") or label == "SL":
        return "SL"
    if label in {"TIMEOUT"}:
        return "TIMEOUT"
    if "BE" in label:
        return "BE"
    return label


def directional_r(side: str, price: float, entry: float, risk: float) -> float:
    direction = 1.0 if side == "long" else -1.0
    return float(direction * (price - entry) / risk)


def event_index(raw: pd.DataFrame, entry_ts: int) -> Optional[int]:
    matches = raw.index[raw["ts"] == int(entry_ts)].tolist()
    return int(matches[0]) if matches else None


def simulate_policy(raw: pd.DataFrame, event: Dict[str, Any], policy_name: str) -> Optional[Dict[str, Any]]:
    policy = POLICIES[policy_name]
    entry_ts = int(event.get("entry_ts", 0))
    idx = event_index(raw, entry_ts)
    if idx is None:
        return None
    entry = safe_float(event.get("entry"))
    risk = safe_float(event.get("base_risk"))
    side = str(event.get("side", ""))
    if entry is None or risk is None or risk <= 0 or side not in {"long", "short"}:
        return None
    target_r = float(policy["target_R"])
    trigger_r = safe_float(policy.get("trigger_R"))
    partial_fraction = float(policy["partial_fraction"])
    move_stop_to_r = safe_float(policy.get("move_stop_to_R"))
    last_idx = min(len(raw) - 1, idx + TIMEOUT_MIN - 1)
    if not path_contiguous(raw, idx, last_idx):
        return None

    activated = False
    trigger_idx: Optional[int] = None
    partial_realized_r = 0.0
    remaining_fraction = 1.0
    exit_idx = last_idx
    exit_r = directional_r(side, float(raw.iloc[last_idx]["close"]), entry, risk)
    outcome = "TIMEOUT"
    ambiguity = False
    post_trigger_floor_r: Optional[float] = None

    for current in range(idx, last_idx + 1):
        bar = raw.iloc[current]
        high_r = directional_r(side, float(bar["high"] if side == "long" else bar["low"]), entry, risk)
        low_r = directional_r(side, float(bar["low"] if side == "long" else bar["high"]), entry, risk)
        active_stop_r = move_stop_to_r if activated and move_stop_to_r is not None else -LOSS_CAP_R
        stop_hit = low_r <= active_stop_r
        target_hit = high_r >= target_r

        if activated:
            post_trigger_floor_r = low_r if post_trigger_floor_r is None else min(post_trigger_floor_r, low_r)

        if stop_hit and target_hit:
            ambiguity = True
            exit_idx = current
            exit_r = active_stop_r
            outcome = "BE" if active_stop_r == 0.0 else "SL"
            break
        if stop_hit:
            exit_idx = current
            exit_r = active_stop_r
            outcome = "BE" if active_stop_r == 0.0 else "SL"
            break
        if target_hit:
            exit_idx = current
            exit_r = target_r
            outcome = "TP"
            break
        if not activated and trigger_r is not None and high_r >= trigger_r:
            activated = True
            trigger_idx = current
            partial_realized_r = partial_fraction * trigger_r
            remaining_fraction = 1.0 - partial_fraction
            post_trigger_floor_r = low_r

    gross_r = partial_realized_r + remaining_fraction * exit_r
    if activated and outcome == "BE" and partial_fraction > 0:
        outcome = "PARTIAL_BE"
    elif activated and outcome == "SL" and partial_fraction > 0:
        outcome = "PARTIAL_SL"
    elif activated and outcome == "TIMEOUT" and partial_fraction > 0:
        outcome = "PARTIAL_TIMEOUT"
    elif activated and outcome == "TP" and partial_fraction > 0:
        outcome = "PARTIAL_TP"
    return {
        "policy": policy_name,
        "role": policy["role"],
        "window": event.get("window"),
        "symbol": event.get("symbol"),
        "side": side,
        "signal_ts": int(event.get("signal_ts", 0)),
        "entry_ts": entry_ts,
        "exit_ts": int(raw.iloc[exit_idx]["ts"]),
        "entry": entry,
        "base_risk": risk,
        "gross_R": float(gross_r),
        "outcome": outcome,
        "triggered_1_5R": activated,
        "trigger_ts": int(raw.iloc[trigger_idx]["ts"]) if trigger_idx is not None else None,
        "minutes_to_trigger": int(trigger_idx - idx) if trigger_idx is not None else None,
        "post_trigger_floor_R": post_trigger_floor_r,
        "partial_fraction": partial_fraction,
        "ambiguity": ambiguity,
    }


def cost_r(trade: Dict[str, Any], cost_pct: float) -> float:
    return float(trade["entry"]) * (float(cost_pct) / 100.0) / max(float(trade["base_risk"]), 1e-12)


def net_r(trade: Dict[str, Any], cost_pct: float) -> float:
    return float(trade["gross_R"]) - cost_r(trade, cost_pct)


def max_drawdown(values: Iterable[float]) -> float:
    equity = peak = worst = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return float(worst)


def metrics(trades: Sequence[Dict[str, Any]], cost_pct: float) -> Dict[str, Any]:
    ordered = sorted(trades, key=lambda row: (int(row["entry_ts"]), str(row["symbol"])))
    values = [net_r(row, cost_pct) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    by_symbol: Dict[str, List[float]] = defaultdict(list)
    by_side: Dict[str, List[float]] = defaultdict(list)
    by_month: Dict[str, List[float]] = defaultdict(list)
    outcomes = Counter()
    triggered = 0
    for row, value in zip(ordered, values):
        by_symbol[str(row["symbol"])].append(value)
        by_side[str(row["side"])].append(value)
        month = pd.to_datetime(int(row["entry_ts"]), unit="ms", utc=True).strftime("%Y-%m")
        by_month[month].append(value)
        outcomes[str(row["outcome"])] += 1
        triggered += int(bool(row.get("triggered_1_5R")))
    gross_profit = float(sum(wins))
    gross_loss = abs(float(sum(losses)))
    nonnegative_months = sum(1 for group in by_month.values() if sum(group) >= 0)
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
        "by_month_net_R": {key: float(sum(group)) for key, group in sorted(by_month.items())},
        "nonnegative_month_ratio": float(nonnegative_months / len(by_month)) if by_month else 0.0,
        "outcomes": dict(sorted(outcomes.items())),
        "triggered_1_5R_pct": float(triggered / len(values) * 100.0) if values else 0.0,
        "ambiguity_count": sum(int(bool(row.get("ambiguity"))) for row in ordered),
    }


def load_consumed_raw() -> Tuple[Dict[Tuple[str, str], pd.DataFrame], Dict[Tuple[str, str], Dict[str, Any]]]:
    frames: Dict[Tuple[str, str], pd.DataFrame] = {}
    reports: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for window in WINDOWS:
        for symbol in SYMBOLS:
            frame, report = load_raw(raw_path(window, symbol))
            frames[(window, symbol)] = frame
            reports[(window, symbol)] = report
    return frames, reports


def replay_policies(events: Sequence[Dict[str, Any]], raw_frames: Dict[Tuple[str, str], pd.DataFrame]) -> Dict[str, Any]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        window = str(event.get("window"))
        symbol = str(event.get("symbol"))
        if window in WINDOWS and symbol in SYMBOLS:
            grouped[(window, symbol)].append(event)

    lane_trades: Dict[str, List[Dict[str, Any]]] = {name: [] for name in POLICIES}
    rejected: Dict[str, Counter[str]] = {name: Counter() for name in POLICIES}
    for key, rows in grouped.items():
        raw = raw_frames[key]
        ordered = sorted(rows, key=lambda event: int(event.get("entry_ts", 0)))
        for policy_name in POLICIES:
            blocked_until = -1
            for event in ordered:
                entry_ts = int(event.get("entry_ts", 0))
                if entry_ts <= blocked_until:
                    rejected[policy_name]["cooldown"] += 1
                    continue
                trade = simulate_policy(raw, event, policy_name)
                if trade is None:
                    rejected[policy_name]["simulation_reject"] += 1
                    continue
                lane_trades[policy_name].append(trade)
                blocked_until = int(trade["exit_ts"]) + COOLDOWN_MIN * MINUTE_MS

    baseline = lane_trades["baseline_fixed_2R"]
    baseline_combined = metrics(baseline, 0.15)
    reports: Dict[str, Any] = {}
    promising: List[str] = []
    for policy_name, trades in lane_trades.items():
        combined = metrics(trades, 0.15)
        cost020 = metrics(trades, 0.20)
        prior = metrics([row for row in trades if row["window"] == WINDOWS[0]], 0.15)
        second = metrics([row for row in trades if row["window"] == WINDOWS[1]], 0.15)
        retention = float(len(trades) / max(len(baseline), 1) * 100.0)
        checks = {
            "retention": retention >= POLICY_GATE["retention_pct_min"],
            "combined_avg_improvement": float(combined["avg_net_R"]) - float(baseline_combined["avg_net_R"]) >= POLICY_GATE["combined_avg_R_improvement_min"],
            "second_floor": float(second["avg_net_R"]) >= POLICY_GATE["second_avg_R_floor"],
            "cost020": float(cost020["avg_net_R"]) > POLICY_GATE["cost_0.20_avg_R_min_exclusive"],
            "profit_factor": float(combined["profit_factor_R"]) >= POLICY_GATE["profit_factor_min"],
            "positive_symbols": int(combined["positive_symbols"]) >= POLICY_GATE["positive_symbols_min"],
            "month_stability": float(combined["nonnegative_month_ratio"]) >= POLICY_GATE["nonnegative_month_ratio_min"],
            "mdd_not_worse": float(combined["max_drawdown_R"]) <= float(baseline_combined["max_drawdown_R"]),
        }
        gate_pass = policy_name != "baseline_fixed_2R" and all(checks.values())
        if gate_pass:
            promising.append(policy_name)
        reports[policy_name] = {
            "contract": POLICIES[policy_name],
            "retention_vs_baseline_pct": retention,
            "combined_cost_0.15": combined,
            "combined_cost_0.20": cost020,
            "prior_cost_0.15": prior,
            "second_cost_0.15": second,
            "avg_R_improvement_vs_baseline": float(combined["avg_net_R"]) - float(baseline_combined["avg_net_R"]),
            "mdd_change_vs_baseline_R": float(combined["max_drawdown_R"]) - float(baseline_combined["max_drawdown_R"]),
            "checks": checks,
            "gate_pass": gate_pass,
            "rejected": dict(sorted(rejected[policy_name].items())),
        }
    ranking = sorted(
        reports,
        key=lambda name: (
            bool(reports[name]["gate_pass"]),
            float(reports[name]["second_cost_0.15"]["avg_net_R"]),
            float(reports[name]["combined_cost_0.15"]["avg_net_R"]),
            -float(reports[name]["combined_cost_0.15"]["max_drawdown_R"]),
        ),
        reverse=True,
    )
    return {
        "status": "PASS_Q4R3_RASCHKE_V3_PARTIAL_RUNNER_REPLAY",
        "verdict": "CAUSAL_EXIT_POLICIES_REPLAYED_WITH_INDEPENDENT_COOLDOWN",
        "gate": POLICY_GATE,
        "baseline": "baseline_fixed_2R",
        "reports": reports,
        "ranking": ranking,
        "promising_candidates": promising,
        "candidate_count": len(promising),
        "trades": lane_trades,
    }


def first_touch_analysis(raw: pd.DataFrame, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    idx = event_index(raw, int(event.get("entry_ts", 0)))
    entry = safe_float(event.get("entry"))
    risk = safe_float(event.get("base_risk"))
    side = str(event.get("side", ""))
    if idx is None or entry is None or risk is None or risk <= 0 or side not in {"long", "short"}:
        return None
    last_idx = min(len(raw) - 1, idx + TIMEOUT_MIN - 1)
    if not path_contiguous(raw, idx, last_idx):
        return None
    touches: Dict[float, Optional[int]] = {0.5: None, 1.0: None, 1.5: None, 2.0: None}
    mae_before_15 = 0.0
    post_15_floor = 999.0
    for current in range(idx, last_idx + 1):
        bar = raw.iloc[current]
        high_r = directional_r(side, float(bar["high"] if side == "long" else bar["low"]), entry, risk)
        low_r = directional_r(side, float(bar["low"] if side == "long" else bar["high"]), entry, risk)
        for threshold in touches:
            if touches[threshold] is None and high_r >= threshold:
                touches[threshold] = current
        if touches[1.5] is None:
            mae_before_15 = min(mae_before_15, low_r)
        else:
            post_15_floor = min(post_15_floor, low_r)
        if touches[2.0] is not None:
            break
        if low_r <= -LOSS_CAP_R and touches[1.5] is None:
            break
    if touches[1.5] is None:
        return None
    reached_2 = touches[2.0] is not None
    month = pd.to_datetime(int(event.get("entry_ts", 0)), unit="ms", utc=True).strftime("%Y-%m")
    time_to_15 = int(touches[1.5] - idx)
    speed_bucket = "le_60m" if time_to_15 <= 60 else ("61_120m" if time_to_15 <= 120 else ("121_240m" if time_to_15 <= 240 else "gt_240m"))
    return {
        "event_id": event.get("event_id"),
        "window": event.get("window"),
        "symbol": event.get("symbol"),
        "side": side,
        "month": month,
        "entry_ts": int(event.get("entry_ts", 0)),
        "reached_2R": reached_2,
        "time_to_1_5R_min": time_to_15,
        "time_1_5R_to_2R_min": int(touches[2.0] - touches[1.5]) if reached_2 else None,
        "mae_before_1_5R": abs(float(mae_before_15)),
        "post_1_5R_floor_R": float(post_15_floor) if post_15_floor < 999.0 else None,
        "speed_bucket": speed_bucket,
        "final_class": class_name(event),
        "net_R_0.15": float(event.get("net_R_0.15", 0.0)),
        "features": event.get("features", {}),
    }


def binary_auc(labels: Sequence[int], scores: Sequence[float]) -> Optional[float]:
    positive = [score for label, score in zip(labels, scores) if label == 1]
    negative = [score for label, score in zip(labels, scores) if label == 0]
    if not positive or not negative:
        return None
    wins = 0.0
    for left in positive:
        for right in negative:
            wins += 1.0 if left > right else (0.5 if left == right else 0.0)
    return float(wins / (len(positive) * len(negative)))


def continuation_group(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    successes = [row for row in rows if row["reached_2R"]]
    failures = [row for row in rows if not row["reached_2R"]]
    return {
        "events_reached_1_5R": len(rows),
        "reached_2R": len(successes),
        "failed_to_reach_2R": len(failures),
        "p_2R_given_1_5R": float(len(successes) / len(rows)) if rows else 0.0,
        "median_time_to_1_5R_min": float(statistics.median(row["time_to_1_5R_min"] for row in rows)) if rows else None,
        "median_1_5R_to_2R_min": float(statistics.median(row["time_1_5R_to_2R_min"] for row in successes)) if successes else None,
        "failure_final_class": dict(sorted(Counter(row["final_class"] for row in failures).items())),
        "failure_net_sum_R": float(sum(row["net_R_0.15"] for row in failures)),
    }


def continuation_report(events: Sequence[Dict[str, Any]], raw_frames: Dict[Tuple[str, str], pd.DataFrame]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    rejected = Counter()
    for event in events:
        key = (str(event.get("window")), str(event.get("symbol")))
        raw = raw_frames.get(key)
        if raw is None:
            rejected["raw_missing"] += 1
            continue
        report = first_touch_analysis(raw, event)
        if report is None:
            rejected["not_1_5R_or_invalid"] += 1
            continue
        rows.append(report)

    groups: Dict[str, Any] = {"all": continuation_group(rows)}
    for axis in ("window", "side", "symbol", "month", "speed_bucket"):
        values = sorted({str(row[axis]) for row in rows})
        groups[axis] = {value: continuation_group([row for row in rows if str(row[axis]) == value]) for value in values}
    groups["window_side"] = {}
    for window in WINDOWS:
        for side in ("long", "short"):
            key = f"{window}|{side}"
            groups["window_side"][key] = continuation_group([row for row in rows if row["window"] == window and row["side"] == side])

    feature_screen: List[Dict[str, Any]] = []
    feature_names = list(PRE_ENTRY_FEATURES) + ["time_to_1_5R_min", "mae_before_1_5R"]
    for feature in feature_names:
        window_reports: Dict[str, Any] = {}
        for window in WINDOWS:
            selected = [row for row in rows if row["window"] == window]
            labels: List[int] = []
            values: List[float] = []
            for row in selected:
                value = row.get(feature) if feature in row else row.get("features", {}).get(feature)
                number = safe_float(value)
                if number is None:
                    continue
                labels.append(1 if row["reached_2R"] else 0)
                values.append(number)
            auc = binary_auc(labels, values)
            window_reports[window] = {
                "events": len(values),
                "positive": sum(labels),
                "negative": len(labels) - sum(labels),
                "auc": auc,
                "oriented_strength": None if auc is None else float((auc - 0.5) * 2.0),
            }
        first = safe_float(window_reports[WINDOWS[0]]["oriented_strength"])
        second = safe_float(window_reports[WINDOWS[1]]["oriented_strength"])
        sign_consistent = bool(first is not None and second is not None and first != 0 and second != 0 and (first > 0) == (second > 0))
        minimum_class = min(
            window_reports[WINDOWS[0]]["positive"],
            window_reports[WINDOWS[0]]["negative"],
            window_reports[WINDOWS[1]]["positive"],
            window_reports[WINDOWS[1]]["negative"],
        )
        strength = min(abs(first), abs(second)) if first is not None and second is not None else 0.0
        feature_screen.append(
            {
                "feature": feature,
                "feature_role": "post_entry_exit_state" if feature in {"time_to_1_5R_min", "mae_before_1_5R"} else "pre_entry_observer",
                "windows": window_reports,
                "sign_consistent": sign_consistent,
                "minimum_class_per_window": minimum_class,
                "minimum_strength": strength,
                "stable_diagnostic": bool(sign_consistent and minimum_class >= 5 and strength >= 0.10),
            }
        )
    feature_screen.sort(key=lambda row: (row["stable_diagnostic"], row["minimum_strength"], row["minimum_class_per_window"]), reverse=True)
    return {
        "status": "PASS_Q4R3_RASCHKE_V3_15R_TO_2R_CONTINUATION",
        "verdict": "CONTINUATION_FAILURE_DECOMPOSED_NO_ENTRY_PROMOTION",
        "rows": rows,
        "groups": groups,
        "feature_screen": feature_screen,
        "rejected": dict(sorted(rejected.items())),
        "contract": {
            "post_entry_features_entry_filter_allowed": False,
            "pre_entry_features_promotion_allowed": False,
            "independent_history_required": True,
        },
    }


def overlap(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return max(left_start, right_start) <= min(left_end, right_end)


def candidate_file_map(group: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    selected: Dict[str, Dict[str, Any]] = {}
    for row in group.get("files", []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", ""))
        if symbol not in SYMBOLS:
            continue
        current = selected.get(symbol)
        if current is None or int(row.get("bytes", 0)) > int(current.get("bytes", 0)):
            selected[symbol] = row
    return selected


def history_integrity(inventory: Dict[str, Any], consumed_reports: Dict[Tuple[str, str], Dict[str, Any]]) -> Dict[str, Any]:
    consumed_ranges = [
        {
            "window": window,
            "symbol": symbol,
            "start_ts": report["start_ts"],
            "end_ts": report["end_ts"],
        }
        for (window, symbol), report in consumed_reports.items()
    ]
    earliest_consumed_start = min(row["start_ts"] for row in consumed_ranges)
    candidates = inventory.get("full_symbol_candidate_groups", [])
    if not isinstance(candidates, list):
        candidates = []
    inspected: List[Dict[str, Any]] = []
    for group in candidates[:MAX_HISTORY_GROUPS]:
        if not isinstance(group, dict):
            continue
        directory = str(group.get("directory", ""))
        lowered = directory.lower()
        reasons: List[str] = []
        reserved = [token for token in RESERVED_PATH_TOKENS if token in lowered]
        if reserved:
            reasons.append("reserved_path_token:" + ",".join(reserved))
        files = candidate_file_map(group)
        if set(files) != set(SYMBOLS):
            reasons.append("five_symbol_coverage_missing")
        symbol_reports: Dict[str, Any] = {}
        for symbol in SYMBOLS:
            row = files.get(symbol)
            if row is None:
                continue
            path = DATA_ROOT / directory / str(row.get("name"))
            try:
                _, report = load_raw(path)
                symbol_reports[symbol] = report
            except Exception as exc:
                symbol_reports[symbol] = {"path": str(path), "error": repr(exc), "strict_or_sparse_valid": False}
                reasons.append(f"raw_invalid:{symbol}")
        valid_reports = [report for report in symbol_reports.values() if report.get("strict_or_sparse_valid")]
        if len(valid_reports) == len(SYMBOLS):
            starts = [int(report["start_ts"]) for report in valid_reports]
            ends = [int(report["end_ts"]) for report in valid_reports]
            if max(starts) - min(starts) > MAX_SYMBOL_SPAN_SKEW_MS or max(ends) - min(ends) > MAX_SYMBOL_SPAN_SKEW_MS:
                reasons.append("symbol_span_misaligned")
            for report in valid_reports:
                for consumed in consumed_ranges:
                    if overlap(int(report["start_ts"]), int(report["end_ts"]), int(consumed["start_ts"]), int(consumed["end_ts"])):
                        reasons.append("overlaps_consumed_window")
                        break
            if max(ends) >= earliest_consumed_start:
                reasons.append("not_strictly_pre_history")
        eligible = len(reasons) == 0 and len(valid_reports) == len(SYMBOLS)
        inspected.append(
            {
                "directory": directory,
                "eligible_for_manual_approval": eligible,
                "automatic_append_allowed": False,
                "reasons": sorted(set(reasons)),
                "symbols": symbol_reports,
            }
        )
    eligible_groups = [row for row in inspected if row["eligible_for_manual_approval"]]
    return {
        "status": "PASS_Q4R3_RASCHKE_V3_SAFE_HISTORY_INTEGRITY",
        "verdict": "HISTORY_CONTENT_INSPECTED_READ_ONLY_NO_APPEND",
        "inspected_groups": inspected,
        "eligible_groups": eligible_groups,
        "eligible_count": len(eligible_groups),
        "consumed_ranges": consumed_ranges,
        "contract": {
            "automatic_append_allowed": False,
            "manual_confirmation_required": True,
            "reserved_final_or_forward_consumed": False,
            "strictly_pre_history_required": True,
        },
    }


def event_month(event: Dict[str, Any]) -> str:
    stamp = int(event.get("signal_ts", event.get("entry_ts", 0)))
    return pd.to_datetime(stamp, unit="ms", utc=True).strftime("%Y-%m")


def bocpd_month_validation(events: Sequence[Dict[str, Any]], bocpd: Dict[str, Any]) -> Dict[str, Any]:
    by_month: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_month[event_month(event)].append(event)
    month_rows = []
    for month, rows in sorted(by_month.items()):
        values = [float(row.get("net_R_0.15", 0.0)) for row in rows]
        month_rows.append(
            {
                "month": month,
                "events": len(rows),
                "avg_net_R": float(statistics.fmean(values)) if values else 0.0,
                "net_sum_R": float(sum(values)),
                "tp": sum(1 for row in rows if class_name(row) == "TP"),
                "sl": sum(1 for row in rows if class_name(row) == "SL"),
                "timeout": sum(1 for row in rows if class_name(row) == "TIMEOUT"),
            }
        )
    worst_months = [row["month"] for row in sorted(month_rows, key=lambda row: (row["avg_net_R"], row["net_sum_R"]))[:3]]
    top_points = bocpd.get("top_change_points", [])
    cp_by_month: Dict[str, float] = defaultdict(float)
    cp_count = Counter()
    if isinstance(top_points, list):
        for row in top_points:
            if not isinstance(row, dict):
                continue
            stamp = int(row.get("signal_ts", 0))
            month = pd.to_datetime(stamp, unit="ms", utc=True).strftime("%Y-%m")
            probability = safe_float(row.get("cp_probability", {}).get("max")) or 0.0
            cp_by_month[month] = max(cp_by_month[month], probability)
            cp_count[month] += 1
    top_cp_months = [month for month, _ in sorted(cp_by_month.items(), key=lambda item: (item[1], cp_count[item[0]]), reverse=True)[:3]]
    overlap_months = sorted(set(worst_months) & set(top_cp_months))
    return {
        "status": "PASS_Q4R3_RASCHKE_V3_BOCPD_MONTH_VALIDATION",
        "month_blocks": month_rows,
        "worst_months": worst_months,
        "top_change_point_months": top_cp_months,
        "overlap_months": overlap_months,
        "overlap_count": len(overlap_months),
        "observer_supported": len(overlap_months) >= 1,
        "promotion_allowed": False,
    }


def write_html(continuation: Dict[str, Any], policy: Dict[str, Any], history: Dict[str, Any], bocpd_month: Dict[str, Any], decision: Dict[str, Any]) -> None:
    policy_rows = "".join(
        "<tr>"
        f"<td>{html.escape(name)}</td>"
        f"<td>{report['gate_pass']}</td>"
        f"<td>{report['combined_cost_0.15']['events']}</td>"
        f"<td>{report['combined_cost_0.15']['avg_net_R']:.4f}</td>"
        f"<td>{report['second_cost_0.15']['avg_net_R']:.4f}</td>"
        f"<td>{report['combined_cost_0.15']['profit_factor_R']:.3f}</td>"
        f"<td>{report['combined_cost_0.15']['max_drawdown_R']:.3f}</td>"
        "</tr>"
        for name, report in policy["reports"].items()
    )
    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Raschke continuation and partial runner</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%;margin-bottom:30px}td,th{border:1px solid #334155;padding:7px}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>Raschke 1.5R to 2R continuation, partial runner and safe history</h1>",
            "<h2>Policy replay</h2><table><thead><tr><th>Policy</th><th>Gate</th><th>Events</th><th>Avg R</th><th>Second Avg R</th><th>PF</th><th>MDD</th></tr></thead><tbody>",
            policy_rows,
            "</tbody></table><h2>Continuation</h2><pre>",
            html.escape(json.dumps({"groups": continuation["groups"], "top_features": continuation["feature_screen"][:10]}, ensure_ascii=False, indent=2)),
            "</pre><h2>Safe history</h2><pre>",
            html.escape(json.dumps({"eligible_count": history["eligible_count"], "eligible_groups": history["eligible_groups"]}, ensure_ascii=False, indent=2)),
            "</pre><h2>BOCPD month validation</h2><pre>",
            html.escape(json.dumps(bocpd_month, ensure_ascii=False, indent=2)),
            "</pre><h2>Decision</h2><pre>",
            html.escape(json.dumps(decision, ensure_ascii=False, indent=2)),
            "</pre></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    ledger = load_json(LEDGER_SOURCE)
    transition_source = load_json(TRANSITION_SOURCE)
    bocpd_source = load_json(BOCPD_SOURCE)
    inventory_source = load_json(INVENTORY_SOURCE)
    events = [row for row in ledger.get("events", []) if isinstance(row, dict)]
    if not events:
        raise RuntimeError("EVENT_LEDGER_EMPTY")
    raw_frames, consumed_reports = load_consumed_raw()

    continuation = continuation_report(events, raw_frames)
    policy = replay_policies(events, raw_frames)
    history = history_integrity(inventory_source, consumed_reports)
    bocpd_month = bocpd_month_validation(events, bocpd_source)

    candidates = list(policy["promising_candidates"])
    next_modules: List[str] = []
    if candidates:
        next_modules.append("PRESERVE_PARTIAL_RUNNER_CANDIDATE_FOR_INDEPENDENT_VALIDATION")
    if history["eligible_count"] > 0:
        next_modules.append("MANUAL_CONFIRM_ONE_SAFE_PRE_HISTORY_GROUP_THEN_APPEND_EVENT_LEDGER")
    else:
        next_modules.append("NO_SAFE_PRE_HISTORY_FOUND_CONTINUE_FORWARD_OBSERVER_COLLECTION")
    next_modules.append("RECHECK_15R_TO_2R_CONTINUATION_ON_EXPANDED_HISTORY")
    if bocpd_month["observer_supported"]:
        next_modules.append("KEEP_BOCPD_AS_MONTH_BLOCK_OBSERVER")
    else:
        next_modules.append("BOCPD_MONTH_ALIGNMENT_NOT_CONFIRMED")

    decision = {
        "status": "PASS_Q4R3_RASCHKE_V3_CONTINUATION_DECISION",
        "verdict": (
            "PARTIAL_RUNNER_CANDIDATE_FOUND_HISTORY_CONFIRMATION_REQUIRED"
            if candidates
            else "NO_PARTIAL_RUNNER_GATE_PASS_SAFE_HISTORY_OR_FORWARD_DATA_REQUIRED"
        ),
        "promising_policy_candidates": candidates,
        "best_policy_by_preregistered_ranking": policy["ranking"][0] if policy["ranking"] else None,
        "continuation_probability_2R_given_1_5R": continuation["groups"]["all"]["p_2R_given_1_5R"],
        "stable_continuation_diagnostics": [row for row in continuation["feature_screen"] if row["stable_diagnostic"]][:5],
        "eligible_safe_history_groups": history["eligible_count"],
        "bocpd_month_observer_supported": bocpd_month["observer_supported"],
        "next_modules": next_modules,
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
    trial = {
        "status": "PASS_Q4R3_RASCHKE_V3_PARTIAL_RUNNER_TRIAL_REGISTERED",
        "policies": POLICIES,
        "gate": POLICY_GATE,
        "data_windows": WINDOWS,
        "signals": len(events),
        "cost_levels_pct": COST_LEVELS,
        "cooldown_min": COOLDOWN_MIN,
        "threshold_search_performed": False,
        "synthetic_oversampling": False,
        "post_hoc_trade_deletion": False,
        "source_transition_status": transition_source.get("status"),
        "research_contract": RESEARCH_CONTRACT,
    }

    atomic_json(CONTINUATION_OUT, continuation)
    policy_without_trades = dict(policy)
    policy_without_trades.pop("trades", None)
    atomic_json(POLICY_OUT, policy_without_trades)
    atomic_json(HISTORY_OUT, history)
    atomic_json(BOCPD_MONTH_OUT, bocpd_month)
    atomic_json(DECISION_OUT, decision)
    atomic_json(TRIAL_OUT, trial)
    write_html(continuation, policy_without_trades, history, bocpd_month, decision)
    print(json.dumps({
        "decision": decision,
        "policy_ranking": policy["ranking"],
        "policy_summary": {
            name: {
                "gate_pass": report["gate_pass"],
                "events": report["combined_cost_0.15"]["events"],
                "avg_net_R": report["combined_cost_0.15"]["avg_net_R"],
                "second_avg_net_R": report["second_cost_0.15"]["avg_net_R"],
                "profit_factor_R": report["combined_cost_0.15"]["profit_factor_R"],
                "max_drawdown_R": report["combined_cost_0.15"]["max_drawdown_R"],
                "cost_0.20_avg_net_R": report["combined_cost_0.20"]["avg_net_R"],
                "failed_checks": [key for key, value in report["checks"].items() if not value],
            }
            for name, report in policy["reports"].items()
        },
        "continuation_all": continuation["groups"]["all"],
        "safe_history_eligible": history["eligible_count"],
        "bocpd_month_overlap": bocpd_month["overlap_months"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
