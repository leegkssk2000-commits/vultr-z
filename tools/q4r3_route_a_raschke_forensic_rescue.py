from __future__ import annotations

import importlib
import importlib.util
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
OVERLAY_ROOT = Path(
    os.environ.get("Q4R3_ROUTE_A_OVERLAY_ROOT", "/tmp/q4r3-route-a-video-fidelity")
)
OUT = ROOT / "runtime" / "q4r3_route_a_raschke_forensic_rescue_latest.json"
TRADES_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_forensic_trades_latest.json"

sys.path.insert(0, str(OVERLAY_ROOT))
sys.path.insert(1, str(ROOT))


def _load_tournament_module() -> Any:
    path = OVERLAY_ROOT / "tools" / "q4r3_route_a_video_fidelity_tournament.py"
    spec = importlib.util.spec_from_file_location("q4r3_video_tournament_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"TOURNAMENT_IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_tournament_module()
STRATEGY_MODULE = importlib.import_module("backend.strategies.raschke_macd_ema200")
Config = STRATEGY_MODULE.RaschkeMacdEma200Config
strategy = STRATEGY_MODULE.strategy

SYMBOLS: List[str] = list(BASE.SYMBOLS)
SAMPLES = ("discovery_30d", "holdout_90d")
COST_LEVELS = (0.10, 0.15, 0.20)
TIMEFRAME_MIN = 60
TIMEOUT_MIN = 8 * TIMEFRAME_MIN
WINDOW_BARS = int(BASE.WINDOW_BARS)
COOLDOWN_MIN = int(BASE.COOLDOWN_MIN)
CONTRACT = {"loss_cap_r": 0.50, "target_r": 2.0}

# Fixed before this run. There is no arbitrary threshold grid search.
MODES: Dict[str, Dict[str, Any]] = {
    "source_core": {
        "confirmation_mode": "source_core",
        "mechanism": "EMA200 plus zero-zone MACD cross only",
    },
    "candle_direction": {
        "confirmation_mode": "candle_direction",
        "mechanism": "current explicit PDM proxy baseline",
    },
    "body_close": {
        "confirmation_mode": "body_close",
        "mechanism": "directional body and strong close location",
    },
    "trend_strength": {
        "confirmation_mode": "trend_strength",
        "mechanism": "directional candle plus ADX and EMA200 slope",
    },
    "pdm_proxy_v1": {
        "confirmation_mode": "pdm_proxy_v1",
        "mechanism": "body-close plus ADX/slope plus volume and MACD acceleration",
    },
}

HARD_GATE = {
    "events_min": 50,
    "avg_net_R_min": 0.15,
    "profit_factor_R_min": 1.20,
    "max_drawdown_R_max": 8.0,
    "positive_symbols_min": 3,
}
NEAR_GATE = {
    "events_min": 50,
    "avg_net_R_min": 0.10,
    "profit_factor_R_min": 1.25,
    "max_drawdown_R_max": 10.0,
    "positive_symbols_min": 3,
}


def _mode_config(mode: str) -> Any:
    if mode not in MODES:
        raise KeyError(mode)
    return Config(confirmation_mode=str(MODES[mode]["confirmation_mode"]))


def _signal_metadata(result: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "confirmation_mode",
        "ema_distance_atr",
        "ema_slope_atr",
        "adx",
        "candle_body_atr",
        "close_location",
        "volume_ratio",
        "macd_line",
        "macd_signal",
        "macd_histogram",
        "macd_signal_spread_atr",
        "macd_signal_spread_prev_atr",
        "macd_spread_accelerating",
        "chop_score",
    )
    return {key: result.get(key) for key in keys}


def run_mode_symbol(
    *,
    mode: str,
    sample: str,
    symbol: str,
    raw: pd.DataFrame,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    config = _mode_config(mode)
    bars = BASE.make_bars(raw, TIMEFRAME_MIN)
    trades: List[Dict[str, Any]] = []
    reasons: Dict[str, int] = defaultdict(int)
    blocked_until_ts = -1

    for end_i in range(WINDOW_BARS, len(bars)):
        window = bars.iloc[end_i - WINDOW_BARS : end_i]
        if not BASE.contiguous(window, TIMEFRAME_MIN):
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
        if not isinstance(result, dict):
            reasons["invalid_result"] += 1
            continue
        action = str(result.get("action", "hold")).lower()
        reason = str(result.get("why", "unknown"))
        reasons[reason] += 1
        if action != "enter":
            continue

        side = str(result.get("side", "")).lower()
        if side not in {"long", "short"}:
            reasons["invalid_side"] += 1
            continue
        try:
            signal_entry = float(result["entry"])
            native_stop = float(result["sl"])
        except (KeyError, TypeError, ValueError):
            reasons["invalid_native_contract"] += 1
            continue

        next_ts = int(raw.iloc[next_raw_idx]["ts"])
        if next_ts <= blocked_until_ts:
            reasons["cooldown_or_overlap"] += 1
            continue

        trade = BASE.simulate_trade(
            raw,
            entry_idx=next_raw_idx,
            side=side,
            signal_entry=signal_entry,
            native_stop=native_stop,
            contract=CONTRACT,
            timeout_min=TIMEOUT_MIN,
        )
        if trade is None:
            reasons["simulation_contract_invalid"] += 1
            continue

        trade.update(
            {
                "profile": "raschke_macd_ema200_60m",
                "mode": mode,
                "symbol": symbol,
                "sample": sample,
                "contract": "target2_loss050",
                "side": side,
                "signal_ts": int(signal_bar["ts"]),
                "why": reason,
                "source_profile": str(result.get("source_profile", "")),
                "fidelity": str(result.get("fidelity", "")),
                **_signal_metadata(result),
            }
        )
        trades.append(trade)
        blocked_until_ts = int(trade["exit_ts"]) + COOLDOWN_MIN * 60_000

    return trades, dict(sorted(reasons.items()))


def _cost_r(trade: Dict[str, Any], cost_pct: float) -> float:
    risk = max(float(trade["base_risk"]), 1e-12)
    return float(trade["entry"]) * (float(cost_pct) / 100.0) / risk


def net_r(trade: Dict[str, Any], cost_pct: float) -> float:
    return float(trade["gross_r"]) - _cost_r(trade, cost_pct)


def _max_drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return float(drawdown)


def metrics(trades: List[Dict[str, Any]], cost_pct: float) -> Dict[str, Any]:
    ordered = sorted(trades, key=lambda row: (int(row["entry_ts"]), str(row["symbol"])))
    values = [net_r(trade, cost_pct) for trade in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    by_symbol: Dict[str, List[float]] = defaultdict(list)
    by_side: Dict[str, List[float]] = defaultdict(list)
    outcomes: Dict[str, int] = defaultdict(int)
    for trade, value in zip(ordered, values):
        by_symbol[str(trade["symbol"])].append(value)
        by_side[str(trade["side"])].append(value)
        outcomes[str(trade["outcome"])] += 1
    gross_profit = float(sum(wins))
    gross_loss = abs(float(sum(losses)))
    return {
        "events": len(values),
        "avg_net_R": float(statistics.fmean(values)) if values else 0.0,
        "median_net_R": float(statistics.median(values)) if values else 0.0,
        "net_sum_R": float(sum(values)),
        "positive_rate_pct": float(len(wins) / len(values) * 100.0) if values else 0.0,
        "tp_rate_pct": float(outcomes["TP"] / len(values) * 100.0) if values else 0.0,
        "sl_rate_pct": float(outcomes["SL"] / len(values) * 100.0) if values else 0.0,
        "timeout_rate_pct": float(outcomes["TIMEOUT"] / len(values) * 100.0) if values else 0.0,
        "profit_factor_R": float(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "max_drawdown_R": _max_drawdown(values),
        "positive_symbols": sum(1 for group in by_symbol.values() if sum(group) > 0),
        "by_symbol_net_R": {key: float(sum(group)) for key, group in sorted(by_symbol.items())},
        "by_side_net_R": {key: float(sum(group)) for key, group in sorted(by_side.items())},
        "ambiguity_count": sum(int(bool(trade.get("ambiguity"))) for trade in ordered),
    }


def _bucket(value: Any, thresholds: Tuple[float, float], labels: Tuple[str, str, str]) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "missing"
    if not math.isfinite(number):
        return "missing"
    if number <= thresholds[0]:
        return labels[0]
    if number <= thresholds[1]:
        return labels[1]
    return labels[2]


def _feature_group(trade: Dict[str, Any], feature: str) -> str:
    if feature == "symbol":
        return str(trade.get("symbol", "missing"))
    if feature == "side":
        return str(trade.get("side", "missing"))
    if feature == "month":
        stamp = int(trade.get("entry_ts", 0))
        return pd.to_datetime(stamp, unit="ms", utc=True).strftime("%Y-%m")
    if feature == "ema_distance_atr":
        return _bucket(trade.get(feature), (0.75, 1.50), ("near<=0.75", "mid<=1.50", "far>1.50"))
    if feature == "chop_score":
        return _bucket(trade.get(feature), (0.15, 0.30), ("clean<=0.15", "mixed<=0.30", "choppy>0.30"))
    if feature == "adx":
        return _bucket(trade.get(feature), (17.0, 25.0), ("weak<=17", "medium<=25", "strong>25"))
    if feature == "candle_body_atr":
        return _bucket(trade.get(feature), (0.10, 0.25), ("small<=0.10", "medium<=0.25", "large>0.25"))
    if feature == "volume_ratio":
        return _bucket(trade.get(feature), (0.80, 1.20), ("low<=0.80", "normal<=1.20", "high>1.20"))
    if feature == "macd_signal_spread_atr":
        return _bucket(trade.get(feature), (0.005, 0.015), ("weak<=0.005", "medium<=0.015", "strong>0.015"))
    if feature == "ema_slope_alignment":
        try:
            slope = float(trade.get("ema_slope_atr"))
        except (TypeError, ValueError):
            return "missing"
        side = str(trade.get("side"))
        aligned = slope > 0 if side == "long" else slope < 0
        magnitude = abs(slope)
        if not aligned:
            return "misaligned"
        if magnitude < 0.015:
            return "aligned_weak"
        return "aligned_strong"
    return "unknown"


def decomposition(trades: List[Dict[str, Any]], cost_pct: float) -> Dict[str, Any]:
    features = (
        "symbol",
        "side",
        "month",
        "ema_distance_atr",
        "chop_score",
        "adx",
        "candle_body_atr",
        "volume_ratio",
        "macd_signal_spread_atr",
        "ema_slope_alignment",
    )
    output: Dict[str, Any] = {}
    for feature in features:
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for trade in trades:
            groups[_feature_group(trade, feature)].append(trade)
        output[feature] = {
            key: metrics(group, cost_pct)
            for key, group in sorted(groups.items())
        }
    return output


def passes_gate(report: Dict[str, Any], gate: Dict[str, Any]) -> bool:
    return bool(
        int(report.get("events", 0)) >= int(gate["events_min"])
        and float(report.get("avg_net_R", 0.0)) >= float(gate["avg_net_R_min"])
        and float(report.get("profit_factor_R", 0.0)) >= float(gate["profit_factor_R_min"])
        and float(report.get("max_drawdown_R", 999.0)) <= float(gate["max_drawdown_R_max"])
        and int(report.get("positive_symbols", 0)) >= int(gate["positive_symbols_min"])
    )


def discovery_score(report: Dict[str, Any]) -> float:
    events = int(report.get("events", 0))
    if events < 15:
        return -999.0 + events
    avg_r = float(report.get("avg_net_R", 0.0))
    pf = max(float(report.get("profit_factor_R", 0.0)), 1e-9)
    mdd = float(report.get("max_drawdown_R", 999.0))
    symbol_factor = min(int(report.get("positive_symbols", 0)), 5) / 5.0
    sample_factor = min(events, 50) / 50.0
    return float(
        avg_r * sample_factor
        + math.log(pf) * 0.05
        - mdd * 0.004
        + symbol_factor * 0.02
    )


def _worst_and_best_groups(decomp: Dict[str, Any]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for feature, groups in decomp.items():
        for label, report in groups.items():
            events = int(report.get("events", 0))
            if events < 5:
                continue
            candidates.append(
                {
                    "feature": feature,
                    "group": label,
                    "events": events,
                    "avg_net_R": float(report.get("avg_net_R", 0.0)),
                    "net_sum_R": float(report.get("net_sum_R", 0.0)),
                    "profit_factor_R": float(report.get("profit_factor_R", 0.0)),
                    "max_drawdown_R": float(report.get("max_drawdown_R", 0.0)),
                }
            )
    best = sorted(candidates, key=lambda row: (row["avg_net_R"], row["net_sum_R"]), reverse=True)[:10]
    worst = sorted(candidates, key=lambda row: (row["avg_net_R"], row["net_sum_R"]))[:10]
    return {"best10": best, "worst10": worst}


def main() -> None:
    raw_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
    integrity: Dict[str, Any] = {}
    for sample in SAMPLES:
        integrity[sample] = {}
        for symbol in SYMBOLS:
            path = BASE.sample_path(sample, symbol)
            frame, report = BASE.load_frame(path)
            raw_cache[(sample, symbol)] = frame
            integrity[sample][symbol] = report

    all_trades: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    reason_counts: Dict[str, Any] = {}
    for mode in MODES:
        reason_counts[mode] = {}
        for sample in SAMPLES:
            reason_counts[mode][sample] = {}
            for symbol in SYMBOLS:
                rows, reasons = run_mode_symbol(
                    mode=mode,
                    sample=sample,
                    symbol=symbol,
                    raw=raw_cache[(sample, symbol)],
                )
                all_trades[(mode, sample)].extend(rows)
                reason_counts[mode][sample][symbol] = reasons

    evaluations: Dict[str, Any] = {}
    discovery_ranking: List[Dict[str, Any]] = []
    for mode, spec in MODES.items():
        evaluations[mode] = {
            "mechanism": spec["mechanism"],
            "config": asdict(_mode_config(mode)),
            "costs": {},
        }
        for cost in COST_LEVELS:
            key = f"cost_{cost:.2f}"
            discovery_report = metrics(all_trades[(mode, "discovery_30d")], cost)
            holdout_report = metrics(all_trades[(mode, "holdout_90d")], cost)
            evaluations[mode]["costs"][key] = {
                "discovery_30d": discovery_report,
                "holdout_90d": holdout_report,
                "hard_gate": passes_gate(holdout_report, HARD_GATE),
                "near_gate": passes_gate(holdout_report, NEAR_GATE),
            }
            if abs(cost - 0.15) < 1e-9:
                discovery_ranking.append(
                    {
                        "mode": mode,
                        "mechanism": spec["mechanism"],
                        "discovery_score": discovery_score(discovery_report),
                        "discovery": discovery_report,
                        "holdout_diagnostic": holdout_report,
                        "holdout_hard_gate": passes_gate(holdout_report, HARD_GATE),
                        "holdout_near_gate": passes_gate(holdout_report, NEAR_GATE),
                    }
                )

    discovery_ranking.sort(
        key=lambda row: (
            float(row["discovery_score"]),
            float(row["discovery"]["avg_net_R"]),
            float(row["discovery"]["profit_factor_R"]),
        ),
        reverse=True,
    )
    discovery_selected = str(discovery_ranking[0]["mode"])
    selected_holdout = metrics(all_trades[(discovery_selected, "holdout_90d")], 0.15)

    baseline_mode = "candle_direction"
    baseline_holdout = all_trades[(baseline_mode, "holdout_90d")]
    baseline_decomp = decomposition(baseline_holdout, 0.15)
    group_extremes = _worst_and_best_groups(baseline_decomp)

    queue: List[str] = [discovery_selected]
    if baseline_mode not in queue:
        queue.append(baseline_mode)
    queue = queue[:2]

    if passes_gate(selected_holdout, HARD_GATE):
        verdict = "RASCHKE_RESCUE_HARD_GATE_ON_FIRST_HOLDOUT"
    elif passes_gate(selected_holdout, NEAR_GATE):
        verdict = "RASCHKE_RESCUE_NEAR_GATE_FREEZE_FOR_SECOND_HOLDOUT"
    else:
        baseline_report = metrics(baseline_holdout, 0.15)
        if passes_gate(baseline_report, NEAR_GATE):
            verdict = "BASELINE_NEAR_GATE_FREEZE_TWO_CANDIDATES_FOR_SECOND_HOLDOUT"
        else:
            verdict = "FORENSIC_ONLY_NO_PROMOTION"

    trades_payload = {
        "status": "PASS_Q4R3_RASCHKE_FORENSIC_TRADES",
        "cost_reference_pct": 0.15,
        "contract": CONTRACT,
        "trades": {
            mode: {
                sample: all_trades[(mode, sample)]
                for sample in SAMPLES
            }
            for mode in MODES
        },
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
        },
    }
    TRADES_OUT.parent.mkdir(parents=True, exist_ok=True)
    trades_tmp = TRADES_OUT.with_suffix(".json.tmp")
    trades_tmp.write_text(json.dumps(trades_payload, ensure_ascii=False), encoding="utf-8")
    trades_tmp.replace(TRADES_OUT)

    output = {
        "status": "PASS_Q4R3_ROUTE_A_RASCHKE_FORENSIC_RESCUE",
        "verdict": verdict,
        "purpose": "mechanistic PDM-proxy rescue with no arbitrary threshold sweep",
        "source_core": {
            "ema_length": 200,
            "macd": [12, 26, 9],
            "long": "above EMA200 and bullish MACD cross below zero",
            "short": "below EMA200 and bearish MACD cross above zero",
            "unavailable_component": "proprietary PDM marker",
        },
        "contract": {
            "target_R": 2.0,
            "loss_cap_R": -0.50,
            "timeout_min": TIMEOUT_MIN,
            "cooldown_min": COOLDOWN_MIN,
        },
        "integrity": integrity,
        "modes": MODES,
        "reason_counts": reason_counts,
        "evaluations": evaluations,
        "discovery_ranking_cost_0.15": discovery_ranking,
        "discovery_selected_mode": discovery_selected,
        "selected_holdout_cost_0.15": selected_holdout,
        "baseline_holdout_cost_0.15": metrics(baseline_holdout, 0.15),
        "baseline_decomposition_cost_0.15": baseline_decomp,
        "baseline_group_extremes": group_extremes,
        "second_holdout_queue_frozen": queue,
        "selection_warning": "current 90d remains validation/diagnostic; final promotion requires a new earlier non-overlapping holdout",
        "hard_gate": HARD_GATE,
        "near_gate": NEAR_GATE,
        "trades_out": str(TRADES_OUT),
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
        },
        "out": str(OUT),
    }
    temporary = OUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(OUT)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
