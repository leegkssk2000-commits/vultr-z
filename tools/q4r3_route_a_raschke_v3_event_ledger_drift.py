from __future__ import annotations

import html
import importlib.util
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
OVERLAY_ROOT = Path(os.environ.get("Q4R3_ROUTE_A_OVERLAY_ROOT", "/tmp/q4r3-route-a-v3-ledger"))
V2_PATH = OVERLAY_ROOT / "tools" / "q4r3_route_a_raschke_v2_entry_exit_tournament.py"

SUMMARY_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_event_ledger_drift_latest.json"
LEDGER_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_all_signal_ledger_latest.json"
DRIFT_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_feature_drift_latest.json"
PATH_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_event_aligned_paths_latest.json"
HTML_OUT = ROOT / "runtime" / "raschke_v3_event_ledger_drift_latest.html"

MINUTE_MS = 60_000
COST_PCT = 0.15
HORIZON_MIN = 480
CHECKPOINTS_MIN = (15, 30, 60, 120, 240, 480)
WINDOWS = ("prior_holdout_90d", "second_holdout_90d")

NUMERIC_FEATURES = (
    "ema_distance_atr", "ema_slope_atr", "adx", "candle_body_atr",
    "close_location", "volume_ratio", "macd_signal_spread_atr",
    "macd_signal_spread_prev_atr", "chop_score", "return_4h",
    "return_24h", "realized_vol_24h", "range_atr_6h", "volume_z_24h",
    "ema50_slope_atr_6h", "ema200_slope_atr_6h", "atr_percentile_120h",
)
CATEGORICAL_FEATURES = (
    "symbol", "side", "utc_session", "utc_hour", "proximity_pass", "source_reason",
)
DRIFT_THRESHOLDS = {
    "psi_warn": 0.10, "psi_high": 0.25, "ks_warn": 0.20,
    "std_mean_diff_warn": 0.35, "js_warn": 0.10,
}


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V2 = _load_module("q4r3_raschke_v3_ledger_v2", V2_PATH)


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def utc_session(stamp_ms: int) -> str:
    hour = int(pd.to_datetime(int(stamp_ms), unit="ms", utc=True).hour)
    return "utc_00_07" if hour < 8 else ("utc_08_15" if hour < 16 else "utc_16_23")


def atr_series(bars: pd.DataFrame, length: int = 14) -> pd.Series:
    previous_close = bars["close"].shift(1)
    return pd.concat(
        [bars["high"] - bars["low"], (bars["high"] - previous_close).abs(), (bars["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1).rolling(length, min_periods=length).mean()


def rolling_percentile(values: pd.Series, lookback: int = 120) -> Optional[float]:
    clean = values.dropna()
    if len(clean) < min(30, lookback):
        return None
    recent = clean.iloc[-lookback:]
    current = float(recent.iloc[-1])
    return float((recent <= current).mean())


def zscore_last(values: pd.Series, lookback: int = 24) -> Optional[float]:
    clean = values.dropna().iloc[-lookback:]
    if len(clean) < min(12, lookback):
        return None
    std = float(clean.std(ddof=0))
    if not math.isfinite(std) or std <= 1e-12:
        return 0.0
    return float((float(clean.iloc[-1]) - float(clean.mean())) / std)


def derived_features(window: pd.DataFrame) -> Dict[str, Optional[float]]:
    close = window["close"].astype(float)
    volume = window["volume"].astype(float)
    atr = atr_series(window)
    current_atr = safe_float(atr.iloc[-1])
    current_close = safe_float(close.iloc[-1])
    empty = {
        "return_4h": None, "return_24h": None, "realized_vol_24h": None,
        "range_atr_6h": None, "volume_z_24h": None, "ema50_slope_atr_6h": None,
        "ema200_slope_atr_6h": None, "atr_percentile_120h": None,
    }
    if current_atr is None or current_atr <= 0 or current_close is None or current_close <= 0:
        return empty
    ema50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
    ema200 = close.ewm(span=200, adjust=False, min_periods=200).mean()
    returns = close.pct_change()
    realized = returns.rolling(24, min_periods=12).std(ddof=0) * math.sqrt(24.0)
    range_6h = (window["high"].rolling(6).max() - window["low"].rolling(6).min()) / current_atr

    def lag_return(periods: int) -> Optional[float]:
        if len(close) <= periods or float(close.iloc[-periods - 1]) == 0:
            return None
        return float(close.iloc[-1] / close.iloc[-periods - 1] - 1.0)

    def slope_atr(series: pd.Series, periods: int = 6) -> Optional[float]:
        if len(series.dropna()) <= periods:
            return None
        current = safe_float(series.iloc[-1])
        past = safe_float(series.iloc[-periods - 1])
        return None if current is None or past is None else float((current - past) / current_atr)

    return {
        "return_4h": lag_return(4),
        "return_24h": lag_return(24),
        "realized_vol_24h": safe_float(realized.iloc[-1]),
        "range_atr_6h": safe_float(range_6h.iloc[-1]),
        "volume_z_24h": zscore_last(volume, 24),
        "ema50_slope_atr_6h": slope_atr(ema50, 6),
        "ema200_slope_atr_6h": slope_atr(ema200, 6),
        "atr_percentile_120h": rolling_percentile(atr, 120),
    }


def path_contiguous(raw: pd.DataFrame, start_idx: int, end_idx: int) -> bool:
    path = raw.iloc[start_idx : end_idx + 1]
    return True if len(path) < 2 else bool((path["ts"].diff().dropna() == MINUTE_MS).all())


def label_signal(raw: pd.DataFrame, *, entry_idx: int, side: str, signal_entry: float, native_stop: float) -> Optional[Dict[str, Any]]:
    if entry_idx < 0 or entry_idx >= len(raw):
        return None
    last_idx = min(len(raw) - 1, entry_idx + HORIZON_MIN - 1)
    if not path_contiguous(raw, entry_idx, last_idx):
        return None
    actual_entry = float(raw.iloc[entry_idx]["open"])
    base_risk = abs(float(signal_entry) - float(native_stop))
    if not math.isfinite(base_risk) or base_risk <= 0:
        return None
    direction = 1.0 if side == "long" else -1.0
    stop = actual_entry - direction * base_risk * 0.5
    target = actual_entry + direction * base_risk * 2.0
    label = "TIMEOUT"
    exit_idx = last_idx
    exit_price = float(raw.iloc[last_idx]["close"])
    ambiguity = False
    mfe_r = mae_r = 0.0
    minutes_to_mfe = minutes_to_mae = 0
    checkpoint_close_r: Dict[str, Optional[float]] = {str(minutes): None for minutes in CHECKPOINTS_MIN}

    for offset, idx in enumerate(range(entry_idx, last_idx + 1)):
        row = raw.iloc[idx]
        high, low, close = float(row["high"]), float(row["low"]), float(row["close"])
        favorable = (high - actual_entry) / base_risk if side == "long" else (actual_entry - low) / base_risk
        adverse = (actual_entry - low) / base_risk if side == "long" else (high - actual_entry) / base_risk
        if favorable > mfe_r:
            mfe_r, minutes_to_mfe = float(favorable), offset
        if adverse > mae_r:
            mae_r, minutes_to_mae = float(adverse), offset
        minute_number = offset + 1
        if minute_number in CHECKPOINTS_MIN:
            checkpoint_close_r[str(minute_number)] = float(direction * (close - actual_entry) / base_risk)
        stop_hit = low <= stop if side == "long" else high >= stop
        target_hit = high >= target if side == "long" else low <= target
        if stop_hit and target_hit:
            ambiguity, label, exit_idx, exit_price = True, "SL_FIRST_CONSERVATIVE", idx, stop
            break
        if stop_hit:
            label, exit_idx, exit_price = "SL_FIRST", idx, stop
            break
        if target_hit:
            label, exit_idx, exit_price = "TP_FIRST", idx, target
            break

    gross_r = float(direction * (exit_price - actual_entry) / base_risk)
    cost_r = float(actual_entry * (COST_PCT / 100.0) / base_risk)
    return {
        "entry_idx": int(entry_idx), "exit_idx": int(exit_idx),
        "entry_ts": int(raw.iloc[entry_idx]["ts"]), "exit_ts": int(raw.iloc[exit_idx]["ts"]),
        "entry": actual_entry, "exit": float(exit_price), "stop": float(stop), "target": float(target),
        "base_risk": float(base_risk), "risk_pct": float(base_risk / actual_entry * 100.0),
        "label": label, "gross_R": gross_r, "net_R_0.15": float(gross_r - cost_r),
        "mfe_R": float(mfe_r), "mae_R": float(mae_r),
        "minutes_to_mfe": int(minutes_to_mfe), "minutes_to_mae": int(minutes_to_mae),
        "duration_min": int((int(raw.iloc[exit_idx]["ts"]) - int(raw.iloc[entry_idx]["ts"])) / MINUTE_MS),
        "ambiguous": ambiguity, "checkpoint_close_R": checkpoint_close_r,
    }


def collect_symbol(raw: pd.DataFrame, *, symbol: str, window_name: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    bars = V2.BASE.make_bars(raw, V2.TIMEFRAME_MIN)
    events: List[Dict[str, Any]] = []
    reasons: Dict[str, int] = defaultdict(int)
    config = V2.Config(confirmation_mode="candle_direction")
    for end_i in range(V2.WINDOW_BARS, len(bars)):
        window = bars.iloc[end_i - V2.WINDOW_BARS : end_i]
        if not V2.window_is_contiguous(window):
            reasons["non_contiguous_window"] += 1
            continue
        signal_bar = bars.iloc[end_i - 1]
        next_raw_idx = int(signal_bar["raw_end_idx"]) + 1
        if next_raw_idx >= len(raw):
            reasons["no_next_open"] += 1
            continue
        result = V2.strategy(window[["ts", "open", "high", "low", "close", "volume"]].copy(), config=config)
        source_reason = str(result.get("why", "unknown")) if isinstance(result, dict) else "invalid_result"
        reasons[source_reason] += 1
        if not isinstance(result, dict) or str(result.get("action", "")).lower() != "enter":
            continue
        side = str(result.get("side", "")).lower()
        if side not in {"long", "short"}:
            reasons["invalid_side"] += 1
            continue
        try:
            signal_entry, native_stop = float(result["entry"]), float(result["sl"])
        except (KeyError, TypeError, ValueError):
            reasons["invalid_contract"] += 1
            continue
        label = label_signal(raw, entry_idx=next_raw_idx, side=side, signal_entry=signal_entry, native_stop=native_stop)
        if label is None:
            reasons["label_path_reject"] += 1
            continue
        signal_ts = int(signal_bar["ts"])
        events.append({
            "event_id": f"{window_name}|{symbol}|{side}|{signal_ts}",
            "window": window_name, "symbol": symbol, "side": side, "signal_ts": signal_ts,
            "signal_utc": str(pd.to_datetime(signal_ts, unit="ms", utc=True)),
            "utc_hour": int(pd.to_datetime(signal_ts, unit="ms", utc=True).hour),
            "utc_session": utc_session(signal_ts), "source_reason": source_reason,
            "proximity_pass": bool(V2.entry_pass("v2_proximity_guard", result)),
            "direction_alignment_pass": bool(V2.entry_pass("v2_direction_alignment", result)),
            "macd_strength_pass": bool(V2.entry_pass("v2_macd_strength", result)),
            "features": {**V2.signal_metadata(result), **derived_features(window)},
            **label,
        })
    return events, dict(sorted(reasons.items()))


def values_for(events: Sequence[Dict[str, Any]], feature: str) -> List[float]:
    output: List[float] = []
    for event in events:
        value = safe_float(event.get("features", {}).get(feature))
        if value is not None:
            output.append(value)
    return output


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower, upper = int(math.floor(position)), int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def ks_statistic(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right:
        return 0.0
    left_sorted, right_sorted = sorted(left), sorted(right)
    points = sorted(set(left_sorted + right_sorted))
    i = j = 0
    worst = 0.0
    for point in points:
        while i < len(left_sorted) and left_sorted[i] <= point:
            i += 1
        while j < len(right_sorted) and right_sorted[j] <= point:
            j += 1
        worst = max(worst, abs(i / len(left_sorted) - j / len(right_sorted)))
    return float(worst)


def population_stability_index(reference: Sequence[float], current: Sequence[float], bins: int = 10) -> float:
    if len(reference) < 5 or len(current) < 5:
        return 0.0
    edges = sorted(set(quantile(reference, index / bins) for index in range(1, bins)))
    if not edges:
        return 0.0
    def counts(values: Sequence[float]) -> List[int]:
        output = [0] * (len(edges) + 1)
        for value in values:
            bucket = 0
            while bucket < len(edges) and value > edges[bucket]:
                bucket += 1
            output[bucket] += 1
        return output
    ref_counts, cur_counts = counts(reference), counts(current)
    epsilon, total_ref, total_cur = 1e-6, max(sum(ref_counts), 1), max(sum(cur_counts), 1)
    psi = 0.0
    for ref_count, cur_count in zip(ref_counts, cur_counts):
        ref_ratio = max(ref_count / total_ref, epsilon)
        cur_ratio = max(cur_count / total_cur, epsilon)
        psi += (cur_ratio - ref_ratio) * math.log(cur_ratio / ref_ratio)
    return float(psi)


def standardized_mean_difference(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) < 2 or len(right) < 2:
        return 0.0
    pooled = math.sqrt(max((statistics.pvariance(left) + statistics.pvariance(right)) / 2.0, 1e-12))
    return float((statistics.fmean(right) - statistics.fmean(left)) / pooled)


def numeric_drift(prior: Sequence[Dict[str, Any]], second: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    for feature in NUMERIC_FEATURES:
        left, right = values_for(prior, feature), values_for(second, feature)
        psi, ks, smd = population_stability_index(left, right), ks_statistic(left, right), standardized_mean_difference(left, right)
        flags: List[str] = []
        if psi >= DRIFT_THRESHOLDS["psi_high"]:
            flags.append("psi_high")
        elif psi >= DRIFT_THRESHOLDS["psi_warn"]:
            flags.append("psi_warn")
        if ks >= DRIFT_THRESHOLDS["ks_warn"]:
            flags.append("ks_warn")
        if abs(smd) >= DRIFT_THRESHOLDS["std_mean_diff_warn"]:
            flags.append("mean_shift")
        report[feature] = {
            "prior_n": len(left), "second_n": len(right),
            "prior_mean": float(statistics.fmean(left)) if left else None,
            "second_mean": float(statistics.fmean(right)) if right else None,
            "prior_median": float(statistics.median(left)) if left else None,
            "second_median": float(statistics.median(right)) if right else None,
            "psi": psi, "ks": ks, "standardized_mean_difference": smd,
            "flags": flags, "drift_score": float(max(psi, ks, abs(smd))),
        }
    return dict(sorted(report.items(), key=lambda item: float(item[1]["drift_score"]), reverse=True))


def categorical_distribution(events: Sequence[Dict[str, Any]], feature: str) -> Dict[str, float]:
    counts: Counter[str] = Counter(str(event.get(feature)) for event in events)
    total = max(sum(counts.values()), 1)
    return {key: value / total for key, value in sorted(counts.items())}


def js_divergence(left: Dict[str, float], right: Dict[str, float]) -> float:
    keys, epsilon, output = set(left) | set(right), 1e-12, 0.0
    for key in keys:
        p, q = max(float(left.get(key, 0.0)), epsilon), max(float(right.get(key, 0.0)), epsilon)
        midpoint = (p + q) / 2.0
        output += 0.5 * p * math.log(p / midpoint) + 0.5 * q * math.log(q / midpoint)
    return float(output)


def categorical_drift(prior: Sequence[Dict[str, Any]], second: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    for feature in CATEGORICAL_FEATURES:
        left, right = categorical_distribution(prior, feature), categorical_distribution(second, feature)
        divergence = js_divergence(left, right)
        report[feature] = {
            "prior_distribution": left, "second_distribution": right,
            "js_divergence": divergence,
            "flags": ["js_warn"] if divergence >= DRIFT_THRESHOLDS["js_warn"] else [],
        }
    return dict(sorted(report.items(), key=lambda item: float(item[1]["js_divergence"]), reverse=True))


def event_metrics(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    values = [float(event["net_R_0.15"]) for event in events]
    labels = Counter(str(event["label"]) for event in events)
    by_side: Dict[str, List[float]] = defaultdict(list)
    by_symbol: Dict[str, List[float]] = defaultdict(list)
    for event, value in zip(events, values):
        by_side[str(event["side"])].append(value)
        by_symbol[str(event["symbol"])].append(value)
    wins, losses = [value for value in values if value > 0], [value for value in values if value < 0]
    gross_profit, gross_loss = float(sum(wins)), abs(float(sum(losses)))
    return {
        "events": len(events), "avg_net_R": float(statistics.fmean(values)) if values else 0.0,
        "median_net_R": float(statistics.median(values)) if values else 0.0,
        "net_sum_R": float(sum(values)), "positive_rate_pct": float(len(wins) / len(values) * 100.0) if values else 0.0,
        "profit_factor_R": float(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "labels": dict(sorted(labels.items())),
        "by_side": {key: {"events": len(group), "avg_net_R": float(statistics.fmean(group)), "net_sum_R": float(sum(group))} for key, group in sorted(by_side.items())},
        "by_symbol": {key: {"events": len(group), "avg_net_R": float(statistics.fmean(group)), "net_sum_R": float(sum(group))} for key, group in sorted(by_symbol.items())},
    }


def aligned_paths(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        groups[(str(event["window"]), str(event["side"]), str(event["label"]))].append(event)
    output: Dict[str, Any] = {}
    for (window, side, label), rows in sorted(groups.items()):
        checkpoints: Dict[str, Any] = {}
        for minute in CHECKPOINTS_MIN:
            clean = [value for row in rows if (value := safe_float(row["checkpoint_close_R"].get(str(minute)))) is not None]
            checkpoints[str(minute)] = {
                "n": len(clean), "mean_close_R": float(statistics.fmean(clean)) if clean else None,
                "median_close_R": float(statistics.median(clean)) if clean else None,
            }
        output[f"{window}|{side}|{label}"] = {
            "events": len(rows), "mean_mfe_R": float(statistics.fmean(float(row["mfe_R"]) for row in rows)),
            "mean_mae_R": float(statistics.fmean(float(row["mae_R"]) for row in rows)), "checkpoints": checkpoints,
        }
    return output


def monthly_expectancy(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        groups[pd.to_datetime(int(event["signal_ts"]), unit="ms", utc=True).strftime("%Y-%m")].append(event)
    return {month: event_metrics(rows) for month, rows in sorted(groups.items())}


def rolling_expectancy(events: Sequence[Dict[str, Any]], window: int = 30) -> List[Dict[str, Any]]:
    ordered = sorted(events, key=lambda row: int(row["signal_ts"]))
    output: List[Dict[str, Any]] = []
    for index in range(window - 1, len(ordered)):
        chunk = ordered[index - window + 1 : index + 1]
        values = [float(row["net_R_0.15"]) for row in chunk]
        output.append({
            "end_signal_ts": int(chunk[-1]["signal_ts"]), "end_signal_utc": chunk[-1]["signal_utc"],
            "events": window, "avg_net_R": float(statistics.fmean(values)), "net_sum_R": float(sum(values)),
        })
    return output


def readiness(events: Sequence[Dict[str, Any]], drift: Dict[str, Any]) -> Dict[str, Any]:
    by_side, by_window = Counter(str(event["side"]) for event in events), Counter(str(event["window"]) for event in events)
    tp = sum(str(event["label"]) == "TP_FIRST" for event in events)
    sl = sum(str(event["label"]).startswith("SL_FIRST") for event in events)
    min_class = min(tp, sl) if tp and sl else 0
    checks = {
        "events_min_200": len(events) >= 200,
        "each_side_min_50": all(by_side.get(side, 0) >= 50 for side in ("long", "short")),
        "each_window_min_80": all(by_window.get(window, 0) >= 80 for window in WINDOWS),
        "tp_sl_min_class_30": min_class >= 30,
        "drift_measured": len(drift["numeric"]) >= 10,
    }
    ready = all(checks.values())
    return {
        "checks": checks, "ready_for_meta_labeler_design": ready, "events": len(events),
        "by_side": dict(by_side), "by_window": dict(by_window), "tp_events": tp, "sl_events": sl,
        "min_tp_sl_class": min_class,
        "high_psi_feature_count": sum("psi_high" in item["flags"] for item in drift["numeric"].values()),
        "next": "PURGED_WALK_FORWARD_META_LABELER" if ready else "RETAIN_DIAGNOSTIC_ONLY_INCREASE_EVENT_SAMPLE",
    }


def write_html(summary: Dict[str, Any], drift: Dict[str, Any], paths: Dict[str, Any]) -> None:
    numeric_rows = "".join(
        "<tr>" f"<td>{html.escape(feature)}</td><td>{report['prior_mean']}</td><td>{report['second_mean']}</td>"
        f"<td>{report['psi']:.3f}</td><td>{report['ks']:.3f}</td><td>{report['standardized_mean_difference']:.3f}</td>"
        f"<td>{html.escape(','.join(report['flags']))}</td></tr>"
        for feature, report in list(drift["numeric"].items())[:20]
    )
    path_rows = "".join(
        "<tr>" f"<td>{html.escape(key)}</td><td>{report['events']}</td><td>{report['mean_mfe_R']:.3f}</td>"
        f"<td>{report['mean_mae_R']:.3f}</td><td>{report['checkpoints']['60']['mean_close_R']}</td>"
        f"<td>{report['checkpoints']['240']['mean_close_R']}</td></tr>" for key, report in paths.items()
    )
    page = "".join([
        "<!doctype html><html><head><meta charset='utf-8'><title>Raschke v3 event ledger drift</title>",
        "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%;margin-bottom:30px}td,th{border:1px solid #334155;padding:7px}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
        "<h1>Raschke v3 all-signal event ledger and drift audit</h1><h2>Summary</h2><pre>",
        html.escape(json.dumps(summary, ensure_ascii=False, indent=2)),
        "</pre><h2>Numeric drift</h2><table><thead><tr><th>Feature</th><th>Prior mean</th><th>Second mean</th><th>PSI</th><th>KS</th><th>SMD</th><th>Flags</th></tr></thead><tbody>",
        numeric_rows,
        "</tbody></table><h2>Event-aligned paths</h2><table><thead><tr><th>Group</th><th>Events</th><th>MFE R</th><th>MAE R</th><th>60m close R</th><th>240m close R</th></tr></thead><tbody>",
        path_rows, "</tbody></table></body></html>",
    ])
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    all_events: List[Dict[str, Any]] = []
    integrity: Dict[str, Any] = {}
    reason_counts: Dict[str, Any] = {}
    for window in WINDOWS:
        integrity[window], reason_counts[window] = {}, {}
        for symbol in V2.SYMBOLS:
            raw, report = V2.load_raw(V2.raw_path(window, symbol))
            integrity[window][symbol] = report
            events, reasons = collect_symbol(raw, symbol=symbol, window_name=window)
            reason_counts[window][symbol] = reasons
            all_events.extend(events)
    all_events.sort(key=lambda row: (int(row["signal_ts"]), str(row["symbol"]), str(row["side"])))
    prior = [event for event in all_events if event["window"] == WINDOWS[0]]
    second = [event for event in all_events if event["window"] == WINDOWS[1]]
    drift = {
        "thresholds": DRIFT_THRESHOLDS,
        "numeric": numeric_drift(prior, second),
        "categorical": categorical_drift(prior, second),
    }
    paths, monthly, rolling, ready = aligned_paths(all_events), monthly_expectancy(all_events), rolling_expectancy(all_events), readiness(all_events, drift)
    ledger_payload = {
        "status": "PASS_Q4R3_RASCHKE_V3_ALL_SIGNAL_LEDGER",
        "contract": {
            "all_source_enter_signals_included": True, "cooldown_applied": False,
            "label": "TP_FIRST_vs_SL_FIRST_vs_TIMEOUT", "target_R": 2.0, "loss_cap_R": 0.5,
            "horizon_min": HORIZON_MIN, "cost_pct": COST_PCT, "no_lookahead_features": True,
        },
        "events": all_events,
    }
    drift_payload = {
        "status": "PASS_Q4R3_RASCHKE_V3_FEATURE_DRIFT",
        "prior_metrics": event_metrics(prior), "second_metrics": event_metrics(second),
        "combined_metrics": event_metrics(all_events), "drift": drift,
        "monthly_expectancy": monthly, "rolling_30_event_expectancy": rolling,
    }
    path_payload = {
        "status": "PASS_Q4R3_RASCHKE_V3_EVENT_ALIGNED_PATHS",
        "checkpoints_min": CHECKPOINTS_MIN, "groups": paths,
    }
    summary = {
        "status": "PASS_Q4R3_ROUTE_A_RASCHKE_V3_EVENT_LEDGER_DRIFT",
        "verdict": "EVENT_SAMPLE_AND_DRIFT_MEASURED_NO_MODEL_OR_STRATEGY_MUTATION",
        "event_count": len(all_events), "prior_event_count": len(prior), "second_event_count": len(second),
        "readiness": ready,
        "top_numeric_drift": [{"feature": feature, **report} for feature, report in list(drift["numeric"].items())[:10]],
        "top_categorical_drift": [{"feature": feature, **report} for feature, report in list(drift["categorical"].items())[:6]],
        "outputs": {"ledger": str(LEDGER_OUT), "drift": str(DRIFT_OUT), "aligned_paths": str(PATH_OUT), "html": str(HTML_OUT)},
        "integrity": integrity, "reason_counts": reason_counts,
        "authority": {
            "order_authority": "blocked", "execution_authority": "none", "real_order_enabled": False,
            "paper_request_written": False, "live_execution_allowed": False, "production_strategy_modified": False,
        },
    }
    atomic_json(LEDGER_OUT, ledger_payload)
    atomic_json(DRIFT_OUT, drift_payload)
    atomic_json(PATH_OUT, path_payload)
    atomic_json(SUMMARY_OUT, summary)
    write_html(summary, drift, paths)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
