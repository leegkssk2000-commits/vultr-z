from __future__ import annotations

import importlib.util
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
OVERLAY_ROOT = Path(os.environ.get("Q4R3_ROUTE_A_OVERLAY_ROOT", "/tmp/q4r3-route-a-v2"))
PRIOR_RAW_DIR = ROOT / "data" / "oos_a2" / "frozen_pre30d"
SECOND_RAW_DIR = ROOT / "data" / "oos_a3" / "raschke_second_holdout"
PAIR_SOURCE = ROOT / "runtime" / "loss_vs_win_matched_pairs.json"
OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v2_tournament_latest.json"
TRADES_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v2_trades_latest.json"
CHART_AUDIT_OUT = ROOT / "runtime" / "raschke_v2_chart_audit_latest.json"
CHART_AUDIT_HTML = ROOT / "runtime" / "raschke_v2_chart_audit_latest.html"

sys.path.insert(0, str(OVERLAY_ROOT))
sys.path.insert(1, str(ROOT))


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_module(
    "q4r3_v2_tournament_base",
    OVERLAY_ROOT / "tools" / "q4r3_route_a_video_fidelity_tournament.py",
)
FORENSIC = _load_module(
    "q4r3_v2_forensic_base",
    OVERLAY_ROOT / "tools" / "q4r3_route_a_raschke_forensic_rescue.py",
)
STRATEGY = __import__(
    "backend.strategies.raschke_macd_ema200",
    fromlist=["RaschkeMacdEma200Config", "strategy"],
)
Config = STRATEGY.RaschkeMacdEma200Config
strategy = STRATEGY.strategy

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
WINDOWS = ("prior_holdout_90d", "second_holdout_90d")
COST_LEVELS = (0.10, 0.15, 0.20)
TIMEFRAME_MIN = 60
WINDOW_BARS = 320
TIMEOUT_MIN = 480
COOLDOWN_MIN = 60
MINUTE_MS = 60_000
CONTRACT = {"loss_cap_r": 0.50, "target_r": 2.0}

# Each candidate changes one entry structure only. Thresholds were declared by
# the completed cross-window forensic before this tournament.
ENTRY_CANDIDATES: Dict[str, Dict[str, Any]] = {
    "baseline_candle_direction": {
        "mechanism": "source EMA200/MACD core plus directional candle",
        "single_delta": None,
    },
    "v2_proximity_guard": {
        "mechanism": "baseline plus reject EMA200 distance <=0.75 ATR",
        "single_delta": "ema_distance_atr>0.75",
    },
    "v2_direction_alignment": {
        "mechanism": "baseline plus EMA200 slope direction must match trade side",
        "single_delta": "ema_slope_direction_aligned",
    },
    "v2_macd_strength": {
        "mechanism": "baseline plus MACD signal spread >0.015 ATR",
        "single_delta": "macd_signal_spread_atr>0.015",
    },
}

# Exit overlays are causal observers. They are evaluated with independent
# cooldown state, not post-hoc arithmetic on the baseline trade list.
EXIT_POLICIES: Dict[str, Dict[str, Any]] = {
    "fixed_2R": {
        "trigger_r": None,
        "partial_fraction": 0.0,
        "move_stop_to_entry": False,
    },
    "breakeven_after_1R": {
        "trigger_r": 1.0,
        "partial_fraction": 0.0,
        "move_stop_to_entry": True,
    },
    "partial30_be_after_1R": {
        "trigger_r": 1.0,
        "partial_fraction": 0.30,
        "move_stop_to_entry": True,
    },
}

RESCUE_GATE = {
    "sample_retention_pct_min": 70.0,
    "avg_R_improvement_min": 0.05,
    "profit_factor_improvement_min": 0.15,
    "mdd_reduction_pct_min": 20.0,
    "positive_symbols_min": 3,
    "cost_0.20_avg_R_min_exclusive": 0.0,
    "each_window_avg_R_floor": -0.05,
}


def raw_path(window: str, symbol: str) -> Path:
    if window == "prior_holdout_90d":
        return PRIOR_RAW_DIR / f"{symbol}_1m_90d_pre30d.json"
    if window == "second_holdout_90d":
        return SECOND_RAW_DIR / f"{symbol}_1m_90d_pre90d.json"
    raise KeyError(window)


def timestamp_ms(value: Any) -> int:
    stamp = int(float(value))
    return stamp * 1000 if abs(stamp) < 100_000_000_000 else stamp


def load_raw(path: Path) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    payload = json.loads(path.read_text(errors="ignore"))
    rows = payload.get("rows", [])
    records: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        stamp = timestamp_ms(row[0])
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
    frame = frame.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
    frame["raw_idx"] = range(len(frame))
    diffs = frame["ts"].diff().dropna()
    gaps = diffs[diffs != MINUTE_MS]
    missing_minutes = int(sum(max(int(diff // MINUTE_MS) - 1, 0) for diff in gaps.tolist()))
    valid_sparse = bool(len(gaps) <= 1 and missing_minutes <= 5)
    if gaps.any() and not valid_sparse:
        raise RuntimeError(f"UNAPPROVED_RAW_GAPS:{path}:ranges={len(gaps)}:minutes={missing_minutes}")
    return frame, {
        "path": str(path),
        "rows": len(frame),
        "gap_ranges": int(len(gaps)),
        "missing_minutes": missing_minutes,
        "mode": "sparse_gap_quarantine" if len(gaps) else "strict_contiguous",
        "valid": True,
    }


def window_is_contiguous(window: pd.DataFrame) -> bool:
    if window.empty or not bool(window["complete"].all()):
        return False
    diffs = window["bucket"].diff().dt.total_seconds().dropna()
    return bool((diffs == TIMEFRAME_MIN * 60).all())


def entry_pass(candidate: str, result: Dict[str, Any]) -> bool:
    if candidate == "baseline_candle_direction":
        return True
    distance = float(result.get("ema_distance_atr", float("nan")))
    slope = float(result.get("ema_slope_atr", float("nan")))
    spread = float(result.get("macd_signal_spread_atr", float("nan")))
    side = str(result.get("side", ""))
    if candidate == "v2_proximity_guard":
        return math.isfinite(distance) and distance > 0.75
    if candidate == "v2_direction_alignment":
        return math.isfinite(slope) and ((side == "long" and slope > 0) or (side == "short" and slope < 0))
    if candidate == "v2_macd_strength":
        return math.isfinite(spread) and spread > 0.015
    raise KeyError(candidate)


def horizon_contiguous(raw: pd.DataFrame, start_idx: int, end_idx: int) -> bool:
    path = raw.iloc[start_idx : end_idx + 1]
    if len(path) < 2:
        return True
    return bool((path["ts"].diff().dropna() == MINUTE_MS).all())


def simulate_policy(
    raw: pd.DataFrame,
    *,
    entry_idx: int,
    side: str,
    signal_entry: float,
    native_stop: float,
    policy_name: str,
) -> Optional[Dict[str, Any]]:
    if entry_idx < 0 or entry_idx >= len(raw):
        return None
    policy = EXIT_POLICIES[policy_name]
    actual_entry = float(raw.iloc[entry_idx]["open"])
    base_risk = abs(float(signal_entry) - float(native_stop))
    if not math.isfinite(base_risk) or base_risk <= 0:
        return None
    direction = 1.0 if side == "long" else -1.0
    stop = actual_entry - direction * base_risk * CONTRACT["loss_cap_r"]
    target = actual_entry + direction * base_risk * CONTRACT["target_r"]
    trigger_r = policy["trigger_r"]
    trigger = None if trigger_r is None else actual_entry + direction * base_risk * float(trigger_r)
    partial_fraction = float(policy["partial_fraction"])
    activated = False
    partial_realized_r = 0.0
    remaining_fraction = 1.0

    last_idx = min(len(raw) - 1, entry_idx + TIMEOUT_MIN - 1)
    if not horizon_contiguous(raw, entry_idx, last_idx):
        return None

    exit_idx = last_idx
    exit_price = float(raw.iloc[last_idx]["close"])
    outcome = "TIMEOUT"
    ambiguity = False

    for idx in range(entry_idx, last_idx + 1):
        row = raw.iloc[idx]
        high = float(row["high"])
        low = float(row["low"])
        active_stop = actual_entry if activated and bool(policy["move_stop_to_entry"]) else stop
        if side == "long":
            stop_hit = low <= active_stop
            target_hit = high >= target
        else:
            stop_hit = high >= active_stop
            target_hit = low <= target

        if stop_hit and target_hit:
            ambiguity = True
            outcome = "BE" if activated and active_stop == actual_entry else "SL"
            exit_idx = idx
            exit_price = active_stop
            break
        if stop_hit:
            outcome = "BE" if activated and active_stop == actual_entry else "SL"
            exit_idx = idx
            exit_price = active_stop
            break
        if target_hit:
            outcome = "PARTIAL_TP" if partial_fraction > 0 and activated else "TP"
            exit_idx = idx
            exit_price = target
            break

        if not activated and trigger is not None:
            trigger_hit = high >= trigger if side == "long" else low <= trigger
            if trigger_hit:
                activated = True
                if partial_fraction > 0:
                    partial_realized_r = partial_fraction * float(trigger_r)
                    remaining_fraction = 1.0 - partial_fraction

    exit_r = direction * (float(exit_price) - actual_entry) / base_risk
    gross_r = partial_realized_r + remaining_fraction * exit_r
    if activated and outcome == "BE" and partial_fraction > 0:
        outcome = "PARTIAL_BE"
    return {
        "entry_idx": int(entry_idx),
        "exit_idx": int(exit_idx),
        "entry_ts": int(raw.iloc[entry_idx]["ts"]),
        "exit_ts": int(raw.iloc[exit_idx]["ts"]),
        "entry": actual_entry,
        "exit": float(exit_price),
        "stop": float(stop),
        "target": float(target),
        "base_risk": float(base_risk),
        "risk_pct": float(base_risk / actual_entry * 100.0),
        "gross_r": float(gross_r),
        "outcome": outcome,
        "ambiguity": ambiguity,
        "exit_policy": policy_name,
        "triggered_1R": bool(activated),
        "partial_fraction": partial_fraction,
    }


def signal_metadata(result: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "ema_distance_atr",
        "ema_slope_atr",
        "adx",
        "candle_body_atr",
        "close_location",
        "volume_ratio",
        "macd_signal_spread_atr",
        "macd_signal_spread_prev_atr",
        "macd_spread_accelerating",
        "chop_score",
    )
    return {key: result.get(key) for key in keys}


def run_symbol(
    raw: pd.DataFrame,
    *,
    symbol: str,
    window_name: str,
) -> Tuple[Dict[Tuple[str, str], List[Dict[str, Any]]], Dict[str, int]]:
    bars = BASE.make_bars(raw, TIMEFRAME_MIN)
    trades: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    blocked_until: Dict[Tuple[str, str], int] = defaultdict(lambda: -1)
    reasons: Dict[str, int] = defaultdict(int)
    config = Config(confirmation_mode="candle_direction")

    for end_i in range(WINDOW_BARS, len(bars)):
        window = bars.iloc[end_i - WINDOW_BARS : end_i]
        if not window_is_contiguous(window):
            reasons["non_contiguous_window"] += 1
            continue
        signal_bar = bars.iloc[end_i - 1]
        next_raw_idx = int(signal_bar["raw_end_idx"]) + 1
        if next_raw_idx >= len(raw):
            reasons["no_next_open"] += 1
            continue
        result = strategy(
            window[["ts", "open", "high", "low", "close", "volume"]].copy(),
            config=config,
        )
        reason = str(result.get("why", "unknown")) if isinstance(result, dict) else "invalid_result"
        reasons[reason] += 1
        if not isinstance(result, dict) or str(result.get("action", "")).lower() != "enter":
            continue
        side = str(result.get("side", "")).lower()
        if side not in {"long", "short"}:
            continue
        try:
            signal_entry = float(result["entry"])
            native_stop = float(result["sl"])
        except (KeyError, TypeError, ValueError):
            continue
        next_ts = int(raw.iloc[next_raw_idx]["ts"])

        for candidate in ENTRY_CANDIDATES:
            if not entry_pass(candidate, result):
                continue
            for exit_policy in EXIT_POLICIES:
                key = (candidate, exit_policy)
                if next_ts <= blocked_until[key]:
                    continue
                trade = simulate_policy(
                    raw,
                    entry_idx=next_raw_idx,
                    side=side,
                    signal_entry=signal_entry,
                    native_stop=native_stop,
                    policy_name=exit_policy,
                )
                if trade is None:
                    continue
                trade.update(
                    {
                        "entry_candidate": candidate,
                        "symbol": symbol,
                        "window": window_name,
                        "side": side,
                        "signal_ts": int(signal_bar["ts"]),
                        "why": reason,
                        **signal_metadata(result),
                    }
                )
                trades[key].append(trade)
                blocked_until[key] = int(trade["exit_ts"]) + COOLDOWN_MIN * MINUTE_MS
    return trades, dict(sorted(reasons.items()))


def cost_r(trade: Dict[str, Any], cost_pct: float) -> float:
    return float(trade["entry"]) * (float(cost_pct) / 100.0) / max(float(trade["base_risk"]), 1e-12)


def net_r(trade: Dict[str, Any], cost_pct: float) -> float:
    return float(trade["gross_r"]) - cost_r(trade, cost_pct)


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
    outcomes: Dict[str, int] = defaultdict(int)
    triggered = 0
    for row, value in zip(ordered, values):
        by_symbol[str(row["symbol"])].append(value)
        by_side[str(row["side"])].append(value)
        outcomes[str(row["outcome"])] += 1
        triggered += int(bool(row.get("triggered_1R")))
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
        "positive_symbols": sum(1 for group in by_symbol.values() if sum(group) > 0),
        "by_symbol_net_R": {key: float(sum(group)) for key, group in sorted(by_symbol.items())},
        "by_side_net_R": {key: float(sum(group)) for key, group in sorted(by_side.items())},
        "outcome_counts": dict(sorted(outcomes.items())),
        "triggered_1R_pct": float(triggered / len(values) * 100.0) if values else 0.0,
        "ambiguity_count": sum(int(bool(row.get("ambiguity"))) for row in ordered),
    }


def pct_reduction(baseline: float, candidate: float) -> float:
    if baseline <= 0:
        return 0.0
    return float((baseline - candidate) / baseline * 100.0)


def gate_assessment(
    *,
    combined: Dict[str, Any],
    prior: Dict[str, Any],
    second: Dict[str, Any],
    baseline_combined: Dict[str, Any],
    retention_pct: float,
    cost020_combined: Dict[str, Any],
) -> Dict[str, Any]:
    checks = {
        "sample_retention": retention_pct >= RESCUE_GATE["sample_retention_pct_min"],
        "avg_R_improvement": float(combined["avg_net_R"]) - float(baseline_combined["avg_net_R"]) >= RESCUE_GATE["avg_R_improvement_min"],
        "profit_factor_improvement": float(combined["profit_factor_R"]) - float(baseline_combined["profit_factor_R"]) >= RESCUE_GATE["profit_factor_improvement_min"],
        "mdd_reduction": pct_reduction(float(baseline_combined["max_drawdown_R"]), float(combined["max_drawdown_R"])) >= RESCUE_GATE["mdd_reduction_pct_min"],
        "positive_symbols": int(combined["positive_symbols"]) >= RESCUE_GATE["positive_symbols_min"],
        "cost_0.20_survival": float(cost020_combined["avg_net_R"]) > RESCUE_GATE["cost_0.20_avg_R_min_exclusive"],
        "prior_window_floor": float(prior["avg_net_R"]) >= RESCUE_GATE["each_window_avg_R_floor"],
        "second_window_floor": float(second["avg_net_R"]) >= RESCUE_GATE["each_window_avg_R_floor"],
    }
    return {
        "checks": checks,
        "pass": all(checks.values()),
        "retention_pct": retention_pct,
        "avg_R_improvement": float(combined["avg_net_R"]) - float(baseline_combined["avg_net_R"]),
        "profit_factor_improvement": float(combined["profit_factor_R"]) - float(baseline_combined["profit_factor_R"]),
        "mdd_reduction_pct": pct_reduction(float(baseline_combined["max_drawdown_R"]), float(combined["max_drawdown_R"])),
    }


def compact_pair_decisions(payload: Dict[str, Any]) -> Dict[str, Any]:
    output: List[Dict[str, Any]] = []
    for index, pair in enumerate(payload.get("pairs", [])[:5], start=1):
        item: Dict[str, Any] = {"pair": index, "feature_distance": pair.get("feature_distance")}
        for label, key in (("loss", "loss_trade"), ("win", "matched_win_trade")):
            trade = pair.get(key, {})
            item[label] = {
                "trade_key": trade.get("trade_key"),
                "symbol": trade.get("symbol"),
                "side": trade.get("side"),
                "net_R": trade.get("net_R"),
                "decisions": {
                    candidate: entry_pass(candidate, trade)
                    for candidate in ENTRY_CANDIDATES
                },
            }
        output.append(item)
    return {
        "source_chart_pack": payload.get("chart_pack_index"),
        "pairs": output,
        "note": "Review only if a candidate removes both loss and matched win inconsistently; no chart-derived threshold changes are allowed.",
    }


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_chart_audit_html(payload: Dict[str, Any]) -> None:
    rows: List[str] = []
    for pair in payload.get("pairs", []):
        for label in ("loss", "win"):
            trade = pair[label]
            decisions = " · ".join(
                f"{name}={'PASS' if passed else 'BLOCK'}"
                for name, passed in trade["decisions"].items()
            )
            rows.append(
                "<tr>"
                f"<td>{pair['pair']}</td><td>{label}</td><td>{trade.get('symbol')}</td>"
                f"<td>{trade.get('side')}</td><td>{trade.get('net_R')}</td><td>{decisions}</td>"
                "</tr>"
            )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Raschke v2 chart audit</title>"
        "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #334155;padding:7px}</style>"
        "</head><body><h1>Raschke v2 matched chart decision audit</h1>"
        f"<p>Source chart pack: {payload.get('source_chart_pack')}</p>"
        "<table><thead><tr><th>Pair</th><th>Type</th><th>Symbol</th><th>Side</th><th>Net R</th><th>Candidate decisions</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )
    CHART_AUDIT_HTML.write_text(html, encoding="utf-8")


def main() -> None:
    raw_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
    integrity: Dict[str, Any] = {}
    all_trades: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    reason_counts: Dict[str, Any] = {}

    for window in WINDOWS:
        integrity[window] = {}
        reason_counts[window] = {}
        for symbol in SYMBOLS:
            frame, report = load_raw(raw_path(window, symbol))
            raw_cache[(window, symbol)] = frame
            integrity[window][symbol] = report
            result, reasons = run_symbol(frame, symbol=symbol, window_name=window)
            reason_counts[window][symbol] = reasons
            for (candidate, exit_policy), rows in result.items():
                all_trades[(candidate, exit_policy, window)].extend(rows)

    evaluations: Dict[str, Any] = {}
    ranking: List[Dict[str, Any]] = []
    baseline_rows = {
        window: all_trades[("baseline_candle_direction", "fixed_2R", window)]
        for window in WINDOWS
    }
    baseline_combined_rows = baseline_rows[WINDOWS[0]] + baseline_rows[WINDOWS[1]]

    for candidate, candidate_spec in ENTRY_CANDIDATES.items():
        evaluations[candidate] = {
            "mechanism": candidate_spec["mechanism"],
            "single_delta": candidate_spec["single_delta"],
            "exit_policies": {},
        }
        for exit_policy in EXIT_POLICIES:
            prior_rows = all_trades[(candidate, exit_policy, WINDOWS[0])]
            second_rows = all_trades[(candidate, exit_policy, WINDOWS[1])]
            combined_rows = prior_rows + second_rows
            costs: Dict[str, Any] = {}
            for cost in COST_LEVELS:
                key = f"cost_{cost:.2f}"
                costs[key] = {
                    WINDOWS[0]: metrics(prior_rows, cost),
                    WINDOWS[1]: metrics(second_rows, cost),
                    "combined_independent_180d": metrics(combined_rows, cost),
                }
            baseline_015 = metrics(baseline_combined_rows, 0.15)
            baseline_events = max(len(baseline_combined_rows), 1)
            retention_pct = float(len(combined_rows) / baseline_events * 100.0)
            assessment = gate_assessment(
                combined=costs["cost_0.15"]["combined_independent_180d"],
                prior=costs["cost_0.15"][WINDOWS[0]],
                second=costs["cost_0.15"][WINDOWS[1]],
                baseline_combined=baseline_015,
                retention_pct=retention_pct,
                cost020_combined=costs["cost_0.20"]["combined_independent_180d"],
            )
            evaluations[candidate]["exit_policies"][exit_policy] = {
                "costs": costs,
                "rescue_gate": assessment,
            }
            combined_015 = costs["cost_0.15"]["combined_independent_180d"]
            ranking.append(
                {
                    "entry_candidate": candidate,
                    "exit_policy": exit_policy,
                    "gate_pass": assessment["pass"],
                    "events": combined_015["events"],
                    "retention_pct": assessment["retention_pct"],
                    "avg_net_R": combined_015["avg_net_R"],
                    "net_sum_R": combined_015["net_sum_R"],
                    "positive_rate_pct": combined_015["positive_rate_pct"],
                    "profit_factor_R": combined_015["profit_factor_R"],
                    "max_drawdown_R": combined_015["max_drawdown_R"],
                    "positive_symbols": combined_015["positive_symbols"],
                    "cost_0.20_avg_net_R": costs["cost_0.20"]["combined_independent_180d"]["avg_net_R"],
                    "prior_avg_net_R": costs["cost_0.15"][WINDOWS[0]]["avg_net_R"],
                    "second_avg_net_R": costs["cost_0.15"][WINDOWS[1]]["avg_net_R"],
                    "avg_R_improvement": assessment["avg_R_improvement"],
                    "pf_improvement": assessment["profit_factor_improvement"],
                    "mdd_reduction_pct": assessment["mdd_reduction_pct"],
                }
            )

    ranking.sort(
        key=lambda row: (
            bool(row["gate_pass"]),
            float(row["avg_net_R"]),
            float(row["profit_factor_R"]),
            -float(row["max_drawdown_R"]),
        ),
        reverse=True,
    )
    third_holdout_queue = [
        row for row in ranking
        if row["gate_pass"] and row["entry_candidate"] != "baseline_candle_direction"
    ][:2]

    pair_payload = json.loads(PAIR_SOURCE.read_text(errors="ignore")) if PAIR_SOURCE.exists() else {"pairs": []}
    chart_audit = compact_pair_decisions(pair_payload)
    atomic_json(CHART_AUDIT_OUT, chart_audit)
    write_chart_audit_html(chart_audit)

    trades_payload = {
        "status": "PASS_Q4R3_RASCHKE_V2_TOURNAMENT_TRADES",
        "trades": {
            candidate: {
                policy: {
                    window: all_trades[(candidate, policy, window)]
                    for window in WINDOWS
                }
                for policy in EXIT_POLICIES
            }
            for candidate in ENTRY_CANDIDATES
        },
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
        },
    }
    atomic_json(TRADES_OUT, trades_payload)

    output = {
        "status": "PASS_Q4R3_ROUTE_A_RASCHKE_V2_ENTRY_EXIT_TOURNAMENT",
        "verdict": (
            "RASCHKE_V2_THIRD_HOLDOUT_QUEUE_READY"
            if third_holdout_queue
            else "RASCHKE_V2_NO_RESCUE_GATE_PASS_YET"
        ),
        "purpose": "rigorous independent rerun of one-delta entry guards and causal exit observers across two 90d windows",
        "entry_candidates": ENTRY_CANDIDATES,
        "exit_policies": EXIT_POLICIES,
        "rescue_gate": RESCUE_GATE,
        "strategy_config": asdict(Config(confirmation_mode="candle_direction")),
        "integrity": integrity,
        "reason_counts": reason_counts,
        "evaluations": evaluations,
        "ranking_cost_0.15": ranking,
        "third_holdout_queue": third_holdout_queue,
        "chart_audit": {
            "json": str(CHART_AUDIT_OUT),
            "html": str(CHART_AUDIT_HTML),
            "source": str(PAIR_SOURCE),
        },
        "trades_out": str(TRADES_OUT),
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
            "production_strategy_modified": False,
        },
        "out": str(OUT),
    }
    atomic_json(OUT, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
