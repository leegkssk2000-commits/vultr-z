from __future__ import annotations

import importlib
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
DISCOVERY_DIR = ROOT / "data" / "oos_a1" / "bingx_public"
HOLDOUT_DIR = ROOT / "data" / "oos_a2" / "frozen_pre30d"
OUT = ROOT / "runtime" / "q4r3_route_a_video_fidelity_tournament_latest.json"

OVERLAY_ROOT = Path(os.environ.get("Q4R3_ROUTE_A_OVERLAY_ROOT", str(ROOT)))
sys.path.insert(0, str(OVERLAY_ROOT))
sys.path.insert(1, str(ROOT))

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"]
COST_LEVELS = (0.10, 0.15, 0.20)
COOLDOWN_MIN = 60
WINDOW_BARS = 320

PROFILES: List[Dict[str, Any]] = [
    {
        "name": "rayner_hist_momentum_60m",
        "module": "backend.strategies.rayner_hist_momentum",
        "timeframe_min": 60,
        "timeout_bars": 8,
        "source_video": 11,
        "fidelity": "exact settings: EMA60 + MACD 1/60/9",
    },
    {
        "name": "raschke_macd_ema200_60m",
        "module": "backend.strategies.raschke_macd_ema200",
        "timeframe_min": 60,
        "timeout_bars": 8,
        "source_video": 2,
        "fidelity": "exact EMA/MACD core; explicit PDM proxy",
    },
    {
        "name": "fractal_triple_ema_pullback_15m",
        "module": "backend.strategies.fractal_triple_ema_pullback",
        "timeframe_min": 15,
        "timeout_bars": 24,
        "source_video": 3,
        "fidelity": "causal Williams fractal + EMA20/50/100",
    },
    {
        "name": "alligator_trend_pullback_15m",
        "module": "backend.strategies.alligator_trend_pullback",
        "timeframe_min": 15,
        "timeout_bars": 24,
        "source_video": 1,
        "fidelity": "causal SMMA5/8/13 with historical shifts",
    },
]

CONTRACTS: Dict[str, Dict[str, float]] = {
    "native_2R": {"loss_cap_r": 1.0, "target_r": 2.0},
    "target2_loss075": {"loss_cap_r": 0.75, "target_r": 2.0},
    "target2_loss050": {"loss_cap_r": 0.50, "target_r": 2.0},
}


def timestamp_ms(value: Any) -> int:
    stamp = int(float(value))
    return stamp * 1000 if abs(stamp) < 100_000_000_000 else stamp


def read_payload(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(errors="ignore"))


def rows_from_payload(payload: Dict[str, Any]) -> List[List[Any]]:
    rows = payload.get("rows", [])
    return rows if isinstance(rows, list) else []


def load_frame(path: Path) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    payload = read_payload(path)
    records: List[Dict[str, Any]] = []
    for row in rows_from_payload(payload):
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
        raise RuntimeError(f"EMPTY_DATA:{path}")
    frame = frame.sort_values("ts_dt").drop_duplicates("ts_dt", keep="last").reset_index(drop=True)
    frame["raw_idx"] = range(len(frame))
    diffs = frame["ts_dt"].diff().dt.total_seconds().dropna()
    gap_count = int((diffs != 60).sum())
    integrity = {
        "path": str(path),
        "rows": int(len(frame)),
        "start": str(frame["ts_dt"].iloc[0]),
        "end": str(frame["ts_dt"].iloc[-1]),
        "duplicate_ts": int(frame["ts_dt"].duplicated().sum()),
        "gap_count": gap_count,
        "valid": bool(gap_count == 0 and not frame["ts_dt"].duplicated().any()),
    }
    if not integrity["valid"]:
        raise RuntimeError(f"DATA_INTEGRITY_FAIL:{path}:{integrity}")
    return frame, integrity


def sample_path(sample: str, symbol: str) -> Path:
    if sample == "discovery_30d":
        return DISCOVERY_DIR / f"{symbol}_1m_30d_isolated.json"
    if sample == "holdout_90d":
        return HOLDOUT_DIR / f"{symbol}_1m_90d_pre30d.json"
    raise KeyError(sample)


def make_bars(frame: pd.DataFrame, timeframe_min: int) -> pd.DataFrame:
    rule = f"{int(timeframe_min)}min"
    data = frame.copy()
    data["bucket"] = data["ts_dt"].dt.floor(rule)
    bars = data.groupby("bucket").agg(
        ts=("ts", "last"),
        ts_dt=("ts_dt", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        raw_start_idx=("raw_idx", "min"),
        raw_end_idx=("raw_idx", "max"),
        raw_count=("raw_idx", "count"),
        min_dt=("ts_dt", "min"),
        max_dt=("ts_dt", "max"),
    ).reset_index()
    bars["span_min"] = (bars["max_dt"] - bars["min_dt"]).dt.total_seconds() / 60.0
    bars["complete"] = (
        (bars["raw_count"] == int(timeframe_min))
        & bars["span_min"].between(float(timeframe_min - 1) - 0.1, float(timeframe_min - 1) + 0.1)
    )
    return bars.reset_index(drop=True)


def contiguous(window: pd.DataFrame, timeframe_min: int) -> bool:
    if window.empty or not bool(window["complete"].all()):
        return False
    diffs = window["bucket"].diff().dt.total_seconds().dropna()
    return bool((diffs == int(timeframe_min) * 60).all())


def contract_prices(
    signal_entry: float,
    native_stop: float,
    actual_entry: float,
    side: str,
    contract: Dict[str, float],
) -> Optional[Dict[str, float]]:
    base_risk = abs(float(signal_entry) - float(native_stop))
    if not math.isfinite(base_risk) or base_risk <= 0:
        return None
    loss_cap = float(contract["loss_cap_r"])
    target_r = float(contract["target_r"])
    if side == "long":
        stop = actual_entry - base_risk * loss_cap
        target = actual_entry + base_risk * target_r
    else:
        stop = actual_entry + base_risk * loss_cap
        target = actual_entry - base_risk * target_r
    return {
        "base_risk": base_risk,
        "stop": stop,
        "target": target,
    }


def simulate_trade(
    raw: pd.DataFrame,
    *,
    entry_idx: int,
    side: str,
    signal_entry: float,
    native_stop: float,
    contract: Dict[str, float],
    timeout_min: int,
) -> Optional[Dict[str, Any]]:
    if entry_idx < 0 or entry_idx >= len(raw):
        return None
    actual_entry = float(raw.iloc[entry_idx]["open"])
    prices = contract_prices(
        signal_entry,
        native_stop,
        actual_entry,
        side,
        contract,
    )
    if prices is None:
        return None
    base_risk = prices["base_risk"]
    stop = prices["stop"]
    target = prices["target"]
    if (side == "long" and not stop < actual_entry < target) or (
        side == "short" and not target < actual_entry < stop
    ):
        return None

    last_idx = min(len(raw) - 1, entry_idx + max(int(timeout_min), 1) - 1)
    outcome = "TIMEOUT"
    exit_idx = last_idx
    exit_price = float(raw.iloc[last_idx]["close"])
    ambiguity = False

    for idx in range(entry_idx, last_idx + 1):
        row = raw.iloc[idx]
        high = float(row["high"])
        low = float(row["low"])
        if side == "long":
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            stop_hit = high >= stop
            target_hit = low <= target
        if stop_hit and target_hit:
            ambiguity = True
            outcome = "SL"
            exit_idx = idx
            exit_price = stop
            break
        if stop_hit:
            outcome = "SL"
            exit_idx = idx
            exit_price = stop
            break
        if target_hit:
            outcome = "TP"
            exit_idx = idx
            exit_price = target
            break

    direction = 1.0 if side == "long" else -1.0
    gross_r = direction * (exit_price - actual_entry) / base_risk
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
    }


def invoke(strategy_fn: Any, window: pd.DataFrame) -> Dict[str, Any]:
    result = strategy_fn(window[["ts", "open", "high", "low", "close", "volume"]].copy())
    return result if isinstance(result, dict) else {"action": "hold", "why": "INVALID_RESULT"}


def run_profile_symbol(
    profile: Dict[str, Any],
    raw: pd.DataFrame,
    symbol: str,
    sample: str,
) -> Dict[str, List[Dict[str, Any]]]:
    module = importlib.import_module(str(profile["module"]))
    strategy_fn = getattr(module, "strategy")
    timeframe_min = int(profile["timeframe_min"])
    timeout_min = int(profile["timeout_bars"]) * timeframe_min
    bars = make_bars(raw, timeframe_min)
    trades: Dict[str, List[Dict[str, Any]]] = {name: [] for name in CONTRACTS}
    blocked_until_ts = {name: -1 for name in CONTRACTS}

    for end_i in range(WINDOW_BARS, len(bars)):
        window = bars.iloc[end_i - WINDOW_BARS : end_i]
        if not contiguous(window, timeframe_min):
            continue
        signal_bar = bars.iloc[end_i - 1]
        next_raw_idx = int(signal_bar["raw_end_idx"]) + 1
        if next_raw_idx >= len(raw):
            continue
        result = invoke(strategy_fn, window)
        if str(result.get("action", "")).lower() != "enter":
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

        for contract_name, contract in CONTRACTS.items():
            if next_ts <= blocked_until_ts[contract_name]:
                continue
            trade = simulate_trade(
                raw,
                entry_idx=next_raw_idx,
                side=side,
                signal_entry=signal_entry,
                native_stop=native_stop,
                contract=contract,
                timeout_min=timeout_min,
            )
            if trade is None:
                continue
            trade.update(
                {
                    "profile": profile["name"],
                    "strategy": str(result.get("strategy", profile["module"])),
                    "symbol": symbol,
                    "sample": sample,
                    "contract": contract_name,
                    "side": side,
                    "signal_ts": int(signal_bar["ts"]),
                    "why": str(result.get("why", "")),
                    "source_profile": str(result.get("source_profile", "")),
                    "fidelity": str(result.get("fidelity", profile.get("fidelity", ""))),
                }
            )
            trades[contract_name].append(trade)
            blocked_until_ts[contract_name] = int(trade["exit_ts"]) + COOLDOWN_MIN * 60_000

    return trades


def max_drawdown(values: Iterable[float]) -> float:
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
    net_values: List[float] = []
    by_symbol: Dict[str, List[float]] = defaultdict(list)
    outcomes: Dict[str, int] = defaultdict(int)
    ambiguity_count = 0
    for trade in ordered:
        risk = max(float(trade["base_risk"]), 1e-12)
        entry = float(trade["entry"])
        cost_r = entry * (float(cost_pct) / 100.0) / risk
        net_r = float(trade["gross_r"]) - cost_r
        net_values.append(net_r)
        by_symbol[str(trade["symbol"])].append(net_r)
        outcomes[str(trade["outcome"])] += 1
        ambiguity_count += int(bool(trade.get("ambiguity")))

    wins = [value for value in net_values if value > 0]
    losses = [value for value in net_values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "events": len(net_values),
        "avg_net_R": float(statistics.fmean(net_values)) if net_values else 0.0,
        "median_net_R": float(statistics.median(net_values)) if net_values else 0.0,
        "net_sum_R": float(sum(net_values)),
        "positive_rate_pct": float(len(wins) / len(net_values) * 100.0) if net_values else 0.0,
        "tp_rate_pct": float(outcomes["TP"] / len(net_values) * 100.0) if net_values else 0.0,
        "sl_rate_pct": float(outcomes["SL"] / len(net_values) * 100.0) if net_values else 0.0,
        "timeout_rate_pct": float(outcomes["TIMEOUT"] / len(net_values) * 100.0) if net_values else 0.0,
        "profit_factor_R": float(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "max_drawdown_R": max_drawdown(net_values),
        "positive_symbols": sum(1 for values in by_symbol.values() if sum(values) > 0),
        "by_symbol_net_R": {key: float(sum(values)) for key, values in sorted(by_symbol.items())},
        "ambiguity_count": int(ambiguity_count),
    }


def classify(discovery: Dict[str, Any], holdout: Dict[str, Any]) -> str:
    if int(holdout.get("events", 0)) < 50:
        return "INSUFFICIENT_HOLDOUT_SAMPLE"
    if (
        float(holdout.get("avg_net_R", 0.0)) >= 0.15
        and float(holdout.get("profit_factor_R", 0.0)) >= 1.20
        and float(holdout.get("max_drawdown_R", 999.0)) <= 8.0
        and int(holdout.get("positive_symbols", 0)) >= 3
    ):
        return "CORE_CANDIDATE"
    if (
        float(holdout.get("avg_net_R", 0.0)) > 0
        and float(holdout.get("profit_factor_R", 0.0)) > 1.0
        and int(holdout.get("positive_symbols", 0)) >= 2
    ):
        return "RESERVE_OR_REBUILD"
    if float(discovery.get("net_sum_R", 0.0)) > 0 and float(holdout.get("net_sum_R", 0.0)) <= 0:
        return "DISCOVERY_ONLY_REGIME_FAILURE"
    return "REJECT_CURRENT_IMPLEMENTATION"


def main() -> None:
    samples = ["discovery_30d", "holdout_90d"]
    integrity: Dict[str, Any] = {}
    raw_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
    for sample in samples:
        integrity[sample] = {}
        for symbol in SYMBOLS:
            path = sample_path(sample, symbol)
            frame, report = load_frame(path)
            raw_cache[(sample, symbol)] = frame
            integrity[sample][symbol] = report

    all_trades: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    profile_reports: Dict[str, Any] = {}
    for profile in PROFILES:
        name = str(profile["name"])
        profile_reports[name] = {
            "module": profile["module"],
            "timeframe_min": profile["timeframe_min"],
            "source_video": profile["source_video"],
            "fidelity": profile["fidelity"],
            "raw_signal_trades": {},
        }
        for sample in samples:
            counts: Dict[str, Dict[str, int]] = {}
            for symbol in SYMBOLS:
                result = run_profile_symbol(
                    profile,
                    raw_cache[(sample, symbol)],
                    symbol,
                    sample,
                )
                counts[symbol] = {contract: len(rows) for contract, rows in result.items()}
                for contract, rows in result.items():
                    all_trades[(name, sample, contract)].extend(rows)
            profile_reports[name]["raw_signal_trades"][sample] = counts

    evaluations: Dict[str, Any] = {}
    ranking_rows: List[Dict[str, Any]] = []
    for profile in PROFILES:
        name = str(profile["name"])
        evaluations[name] = {}
        for contract_name in CONTRACTS:
            evaluations[name][contract_name] = {}
            for cost in COST_LEVELS:
                key = f"cost_{cost:.2f}"
                discovery_metrics = metrics(
                    all_trades[(name, "discovery_30d", contract_name)],
                    cost,
                )
                holdout_metrics = metrics(
                    all_trades[(name, "holdout_90d", contract_name)],
                    cost,
                )
                verdict = classify(discovery_metrics, holdout_metrics)
                evaluations[name][contract_name][key] = {
                    "discovery_30d": discovery_metrics,
                    "holdout_90d": holdout_metrics,
                    "verdict": verdict,
                }
                if abs(cost - 0.15) < 1e-9:
                    ranking_rows.append(
                        {
                            "profile": name,
                            "contract": contract_name,
                            "cost_pct": cost,
                            "verdict": verdict,
                            "holdout_events": holdout_metrics["events"],
                            "holdout_avg_net_R": holdout_metrics["avg_net_R"],
                            "holdout_net_sum_R": holdout_metrics["net_sum_R"],
                            "holdout_profit_factor_R": holdout_metrics["profit_factor_R"],
                            "holdout_max_drawdown_R": holdout_metrics["max_drawdown_R"],
                            "holdout_positive_symbols": holdout_metrics["positive_symbols"],
                        }
                    )

    rank_order = {
        "CORE_CANDIDATE": 4,
        "RESERVE_OR_REBUILD": 3,
        "INSUFFICIENT_HOLDOUT_SAMPLE": 2,
        "DISCOVERY_ONLY_REGIME_FAILURE": 1,
        "REJECT_CURRENT_IMPLEMENTATION": 0,
    }
    ranking_rows.sort(
        key=lambda row: (
            rank_order.get(str(row["verdict"]), -1),
            float(row["holdout_avg_net_R"]),
            float(row["holdout_profit_factor_R"]),
            -float(row["holdout_max_drawdown_R"]),
        ),
        reverse=True,
    )

    output = {
        "status": "PASS_Q4R3_ROUTE_A_VIDEO_FIDELITY_TOURNAMENT",
        "purpose": "source-faithful Route A core discovery; no production writes",
        "root_cause_under_test": "failed EMA ribbon beam was a hybrid, not a faithful video implementation",
        "profiles": profile_reports,
        "contracts": CONTRACTS,
        "cost_levels_pct_round_trip": COST_LEVELS,
        "integrity": integrity,
        "evaluations": evaluations,
        "ranking_cost_0.15": ranking_rows,
        "hard_gate": {
            "events_min": 50,
            "avg_net_R_min": 0.15,
            "profit_factor_R_min": 1.20,
            "max_drawdown_R_max": 8.0,
            "positive_symbols_min": 3,
        },
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
        },
        "out": str(OUT),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(OUT)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
