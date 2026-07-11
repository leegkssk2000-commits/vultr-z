from __future__ import annotations

import html
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
PRIOR_TRADES = ROOT / "runtime" / "q4r3_route_a_raschke_forensic_trades_latest.json"
SECOND_TRADES = ROOT / "runtime" / "q4r3_route_a_raschke_second_holdout_trades_latest.json"
PRIOR_RAW_DIR = ROOT / "data" / "oos_a2" / "frozen_pre30d"
SECOND_RAW_DIR = ROOT / "data" / "oos_a3" / "raschke_second_holdout"

SUMMARY_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_loss_forensic_latest.json"
CLUSTERS_OUT = ROOT / "runtime" / "common_loss_clusters.json"
PAIRS_OUT = ROOT / "runtime" / "loss_vs_win_matched_pairs.json"
FIXES_OUT = ROOT / "runtime" / "raschke_structural_fix_candidates.json"
CHART_DIR = ROOT / "runtime" / "loss_cluster_chart_pack"
INDEX_OUT = CHART_DIR / "index.html"

MODES = ("source_core", "candle_direction")
WINDOWS = ("prior_holdout_90d", "second_holdout_90d")
COST_PCT = 0.15
MIN_CLUSTER_SL_STREAK = 3
ROLLING_N = 5
ROLLING_NET_R_MAX = -1.50
MIN_BUCKET_EVENTS_PER_WINDOW = 5
MAX_FIX_CANDIDATES = 3
MINUTE_MS = 60_000

NUMERIC_FEATURES = (
    "ema_distance_atr",
    "ema_slope_atr",
    "adx",
    "candle_body_atr",
    "close_location",
    "volume_ratio",
    "macd_signal_spread_atr",
    "macd_signal_spread_prev_atr",
    "chop_score",
)

FEATURE_BUCKETS = (
    "ema_slope_alignment",
    "adx",
    "ema_distance_atr",
    "chop_score",
    "candle_body_atr",
    "volume_ratio",
    "macd_signal_spread_atr",
    "side",
    "symbol",
)


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    payload = json.loads(path.read_text(errors="ignore"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"INVALID_JSON_OBJECT:{path}")
    return payload


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def utc_text(stamp: int) -> str:
    return str(pd.to_datetime(int(stamp), unit="ms", utc=True))


def trade_key(trade: Dict[str, Any]) -> str:
    return ".".join(
        [
            str(trade.get("mode", "unknown")),
            str(trade.get("window", "unknown")),
            str(trade.get("symbol", "unknown")),
            str(trade.get("side", "unknown")),
            str(int(trade.get("entry_ts", 0))),
        ]
    )


def net_r(trade: Dict[str, Any], cost_pct: float = COST_PCT) -> float:
    risk = max(float(trade.get("base_risk", 0.0)), 1e-12)
    entry = float(trade.get("entry", 0.0))
    return float(trade.get("gross_r", 0.0)) - entry * (float(cost_pct) / 100.0) / risk


def max_drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return float(worst)


def metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    values = [float(row["net_R"]) for row in rows]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = float(sum(wins))
    gross_loss = abs(float(sum(losses)))
    return {
        "events": len(values),
        "avg_net_R": float(statistics.fmean(values)) if values else 0.0,
        "median_net_R": float(statistics.median(values)) if values else 0.0,
        "net_sum_R": float(sum(values)),
        "positive_rate_pct": float(len(wins) / len(values) * 100.0) if values else 0.0,
        "profit_factor_R": float(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "max_drawdown_R": max_drawdown(values),
    }


def normalize_trade(raw: Dict[str, Any], *, mode: str, window: str) -> Dict[str, Any]:
    trade = dict(raw)
    trade["mode"] = mode
    trade["window"] = window
    trade["net_R"] = net_r(trade)
    trade["trade_key"] = trade_key(trade)
    trade["entry_utc"] = utc_text(int(trade.get("entry_ts", 0)))
    trade["exit_utc"] = utc_text(int(trade.get("exit_ts", 0)))
    return trade


def load_trades() -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    prior = load_json(PRIOR_TRADES)
    second = load_json(SECOND_TRADES)
    output: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for mode in MODES:
        prior_rows = prior.get("trades", {}).get(mode, {}).get("holdout_90d", [])
        second_rows = second.get("trades", {}).get(mode, [])
        if not isinstance(prior_rows, list) or not isinstance(second_rows, list):
            raise RuntimeError(f"INVALID_TRADE_PAYLOAD:{mode}")
        output[mode] = {
            "prior_holdout_90d": [
                normalize_trade(row, mode=mode, window="prior_holdout_90d")
                for row in prior_rows
                if isinstance(row, dict)
            ],
            "second_holdout_90d": [
                normalize_trade(row, mode=mode, window="second_holdout_90d")
                for row in second_rows
                if isinstance(row, dict)
            ],
        }
    return output


def raw_path(window: str, symbol: str) -> Path:
    directory = PRIOR_RAW_DIR if window == "prior_holdout_90d" else SECOND_RAW_DIR
    return directory / f"{symbol}_1m_90d_pre30d.json"


def load_raw(path: Path) -> pd.DataFrame:
    payload = load_json(path)
    rows = payload.get("rows", [])
    records: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        stamp = int(float(row[0]))
        if abs(stamp) < 100_000_000_000:
            stamp *= 1000
        records.append(
            {
                "ts": stamp,
                "ts_dt": pd.to_datetime(stamp, unit="ms", utc=True),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        raise RuntimeError(f"EMPTY_RAW:{path}")
    return frame.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)


def path_is_contiguous(frame: pd.DataFrame) -> bool:
    if len(frame) < 2:
        return True
    return bool((frame["ts"].diff().dropna() == MINUTE_MS).all())


def enrich_excursions(trade: Dict[str, Any], raw: pd.DataFrame) -> Dict[str, Any]:
    result = dict(trade)
    entry_ts = int(trade["entry_ts"])
    exit_ts = int(trade["exit_ts"])
    entry = float(trade["entry"])
    risk = max(float(trade["base_risk"]), 1e-12)
    side = str(trade["side"])
    path = raw[(raw["ts"] >= entry_ts) & (raw["ts"] <= exit_ts)].copy()
    result["path_gap"] = not path_is_contiguous(path)
    if path.empty or result["path_gap"]:
        for key in (
            "mfe_R",
            "mae_R",
            "minutes_to_mfe",
            "minutes_to_mae",
            "post_exit_best_R_120",
            "post_exit_best_R_240",
            "post_exit_best_R_480",
        ):
            result[key] = None
        return result

    if side == "long":
        favorable = (path["high"] - entry) / risk
        adverse = (entry - path["low"]) / risk
    else:
        favorable = (entry - path["low"]) / risk
        adverse = (path["high"] - entry) / risk
    mfe_idx = int(favorable.idxmax())
    mae_idx = int(adverse.idxmax())
    result["mfe_R"] = float(favorable.max())
    result["mae_R"] = float(adverse.max())
    result["minutes_to_mfe"] = int((int(raw.loc[mfe_idx, "ts"]) - entry_ts) / MINUTE_MS)
    result["minutes_to_mae"] = int((int(raw.loc[mae_idx, "ts"]) - entry_ts) / MINUTE_MS)

    for minutes in (120, 240, 480):
        post = raw[(raw["ts"] > exit_ts) & (raw["ts"] <= exit_ts + minutes * MINUTE_MS)]
        if post.empty or not path_is_contiguous(post):
            result[f"post_exit_best_R_{minutes}"] = None
        elif side == "long":
            result[f"post_exit_best_R_{minutes}"] = float((post["high"].max() - entry) / risk)
        else:
            result[f"post_exit_best_R_{minutes}"] = float((entry - post["low"].min()) / risk)
    return result


def enrich_all(
    trades: Dict[str, Dict[str, List[Dict[str, Any]]]]
) -> Tuple[Dict[str, Dict[str, List[Dict[str, Any]]]], Dict[Tuple[str, str], pd.DataFrame]]:
    cache: Dict[Tuple[str, str], pd.DataFrame] = {}
    output: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for mode, windows in trades.items():
        output[mode] = {}
        for window, rows in windows.items():
            enriched: List[Dict[str, Any]] = []
            for trade in rows:
                symbol = str(trade["symbol"])
                key = (window, symbol)
                if key not in cache:
                    cache[key] = load_raw(raw_path(window, symbol))
                enriched.append(enrich_excursions(trade, cache[key]))
            output[mode][window] = enriched
    return output, cache


def merge_intervals(intervals: Sequence[Tuple[int, int, str]]) -> List[Tuple[int, int, List[str]]]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda row: (row[0], row[1]))
    merged: List[Tuple[int, int, List[str]]] = []
    start, end, trigger = ordered[0]
    triggers = [trigger]
    for next_start, next_end, next_trigger in ordered[1:]:
        if next_start <= end + 1:
            end = max(end, next_end)
            if next_trigger not in triggers:
                triggers.append(next_trigger)
        else:
            merged.append((start, end, triggers))
            start, end, triggers = next_start, next_end, [next_trigger]
    merged.append((start, end, triggers))
    return merged


def detect_clusters(rows: Sequence[Dict[str, Any]], mode: str, window: str) -> List[Dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (int(row["entry_ts"]), str(row["symbol"])))
    intervals: List[Tuple[int, int, str]] = []

    index = 0
    while index < len(ordered):
        if str(ordered[index].get("outcome")) != "SL":
            index += 1
            continue
        end = index
        while end + 1 < len(ordered) and str(ordered[end + 1].get("outcome")) == "SL":
            end += 1
        if end - index + 1 >= MIN_CLUSTER_SL_STREAK:
            intervals.append((index, end, f"consecutive_sl>={MIN_CLUSTER_SL_STREAK}"))
        index = end + 1

    for start in range(0, max(0, len(ordered) - ROLLING_N + 1)):
        end = start + ROLLING_N - 1
        total = sum(float(row["net_R"]) for row in ordered[start : end + 1])
        if total <= ROLLING_NET_R_MAX:
            intervals.append((start, end, f"rolling_{ROLLING_N}_net<={ROLLING_NET_R_MAX}R"))

    clusters: List[Dict[str, Any]] = []
    for cluster_index, (start, end, triggers) in enumerate(merge_intervals(intervals), start=1):
        members = ordered[start : end + 1]
        values = [float(row["net_R"]) for row in members]
        cluster_id = f"{mode}.{window}.C{cluster_index:02d}"
        for row in members:
            row.setdefault("cluster_ids", []).append(cluster_id)
        clusters.append(
            {
                "cluster_id": cluster_id,
                "mode": mode,
                "window": window,
                "triggers": triggers,
                "start_utc": utc_text(int(members[0]["entry_ts"])),
                "end_utc": utc_text(int(members[-1]["exit_ts"])),
                "events": len(members),
                "net_sum_R": float(sum(values)),
                "avg_net_R": float(statistics.fmean(values)),
                "max_drawdown_R": max_drawdown(values),
                "sl_count": sum(str(row.get("outcome")) == "SL" for row in members),
                "timeout_count": sum(str(row.get("outcome")) == "TIMEOUT" for row in members),
                "symbols": sorted({str(row["symbol"]) for row in members}),
                "sides": sorted({str(row["side"]) for row in members}),
                "trade_keys": [str(row["trade_key"]) for row in members],
                "mean_mfe_R": mean_present(row.get("mfe_R") for row in members),
                "mean_mae_R": mean_present(row.get("mae_R") for row in members),
                "stop_recovery_240_pct": stop_recovery_rate(members, 240),
            }
        )
    return clusters


def mean_present(values: Iterable[Any]) -> Optional[float]:
    numbers = [number for value in values if (number := safe_float(value)) is not None]
    return float(statistics.fmean(numbers)) if numbers else None


def stop_recovery_rate(rows: Sequence[Dict[str, Any]], minutes: int) -> Optional[float]:
    stopped = [row for row in rows if str(row.get("outcome")) == "SL"]
    values = [safe_float(row.get(f"post_exit_best_R_{minutes}")) for row in stopped]
    observed = [value for value in values if value is not None]
    if not observed:
        return None
    return float(sum(value >= 0.0 for value in observed) / len(observed) * 100.0)


def bucket(value: Any, thresholds: Tuple[float, float], labels: Tuple[str, str, str]) -> str:
    number = safe_float(value)
    if number is None:
        return "missing"
    if number <= thresholds[0]:
        return labels[0]
    if number <= thresholds[1]:
        return labels[1]
    return labels[2]


def feature_bucket(trade: Dict[str, Any], feature: str) -> str:
    if feature in {"side", "symbol"}:
        return str(trade.get(feature, "missing"))
    if feature == "adx":
        return bucket(trade.get("adx"), (17.0, 25.0), ("weak<=17", "medium<=25", "strong>25"))
    if feature == "ema_distance_atr":
        return bucket(trade.get(feature), (0.75, 1.50), ("near<=0.75", "mid<=1.50", "far>1.50"))
    if feature == "chop_score":
        return bucket(trade.get(feature), (0.15, 0.30), ("clean<=0.15", "mixed<=0.30", "choppy>0.30"))
    if feature == "candle_body_atr":
        return bucket(trade.get(feature), (0.10, 0.25), ("small<=0.10", "medium<=0.25", "large>0.25"))
    if feature == "volume_ratio":
        return bucket(trade.get(feature), (0.80, 1.20), ("low<=0.80", "normal<=1.20", "high>1.20"))
    if feature == "macd_signal_spread_atr":
        return bucket(trade.get(feature), (0.005, 0.015), ("weak<=0.005", "medium<=0.015", "strong>0.015"))
    if feature == "ema_slope_alignment":
        slope = safe_float(trade.get("ema_slope_atr"))
        if slope is None:
            return "missing"
        side = str(trade.get("side"))
        aligned = slope > 0 if side == "long" else slope < 0
        if not aligned:
            return "misaligned"
        if abs(slope) < 0.015:
            return "aligned_weak"
        return "aligned_strong"
    return "unknown"


def bucket_report(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    report = metrics(rows)
    report["cluster_event_pct"] = float(
        sum(bool(row.get("cluster_ids")) for row in rows) / len(rows) * 100.0
    ) if rows else 0.0
    return report


def recurring_signatures(
    mode_rows: Dict[str, List[Dict[str, Any]]]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    matrix: Dict[str, Any] = {}
    adverse: List[Dict[str, Any]] = []
    for feature in FEATURE_BUCKETS:
        matrix[feature] = {}
        all_labels = sorted(
            {
                feature_bucket(row, feature)
                for window in WINDOWS
                for row in mode_rows[window]
            }
        )
        for label in all_labels:
            window_reports: Dict[str, Any] = {}
            combined: List[Dict[str, Any]] = []
            qualifies = True
            for window in WINDOWS:
                selected = [
                    row for row in mode_rows[window]
                    if feature_bucket(row, feature) == label
                ]
                window_reports[window] = bucket_report(selected)
                combined.extend(selected)
                if len(selected) < MIN_BUCKET_EVENTS_PER_WINDOW or window_reports[window]["avg_net_R"] >= 0:
                    qualifies = False
            combined_report = bucket_report(combined)
            matrix[feature][label] = {
                "windows": window_reports,
                "combined": combined_report,
                "recurs_negative_both_windows": qualifies,
            }
            if qualifies:
                min_events = min(window_reports[window]["events"] for window in WINDOWS)
                impact = abs(float(combined_report["avg_net_R"]))
                cluster_rate = float(combined_report["cluster_event_pct"]) / 100.0
                adverse.append(
                    {
                        "feature": feature,
                        "bucket": label,
                        "windows": window_reports,
                        "combined": combined_report,
                        "evidence_score": float(impact * math.sqrt(min_events) * (1.0 + cluster_rate)),
                    }
                )
    adverse.sort(key=lambda row: (float(row["evidence_score"]), -float(row["combined"]["avg_net_R"])), reverse=True)
    return matrix, adverse


def standardized_features(rows: Sequence[Dict[str, Any]]) -> Dict[str, Tuple[float, float]]:
    output: Dict[str, Tuple[float, float]] = {}
    for feature in NUMERIC_FEATURES:
        values = [number for row in rows if (number := safe_float(row.get(feature))) is not None]
        if len(values) < 2:
            output[feature] = (0.0, 1.0)
        else:
            mean = statistics.fmean(values)
            std = statistics.pstdev(values) or 1.0
            output[feature] = (float(mean), float(std))
    return output


def feature_distance(left: Dict[str, Any], right: Dict[str, Any], scales: Dict[str, Tuple[float, float]]) -> float:
    terms: List[float] = []
    for feature in NUMERIC_FEATURES:
        a = safe_float(left.get(feature))
        b = safe_float(right.get(feature))
        if a is None or b is None:
            continue
        _, std = scales[feature]
        terms.append(((a - b) / std) ** 2)
    if str(left.get("symbol")) != str(right.get("symbol")):
        terms.append(1.0)
    if str(left.get("side")) != str(right.get("side")):
        terms.append(1.5)
    return float(math.sqrt(sum(terms))) if terms else 999.0


def build_matched_pairs(rows: Sequence[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    losses = sorted(
        [row for row in rows if float(row["net_R"]) < 0],
        key=lambda row: (not bool(row.get("cluster_ids")), float(row["net_R"])),
    )
    wins = [row for row in rows if float(row["net_R"]) > 0]
    scales = standardized_features(rows)
    pairs: List[Dict[str, Any]] = []
    used_wins: set[str] = set()
    for loss in losses:
        candidates = [
            win for win in wins
            if str(win.get("mode")) == str(loss.get("mode"))
            and str(win.get("window")) == str(loss.get("window"))
        ]
        if not candidates:
            continue
        ranked = sorted(candidates, key=lambda win: feature_distance(loss, win, scales))
        winner = next((row for row in ranked if row["trade_key"] not in used_wins), ranked[0])
        used_wins.add(str(winner["trade_key"]))
        pairs.append(
            {
                "loss_trade": compact_trade(loss),
                "matched_win_trade": compact_trade(winner),
                "feature_distance": feature_distance(loss, winner, scales),
                "feature_delta": {
                    feature: {
                        "loss": loss.get(feature),
                        "win": winner.get(feature),
                    }
                    for feature in NUMERIC_FEATURES
                },
            }
        )
        if len(pairs) >= limit:
            break
    return pairs


def compact_trade(row: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "trade_key",
        "mode",
        "window",
        "symbol",
        "side",
        "entry_ts",
        "exit_ts",
        "entry_utc",
        "exit_utc",
        "entry",
        "exit",
        "stop",
        "target",
        "outcome",
        "net_R",
        "gross_r",
        "mfe_R",
        "mae_R",
        "minutes_to_mfe",
        "minutes_to_mae",
        "post_exit_best_R_120",
        "post_exit_best_R_240",
        "post_exit_best_R_480",
        "cluster_ids",
    ) + NUMERIC_FEATURES
    return {key: row.get(key) for key in keys}


def stop_recovery_summary(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    stopped = [row for row in rows if str(row.get("outcome")) == "SL"]
    output: Dict[str, Any] = {"sl_events": len(stopped)}
    for minutes in (120, 240, 480):
        values = [safe_float(row.get(f"post_exit_best_R_{minutes}")) for row in stopped]
        observed = [value for value in values if value is not None]
        output[f"observed_{minutes}"] = len(observed)
        output[f"recovered_to_entry_pct_{minutes}"] = (
            float(sum(value >= 0.0 for value in observed) / len(observed) * 100.0)
            if observed else None
        )
        output[f"reached_plus_0_5R_pct_{minutes}"] = (
            float(sum(value >= 0.5 for value in observed) / len(observed) * 100.0)
            if observed else None
        )
    return output


def make_fix_candidates(
    adverse: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_key = {(row["feature"], row["bucket"]): row for row in adverse}
    candidates: List[Dict[str, Any]] = []

    rules = [
        (
            ("ema_slope_alignment", "misaligned"),
            "ema200_direction_alignment_guard",
            "Block entries only when EMA200 slope opposes trade direction; do not tune the slope magnitude.",
            ["source_core unchanged", "reject opposite-slope cross", "retest as one isolated structural delta"],
        ),
        (
            ("adx", "weak<=17"),
            "weak_trend_regime_guard",
            "Block zero-zone crosses when ADX is at or below the predeclared weak-trend boundary of 17.",
            ["retain EMA200/MACD core", "require ADX>17", "no other entry or exit change"],
        ),
        (
            ("ema_distance_atr", "near<=0.75"),
            "ema200_proximity_guard",
            "Reject crosses occurring within 0.75 ATR of EMA200 where whipsaw repeatedly dominates.",
            ["retain source cross", "require EMA distance>0.75 ATR", "leave max-distance and exits frozen"],
        ),
        (
            ("chop_score", "choppy>0.30"),
            "chop_guard",
            "Reject only the predeclared choppy bucket above 0.30; leave clean and mixed regimes intact.",
            ["retain source cross", "block chop_score>0.30", "leave contract unchanged"],
        ),
        (
            ("side", "short"),
            "short_route_separation",
            "Route short signals to Reserve until a short-specific trend filter is independently validated.",
            ["long core unchanged", "short becomes observer-only", "test short route separately"],
        ),
    ]
    for key, title, why, steps in rules:
        evidence = by_key.get(key)
        if evidence is None:
            continue
        candidates.append(
            {
                "title": title,
                "why": why,
                "steps": steps,
                "evidence": evidence,
                "change_scope": "single_structure_only",
                "auto_apply": False,
            }
        )

    recovery = stop_recovery_summary(rows)
    recovered_240 = safe_float(recovery.get("recovered_to_entry_pct_240"))
    if recovered_240 is not None and recovered_240 >= 40.0:
        candidates.append(
            {
                "title": "entry_confirmation_or_retest_delay",
                "why": "At least 40% of stopped trades recovered to entry within 240 minutes; widening the stop is forbidden, so test delayed confirmation/retest instead.",
                "steps": [
                    "keep -0.5R loss cap",
                    "delay entry by one completed confirmation event",
                    "reject if reward distance is no longer at least 2R",
                ],
                "evidence": recovery,
                "change_scope": "single_structure_only",
                "auto_apply": False,
            }
        )

    candidates.sort(
        key=lambda row: float(row.get("evidence", {}).get("evidence_score", 0.0)),
        reverse=True,
    )
    return candidates[:MAX_FIX_CANDIDATES]


def resample_60m(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    frame["bucket"] = frame["ts_dt"].dt.floor("60min")
    bars = frame.groupby("bucket").agg(
        ts=("ts", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        count=("ts", "count"),
    ).reset_index()
    bars["ema200"] = bars["close"].ewm(span=200, adjust=False, min_periods=200).mean()
    return bars


def chart_svg(trade: Dict[str, Any], raw: pd.DataFrame, before: int = 40, after: int = 30) -> str:
    bars = resample_60m(raw)
    entry_dt = pd.to_datetime(int(trade["entry_ts"]), unit="ms", utc=True).floor("60min")
    positions = bars.index[bars["bucket"] == entry_dt].tolist()
    if not positions:
        return "<svg width='1200' height='420'><text x='20' y='40'>entry bar unavailable</text></svg>"
    center = positions[0]
    view = bars.iloc[max(0, center - before) : min(len(bars), center + after + 1)].reset_index(drop=True)
    width, height = 1200, 420
    left, right, top, bottom = 60, 20, 20, 55
    plot_w, plot_h = width - left - right, height - top - bottom
    price_values: List[float] = []
    for column in ("high", "low", "ema200"):
        price_values.extend([float(value) for value in view[column].dropna().tolist()])
    for key in ("entry", "stop", "target", "exit"):
        number = safe_float(trade.get(key))
        if number is not None:
            price_values.append(number)
    low_price, high_price = min(price_values), max(price_values)
    padding = max((high_price - low_price) * 0.05, high_price * 0.001)
    low_price -= padding
    high_price += padding

    def x(index: int) -> float:
        return left + (index + 0.5) * plot_w / max(len(view), 1)

    def y(price: float) -> float:
        return top + (high_price - price) / max(high_price - low_price, 1e-12) * plot_h

    elements = [
        f"<svg viewBox='0 0 {width} {height}' width='{width}' height='{height}' xmlns='http://www.w3.org/2000/svg'>",
        "<rect width='100%' height='100%' fill='#0b0f14'/>",
    ]
    bar_width = max(plot_w / max(len(view), 1) * 0.55, 2.0)
    for index, row in view.iterrows():
        xi = x(index)
        open_y, close_y = y(float(row["open"])), y(float(row["close"]))
        high_y, low_y = y(float(row["high"])), y(float(row["low"]))
        up = float(row["close"]) >= float(row["open"])
        color = "#31c48d" if up else "#f05252"
        elements.append(f"<line x1='{xi:.2f}' y1='{high_y:.2f}' x2='{xi:.2f}' y2='{low_y:.2f}' stroke='{color}' stroke-width='1'/>")
        body_y = min(open_y, close_y)
        body_h = max(abs(close_y - open_y), 1.0)
        elements.append(f"<rect x='{xi-bar_width/2:.2f}' y='{body_y:.2f}' width='{bar_width:.2f}' height='{body_h:.2f}' fill='{color}'/>")

    ema_points = [
        f"{x(index):.2f},{y(float(value)):.2f}"
        for index, value in enumerate(view["ema200"].tolist())
        if safe_float(value) is not None
    ]
    if ema_points:
        elements.append(f"<polyline points='{' '.join(ema_points)}' fill='none' stroke='#f6c85f' stroke-width='2'/>")

    levels = (
        ("entry", "#4c9aff"),
        ("stop", "#ff6b6b"),
        ("target", "#5ee28a"),
        ("exit", "#c792ea"),
    )
    for key, color in levels:
        number = safe_float(trade.get(key))
        if number is None:
            continue
        yi = y(number)
        elements.append(f"<line x1='{left}' y1='{yi:.2f}' x2='{width-right}' y2='{yi:.2f}' stroke='{color}' stroke-dasharray='5 4' stroke-width='1'/>")
        elements.append(f"<text x='{left+4}' y='{yi-4:.2f}' fill='{color}' font-size='12'>{html.escape(key)} {number:.6g}</text>")

    entry_index = center - max(0, center - before)
    elements.append(f"<line x1='{x(entry_index):.2f}' y1='{top}' x2='{x(entry_index):.2f}' y2='{height-bottom}' stroke='#ffffff' stroke-width='1.5'/>")
    elements.append(f"<text x='{left}' y='{height-20}' fill='#cbd5e1' font-size='12'>{html.escape(str(view['bucket'].iloc[0]))} → {html.escape(str(view['bucket'].iloc[-1]))}</text>")
    elements.append("</svg>")
    return "".join(elements)


def write_chart_pack(
    pairs: Sequence[Dict[str, Any]],
    all_rows: Dict[str, Dict[str, Any]],
    raw_cache: Dict[Tuple[str, str], pd.DataFrame],
    clusters: Sequence[Dict[str, Any]],
) -> List[str]:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    pages: List[str] = []
    cards: List[str] = []
    for index, pair in enumerate(pairs[:5], start=1):
        pair_cards: List[str] = []
        for label, key_name in (("LOSS", "loss_trade"), ("MATCHED WIN", "matched_win_trade")):
            compact = pair[key_name]
            key = str(compact["trade_key"])
            trade = all_rows[key]
            raw = raw_cache[(str(trade["window"]), str(trade["symbol"]))]
            svg = chart_svg(trade, raw)
            filename = f"pair_{index:02d}_{label.lower().replace(' ', '_')}.html"
            page = "".join(
                [
                    "<!doctype html><html><head><meta charset='utf-8'><title>Raschke forensic chart</title>",
                    "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}pre{white-space:pre-wrap;background:#111827;padding:12px}</style></head><body>",
                    f"<h2>{html.escape(label)} — {html.escape(key)}</h2>",
                    svg,
                    f"<pre>{html.escape(json.dumps(compact, ensure_ascii=False, indent=2))}</pre>",
                    "</body></html>",
                ]
            )
            (CHART_DIR / filename).write_text(page, encoding="utf-8")
            pages.append(filename)
            pair_cards.append(
                f"<div class='card'><h3>{html.escape(label)}</h3>{svg}<pre>{html.escape(json.dumps(compact, ensure_ascii=False, indent=2))}</pre></div>"
            )
        cards.append(f"<section><h2>Matched pair {index} · distance {pair['feature_distance']:.3f}</h2>{''.join(pair_cards)}</section>")

    cluster_rows = "".join(
        f"<tr><td>{html.escape(str(row['cluster_id']))}</td><td>{html.escape(str(row['window']))}</td><td>{row['events']}</td><td>{row['net_sum_R']:.3f}</td><td>{html.escape(','.join(row['symbols']))}</td><td>{html.escape(','.join(row['triggers']))}</td></tr>"
        for row in sorted(clusters, key=lambda item: float(item["net_sum_R"]))[:20]
    )
    index_html = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Raschke loss-cluster forensic</title>",
            "<style>body{background:#070b10;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #334155;padding:6px}.card{background:#111827;margin:12px 0;padding:12px;overflow:auto}pre{white-space:pre-wrap;font-size:12px}section{margin-bottom:36px}</style></head><body>",
            "<h1>Raschke cross-window loss-cluster forensic</h1>",
            "<p>Two independent 90-day windows. Cost 0.15%. No parameter changes and no production writes.</p>",
            "<h2>Worst clusters</h2><table><thead><tr><th>ID</th><th>Window</th><th>Events</th><th>Net R</th><th>Symbols</th><th>Triggers</th></tr></thead><tbody>",
            cluster_rows,
            "</tbody></table>",
            "".join(cards),
            "</body></html>",
        ]
    )
    INDEX_OUT.write_text(index_html, encoding="utf-8")
    return pages


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    trades = load_trades()
    trades, raw_cache = enrich_all(trades)

    all_clusters: List[Dict[str, Any]] = []
    signature_reports: Dict[str, Any] = {}
    adverse_by_mode: Dict[str, List[Dict[str, Any]]] = {}
    all_rows_list: List[Dict[str, Any]] = []
    window_metrics: Dict[str, Any] = {}

    for mode in MODES:
        window_metrics[mode] = {}
        for window in WINDOWS:
            rows = trades[mode][window]
            window_metrics[mode][window] = metrics(rows)
            all_clusters.extend(detect_clusters(rows, mode, window))
            all_rows_list.extend(rows)
        matrix, adverse = recurring_signatures(trades[mode])
        signature_reports[mode] = matrix
        adverse_by_mode[mode] = adverse

    all_rows_by_key = {str(row["trade_key"]): row for row in all_rows_list}
    pair_input = [row for row in all_rows_list if str(row.get("mode")) == "candle_direction"]
    pairs = build_matched_pairs(pair_input)
    pages = write_chart_pack(pairs, all_rows_by_key, raw_cache, all_clusters)

    primary_rows = [row for row in all_rows_list if str(row.get("mode")) == "candle_direction"]
    fixes = make_fix_candidates(adverse_by_mode["candle_direction"], primary_rows)

    clusters_payload = {
        "status": "PASS_Q4R3_RASCHKE_COMMON_LOSS_CLUSTERS",
        "definition": {
            "consecutive_sl_min": MIN_CLUSTER_SL_STREAK,
            "rolling_events": ROLLING_N,
            "rolling_net_R_max": ROLLING_NET_R_MAX,
            "cost_pct_round_trip": COST_PCT,
        },
        "clusters": sorted(all_clusters, key=lambda row: float(row["net_sum_R"])),
        "recurring_adverse_signatures": adverse_by_mode,
        "signature_matrix": signature_reports,
    }
    pairs_payload = {
        "status": "PASS_Q4R3_RASCHKE_LOSS_WIN_MATCHED_PAIRS",
        "mode": "candle_direction",
        "pairs": pairs,
        "chart_pack_index": str(INDEX_OUT),
        "chart_pages": pages,
    }
    fixes_payload = {
        "status": "PASS_Q4R3_RASCHKE_STRUCTURAL_FIX_CANDIDATES",
        "policy": {
            "max_candidates": MAX_FIX_CANDIDATES,
            "single_structure_delta_only": True,
            "auto_apply": False,
            "next_validation": "untouched_third_independent_window",
            "acceptance": {
                "sample_retention_pct_min": 70.0,
                "avg_R_improvement_min": 0.05,
                "profit_factor_improvement_min": 0.15,
                "mdd_reduction_pct_min": 20.0,
                "positive_symbols_min": 3,
                "cost_0.20_avg_R_min_exclusive": 0.0,
            },
        },
        "candidates": fixes,
        "stop_recovery": stop_recovery_summary(primary_rows),
    }
    summary = {
        "status": "PASS_Q4R3_ROUTE_A_RASCHKE_LOSS_CLUSTER_FORENSIC",
        "verdict": "FORENSIC_COMPLETE_NOT_A_STRATEGY_REJECTION",
        "purpose": "identify repeated pre-entry loss structures across two independent 90d windows before any Raschke v2 change",
        "window_metrics_cost_0.15": window_metrics,
        "cluster_count": len(all_clusters),
        "top_common_adverse_signatures": adverse_by_mode,
        "structural_fix_candidates": fixes,
        "outputs": {
            "clusters": str(CLUSTERS_OUT),
            "matched_pairs": str(PAIRS_OUT),
            "fix_candidates": str(FIXES_OUT),
            "chart_pack": str(INDEX_OUT),
        },
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
            "production_strategy_modified": False,
        },
    }

    atomic_json(CLUSTERS_OUT, clusters_payload)
    atomic_json(PAIRS_OUT, pairs_payload)
    atomic_json(FIXES_OUT, fixes_payload)
    atomic_json(SUMMARY_OUT, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
