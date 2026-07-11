from __future__ import annotations

import importlib.util
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
OVERLAY_ROOT = Path(os.environ.get("Q4R3_ROUTE_A_OVERLAY_ROOT", "/tmp/q4r3-route-a-router"))
V2_PATH = OVERLAY_ROOT / "tools" / "q4r3_route_a_raschke_v2_entry_exit_tournament.py"
PAIR_SOURCE = ROOT / "runtime" / "loss_vs_win_matched_pairs.json"
OUT = ROOT / "runtime" / "q4r3_route_a_raschke_regime_router_latest.json"
TRADES_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_regime_router_trades_latest.json"
AUDIT_JSON = ROOT / "runtime" / "raschke_regime_router_chart_audit_latest.json"
AUDIT_HTML = ROOT / "runtime" / "raschke_regime_router_chart_audit_latest.html"

MINUTE_MS = 60_000
COST_LEVELS = (0.10, 0.15, 0.20)
BASE_ENTRY = "v2_proximity_guard"
BASE_EXIT = "fixed_2R"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V2 = _load_module("q4r3_regime_router_v2", V2_PATH)

ROUTERS: Dict[str, Dict[str, Any]] = {
    "router_off": {
        "mechanism": "proximity guard only; no regime routing",
        "score_min": 0,
        "features": (),
    },
    "r1_slope_alignment": {
        "mechanism": "require EMA200 slope direction to match trade side",
        "score_min": 1,
        "features": ("slope_aligned",),
    },
    "r2_quality_2of3": {
        "mechanism": "require any two of aligned EMA slope, ADX>17, MACD spread>0.005 ATR",
        "score_min": 2,
        "features": ("slope_aligned", "adx_ok", "macd_ok"),
    },
    "r3_regime_3of5": {
        "mechanism": "require three of slope alignment, ADX, non-chop, MACD strength, completed 4h trend alignment",
        "score_min": 3,
        "features": ("slope_aligned", "adx_ok", "chop_ok", "macd_ok", "h4_aligned"),
    },
    "r4_regime_4of6": {
        "mechanism": "require four of the five regime features plus sane 1h ATR percentile 20-85",
        "score_min": 4,
        "features": (
            "slope_aligned",
            "adx_ok",
            "chop_ok",
            "macd_ok",
            "h4_aligned",
            "volatility_ok",
        ),
    },
}

ROUTER_GATE = {
    "events_min": 70,
    "retention_vs_proximity_pct_min": 70.0,
    "combined_avg_net_R_min": 0.08,
    "combined_profit_factor_R_min": 1.25,
    "combined_max_drawdown_R_max": 8.0,
    "positive_symbols_min": 3,
    "cost_0.20_avg_net_R_min_exclusive": 0.0,
    "prior_window_avg_net_R_min": 0.0,
    "second_window_avg_net_R_min": -0.05,
    "nonnegative_block_ratio_min": 2.0 / 3.0,
}


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


def true_range(frame: pd.DataFrame) -> pd.Series:
    previous = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr_percentile(values: Sequence[float]) -> Optional[float]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if len(clean) < 60:
        return None
    current = clean[-1]
    below_or_equal = sum(value <= current for value in clean)
    return float((below_or_equal - 1) / max(len(clean) - 1, 1) * 100.0)


def build_regime_frames(raw: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    frame = raw.copy()
    frame["bucket_1h"] = frame["ts_dt"].dt.floor("60min")
    one_hour = frame.groupby("bucket_1h", sort=True).agg(
        ts=("ts", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        count=("ts", "count"),
    ).reset_index(drop=False)
    one_hour = one_hour[one_hour["count"] == 60].reset_index(drop=True)
    one_hour["atr14"] = true_range(one_hour).rolling(14, min_periods=14).mean()
    atr_pct: List[Optional[float]] = []
    atr_values = one_hour["atr14"].tolist()
    for index in range(len(one_hour)):
        start = max(0, index - 239)
        window = [value for value in atr_values[start : index + 1] if safe_float(value) is not None]
        atr_pct.append(atr_percentile(window))
    one_hour["atr_percentile_240h"] = atr_pct

    frame["bucket_4h"] = frame["ts_dt"].dt.floor("4h")
    four_hour = frame.groupby("bucket_4h", sort=True).agg(
        ts=("ts", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        count=("ts", "count"),
    ).reset_index(drop=False)
    four_hour = four_hour[four_hour["count"] == 240].reset_index(drop=True)
    four_hour["ema50"] = four_hour["close"].ewm(span=50, adjust=False, min_periods=50).mean()
    four_hour["ema50_slope_2bar"] = four_hour["ema50"] - four_hour["ema50"].shift(2)
    return {"1h": one_hour, "4h": four_hour}


def latest_row(frame: pd.DataFrame, signal_ts: int) -> Optional[pd.Series]:
    eligible = frame[frame["ts"] <= int(signal_ts)]
    if eligible.empty:
        return None
    return eligible.iloc[-1]


def regime_features(
    result: Dict[str, Any],
    *,
    side: str,
    signal_ts: int,
    frames: Dict[str, pd.DataFrame],
) -> Dict[str, Any]:
    slope = safe_float(result.get("ema_slope_atr"))
    adx = safe_float(result.get("adx"))
    chop = safe_float(result.get("chop_score"))
    spread = safe_float(result.get("macd_signal_spread_atr"))
    slope_aligned = bool(
        slope is not None
        and ((side == "long" and slope > 0.0) or (side == "short" and slope < 0.0))
    )
    adx_ok = bool(adx is not None and adx > 17.0)
    chop_ok = bool(chop is not None and chop <= 0.30)
    macd_ok = bool(spread is not None and spread > 0.005)

    one_hour = latest_row(frames["1h"], signal_ts)
    atr_pct = safe_float(one_hour.get("atr_percentile_240h")) if one_hour is not None else None
    volatility_ok = bool(atr_pct is not None and 20.0 <= atr_pct <= 85.0)

    four_hour = latest_row(frames["4h"], signal_ts)
    h4_close = safe_float(four_hour.get("close")) if four_hour is not None else None
    h4_ema = safe_float(four_hour.get("ema50")) if four_hour is not None else None
    h4_slope = safe_float(four_hour.get("ema50_slope_2bar")) if four_hour is not None else None
    h4_aligned = bool(
        None not in {h4_close, h4_ema, h4_slope}
        and (
            (side == "long" and float(h4_close) > float(h4_ema) and float(h4_slope) > 0.0)
            or (side == "short" and float(h4_close) < float(h4_ema) and float(h4_slope) < 0.0)
        )
    )
    return {
        "slope_aligned": slope_aligned,
        "adx_ok": adx_ok,
        "chop_ok": chop_ok,
        "macd_ok": macd_ok,
        "h4_aligned": h4_aligned,
        "volatility_ok": volatility_ok,
        "atr_percentile_240h": atr_pct,
        "h4_close": h4_close,
        "h4_ema50": h4_ema,
        "h4_ema50_slope_2bar": h4_slope,
    }


def router_pass(router: str, features: Dict[str, Any]) -> Tuple[bool, int]:
    spec = ROUTERS[router]
    score = sum(int(bool(features.get(feature))) for feature in spec["features"])
    return bool(score >= int(spec["score_min"])), int(score)


def run_symbol(
    raw: pd.DataFrame,
    *,
    symbol: str,
    window_name: str,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, int]]:
    bars = V2.BASE.make_bars(raw, V2.TIMEFRAME_MIN)
    frames = build_regime_frames(raw)
    trades: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    blocked_until: Dict[str, int] = defaultdict(lambda: -1)
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
        result = V2.strategy(
            window[["ts", "open", "high", "low", "close", "volume"]].copy(),
            config=config,
        )
        reason = str(result.get("why", "unknown")) if isinstance(result, dict) else "invalid_result"
        reasons[reason] += 1
        if not isinstance(result, dict) or str(result.get("action", "")).lower() != "enter":
            continue
        if not V2.entry_pass(BASE_ENTRY, result):
            reasons["proximity_guard_block"] += 1
            continue
        side = str(result.get("side", "")).lower()
        if side not in {"long", "short"}:
            reasons["invalid_side"] += 1
            continue
        try:
            signal_entry = float(result["entry"])
            native_stop = float(result["sl"])
        except (KeyError, TypeError, ValueError):
            reasons["invalid_contract"] += 1
            continue

        next_ts = int(raw.iloc[next_raw_idx]["ts"])
        signal_ts = int(signal_bar["ts"])
        features = regime_features(result, side=side, signal_ts=signal_ts, frames=frames)

        for router in ROUTERS:
            passed, score = router_pass(router, features)
            if not passed:
                reasons[f"{router}_block"] += 1
                continue
            if next_ts <= blocked_until[router]:
                reasons[f"{router}_cooldown"] += 1
                continue
            trade = V2.simulate_policy(
                raw,
                entry_idx=next_raw_idx,
                side=side,
                signal_entry=signal_entry,
                native_stop=native_stop,
                policy_name=BASE_EXIT,
            )
            if trade is None:
                reasons[f"{router}_simulation_reject"] += 1
                continue
            trade.update(
                {
                    "router": router,
                    "entry_candidate": BASE_ENTRY,
                    "exit_policy": BASE_EXIT,
                    "symbol": symbol,
                    "window": window_name,
                    "side": side,
                    "signal_ts": signal_ts,
                    "why": reason,
                    "router_score": score,
                    **V2.signal_metadata(result),
                    **features,
                }
            )
            trades[router].append(trade)
            blocked_until[router] = int(trade["exit_ts"]) + V2.COOLDOWN_MIN * MINUTE_MS
    return trades, dict(sorted(reasons.items()))


def monthly_blocks(rows: Sequence[Dict[str, Any]], cost_pct: float) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    purged = 0
    for row in rows:
        entry_month = pd.to_datetime(int(row["entry_ts"]), unit="ms", utc=True).strftime("%Y-%m")
        exit_month = pd.to_datetime(int(row["exit_ts"]), unit="ms", utc=True).strftime("%Y-%m")
        if entry_month != exit_month:
            purged += 1
            continue
        groups[entry_month].append(row)
    reports = {month: V2.metrics(group, cost_pct) for month, group in sorted(groups.items())}
    nonnegative = sum(float(report["avg_net_R"]) >= 0.0 for report in reports.values())
    return {
        "blocks": reports,
        "block_count": len(reports),
        "purged_cross_month_trades": purged,
        "nonnegative_blocks": nonnegative,
        "nonnegative_block_ratio": float(nonnegative / len(reports)) if reports else 0.0,
    }


def gate_assessment(
    *,
    combined: Dict[str, Any],
    prior: Dict[str, Any],
    second: Dict[str, Any],
    cost020: Dict[str, Any],
    block_report: Dict[str, Any],
    retention_pct: float,
) -> Dict[str, Any]:
    checks = {
        "events": int(combined["events"]) >= ROUTER_GATE["events_min"],
        "retention": retention_pct >= ROUTER_GATE["retention_vs_proximity_pct_min"],
        "combined_avg": float(combined["avg_net_R"]) >= ROUTER_GATE["combined_avg_net_R_min"],
        "combined_pf": float(combined["profit_factor_R"]) >= ROUTER_GATE["combined_profit_factor_R_min"],
        "combined_mdd": float(combined["max_drawdown_R"]) <= ROUTER_GATE["combined_max_drawdown_R_max"],
        "positive_symbols": int(combined["positive_symbols"]) >= ROUTER_GATE["positive_symbols_min"],
        "cost020": float(cost020["avg_net_R"]) > ROUTER_GATE["cost_0.20_avg_net_R_min_exclusive"],
        "prior_window": float(prior["avg_net_R"]) >= ROUTER_GATE["prior_window_avg_net_R_min"],
        "second_window": float(second["avg_net_R"]) >= ROUTER_GATE["second_window_avg_net_R_min"],
        "block_stability": float(block_report["nonnegative_block_ratio"]) >= ROUTER_GATE["nonnegative_block_ratio_min"],
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "retention_vs_proximity_pct": retention_pct,
        "failed_checks": [key for key, value in checks.items() if not value],
    }


def compact_chart_audit(
    raw_cache: Dict[Tuple[str, str], pd.DataFrame]
) -> Dict[str, Any]:
    if not PAIR_SOURCE.exists():
        return {"source": str(PAIR_SOURCE), "pairs": [], "reason": "PAIR_SOURCE_MISSING"}
    payload = json.loads(PAIR_SOURCE.read_text(errors="ignore"))
    output: List[Dict[str, Any]] = []
    regime_cache: Dict[Tuple[str, str], Dict[str, pd.DataFrame]] = {
        key: build_regime_frames(raw) for key, raw in raw_cache.items()
    }
    for index, pair in enumerate(payload.get("pairs", [])[:5], start=1):
        item: Dict[str, Any] = {"pair": index, "feature_distance": pair.get("feature_distance")}
        for label, source_key in (("loss", "loss_trade"), ("win", "matched_win_trade")):
            trade = pair.get(source_key, {})
            window = str(trade.get("window", ""))
            symbol = str(trade.get("symbol", ""))
            side = str(trade.get("side", ""))
            entry_ts = int(trade.get("entry_ts", 0))
            signal_ts = max(entry_ts - MINUTE_MS, 0)
            features = regime_features(trade, side=side, signal_ts=signal_ts, frames=regime_cache[(window, symbol)])
            decisions = {router: router_pass(router, features)[0] for router in ROUTERS}
            item[label] = {
                "trade_key": trade.get("trade_key"),
                "window": window,
                "symbol": symbol,
                "side": side,
                "net_R": trade.get("net_R"),
                "features": features,
                "decisions": decisions,
            }
        output.append(item)
    return {
        "source": str(PAIR_SOURCE),
        "source_chart_pack": payload.get("chart_pack_index"),
        "pairs": output,
        "rule": "A router is rejected if it repeatedly blocks matched wins without preferentially blocking losses; chart review cannot create new thresholds.",
    }


def write_audit_html(payload: Dict[str, Any]) -> None:
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
                f"<td>{pair['pair']}</td><td>{label}</td><td>{trade['window']}</td>"
                f"<td>{trade['symbol']}</td><td>{trade['side']}</td><td>{trade['net_R']}</td>"
                f"<td>{decisions}</td></tr>"
            )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Raschke regime router audit</title>"
        "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #334155;padding:7px}</style>"
        "</head><body><h1>Raschke regime-router matched chart audit</h1>"
        f"<p>Source chart pack: {payload.get('source_chart_pack')}</p>"
        "<table><thead><tr><th>Pair</th><th>Type</th><th>Window</th><th>Symbol</th><th>Side</th><th>Net R</th><th>Router decisions</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )
    AUDIT_HTML.write_text(html, encoding="utf-8")


def main() -> None:
    raw_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
    integrity: Dict[str, Any] = {}
    all_trades: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    reason_counts: Dict[str, Any] = {}

    for window in V2.WINDOWS:
        integrity[window] = {}
        reason_counts[window] = {}
        for symbol in V2.SYMBOLS:
            raw, report = V2.load_raw(V2.raw_path(window, symbol))
            raw_cache[(window, symbol)] = raw
            integrity[window][symbol] = report
            result, reasons = run_symbol(raw, symbol=symbol, window_name=window)
            reason_counts[window][symbol] = reasons
            for router, rows in result.items():
                all_trades[(router, window)].extend(rows)

    baseline_combined = (
        all_trades[("router_off", V2.WINDOWS[0])]
        + all_trades[("router_off", V2.WINDOWS[1])]
    )
    baseline_events = max(len(baseline_combined), 1)
    baseline_015 = V2.metrics(baseline_combined, 0.15)

    evaluations: Dict[str, Any] = {}
    ranking: List[Dict[str, Any]] = []
    for router, spec in ROUTERS.items():
        prior_rows = all_trades[(router, V2.WINDOWS[0])]
        second_rows = all_trades[(router, V2.WINDOWS[1])]
        combined_rows = prior_rows + second_rows
        costs: Dict[str, Any] = {}
        for cost in COST_LEVELS:
            key = f"cost_{cost:.2f}"
            costs[key] = {
                V2.WINDOWS[0]: V2.metrics(prior_rows, cost),
                V2.WINDOWS[1]: V2.metrics(second_rows, cost),
                "combined_independent_180d": V2.metrics(combined_rows, cost),
            }
        blocks = monthly_blocks(combined_rows, 0.15)
        retention = float(len(combined_rows) / baseline_events * 100.0)
        assessment = gate_assessment(
            combined=costs["cost_0.15"]["combined_independent_180d"],
            prior=costs["cost_0.15"][V2.WINDOWS[0]],
            second=costs["cost_0.15"][V2.WINDOWS[1]],
            cost020=costs["cost_0.20"]["combined_independent_180d"],
            block_report=blocks,
            retention_pct=retention,
        )
        combined = costs["cost_0.15"]["combined_independent_180d"]
        evaluations[router] = {
            "spec": spec,
            "costs": costs,
            "monthly_purged_blocks_cost_0.15": blocks,
            "gate": assessment,
        }
        ranking.append(
            {
                "router": router,
                "gate_pass": assessment["pass"],
                "failed_checks": assessment["failed_checks"],
                "events": combined["events"],
                "retention_vs_proximity_pct": retention,
                "avg_net_R": combined["avg_net_R"],
                "net_sum_R": combined["net_sum_R"],
                "positive_rate_pct": combined["positive_rate_pct"],
                "profit_factor_R": combined["profit_factor_R"],
                "max_drawdown_R": combined["max_drawdown_R"],
                "positive_symbols": combined["positive_symbols"],
                "cost_0.20_avg_net_R": costs["cost_0.20"]["combined_independent_180d"]["avg_net_R"],
                "prior_avg_net_R": costs["cost_0.15"][V2.WINDOWS[0]]["avg_net_R"],
                "second_avg_net_R": costs["cost_0.15"][V2.WINDOWS[1]]["avg_net_R"],
                "nonnegative_block_ratio": blocks["nonnegative_block_ratio"],
                "avg_improvement_vs_proximity": float(combined["avg_net_R"]) - float(baseline_015["avg_net_R"]),
            }
        )

    ranking.sort(
        key=lambda row: (
            bool(row["gate_pass"]),
            float(row["second_avg_net_R"]),
            float(row["avg_net_R"]),
            float(row["profit_factor_R"]),
            -float(row["max_drawdown_R"]),
        ),
        reverse=True,
    )
    third_holdout_queue = [
        row for row in ranking if row["gate_pass"] and row["router"] != "router_off"
    ][:2]

    audit = compact_chart_audit(raw_cache)
    atomic_json(AUDIT_JSON, audit)
    write_audit_html(audit)

    trades_payload = {
        "status": "PASS_Q4R3_RASCHKE_REGIME_ROUTER_TRADES",
        "base_entry": BASE_ENTRY,
        "base_exit": BASE_EXIT,
        "trades": {
            router: {
                window: all_trades[(router, window)]
                for window in V2.WINDOWS
            }
            for router in ROUTERS
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
        "status": "PASS_Q4R3_ROUTE_A_RASCHKE_REGIME_ROUTER_TOURNAMENT",
        "verdict": (
            "RASCHKE_REGIME_ROUTER_THIRD_HOLDOUT_QUEUE_READY"
            if third_holdout_queue
            else "RASCHKE_REGIME_ROUTER_NO_GATE_PASS_YET"
        ),
        "purpose": "causal one-layer regime routing of the rescued proximity-guard fixed-2R lane across two independent 90d windows",
        "base_lane": {
            "entry_candidate": BASE_ENTRY,
            "exit_policy": BASE_EXIT,
            "cost_0.15": baseline_015,
        },
        "router_candidates": ROUTERS,
        "router_gate": ROUTER_GATE,
        "integrity": integrity,
        "reason_counts": reason_counts,
        "evaluations": evaluations,
        "ranking": ranking,
        "third_holdout_queue": third_holdout_queue,
        "chart_audit": {
            "json": str(AUDIT_JSON),
            "html": str(AUDIT_HTML),
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
