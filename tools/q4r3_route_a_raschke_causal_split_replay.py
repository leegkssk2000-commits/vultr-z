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
OVERLAY_ROOT = Path(os.environ.get("Q4R3_ROUTE_A_OVERLAY_ROOT", "/tmp/q4r3-route-a-causal-split"))
V2_PATH = OVERLAY_ROOT / "tools" / "q4r3_route_a_raschke_v2_entry_exit_tournament.py"

OUT = ROOT / "runtime" / "q4r3_route_a_raschke_causal_split_latest.json"
TRADES_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_causal_split_trades_latest.json"
DIAGNOSTIC_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_short_confirmation_diagnostic_latest.json"

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


V2 = _load_module("q4r3_raschke_causal_split_v2", V2_PATH)

LANES: Dict[str, Dict[str, Any]] = {
    "proximity_baseline": {
        "mechanism": "proximity guard + fixed 2R; no split",
        "kind": "baseline",
    },
    "long_only_core": {
        "mechanism": "proximity guard; long signals only",
        "kind": "specialized_long",
    },
    "utc_00_07_hold": {
        "mechanism": "proximity guard; block signals entered during UTC 00:00-07:59",
        "kind": "general_split",
    },
    "link_reserve": {
        "mechanism": "proximity guard; LINKUSDT becomes observer-only",
        "kind": "general_split",
    },
    "short_followthrough_1h": {
        "mechanism": "long unchanged; short waits one completed 1h bar and requires bearish close below original signal-bar low",
        "kind": "general_split",
    },
    "short_reconfirm_1h": {
        "mechanism": "long unchanged; short enters only if the source strategy independently reconfirms short one completed 1h bar later",
        "kind": "general_split",
    },
}

GENERAL_GATE = {
    "events_min": 70,
    "retention_pct_min": 70.0,
    "combined_avg_R_min": 0.08,
    "combined_pf_min": 1.25,
    "combined_mdd_R_max": 8.0,
    "positive_symbols_min": 3,
    "cost_020_avg_R_min_exclusive": 0.0,
    "prior_avg_R_min": 0.0,
    "second_avg_R_min": -0.05,
    "nonnegative_block_ratio_min": 2.0 / 3.0,
}

LONG_SPECIALIST_GATE = {
    "events_min": 35,
    "combined_avg_R_min": 0.08,
    "combined_pf_min": 1.25,
    "combined_mdd_R_max": 4.0,
    "positive_symbols_min": 3,
    "cost_020_avg_R_min_exclusive": 0.0,
    "prior_avg_R_min": 0.0,
    "second_avg_R_min": -0.05,
    "nonnegative_block_ratio_min": 2.0 / 3.0,
}


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def utc_session(stamp_ms: int) -> str:
    hour = int(pd.to_datetime(int(stamp_ms), unit="ms", utc=True).hour)
    if hour < 8:
        return "utc_00_07"
    if hour < 16:
        return "utc_08_15"
    return "utc_16_23"


def next_complete_bar(
    bars: pd.DataFrame,
    *,
    end_i: int,
    signal_bar: pd.Series,
) -> Optional[pd.Series]:
    if end_i >= len(bars):
        return None
    confirm = bars.iloc[end_i]
    if not bool(confirm.get("complete", False)):
        return None
    delta = pd.Timestamp(confirm["bucket"]) - pd.Timestamp(signal_bar["bucket"])
    if delta.total_seconds() != V2.TIMEFRAME_MIN * 60:
        return None
    return confirm


def short_followthrough_pass(signal_bar: pd.Series, confirm_bar: pd.Series) -> bool:
    return bool(
        float(confirm_bar["close"]) < float(confirm_bar["open"])
        and float(confirm_bar["close"]) < float(signal_bar["low"])
    )


def reconfirm_short(
    bars: pd.DataFrame,
    *,
    end_i: int,
) -> Optional[Dict[str, Any]]:
    start = end_i - V2.WINDOW_BARS + 1
    if start < 0 or end_i >= len(bars):
        return None
    window = bars.iloc[start : end_i + 1]
    if len(window) != V2.WINDOW_BARS or not V2.window_is_contiguous(window):
        return None
    result = V2.strategy(
        window[["ts", "open", "high", "low", "close", "volume"]].copy(),
        config=V2.Config(confirmation_mode="candle_direction"),
    )
    if not isinstance(result, dict) or str(result.get("action", "")).lower() != "enter":
        return None
    if str(result.get("side", "")).lower() != "short":
        return None
    if not V2.entry_pass(BASE_ENTRY, result):
        return None
    return result


def lane_decision(
    lane: str,
    *,
    symbol: str,
    side: str,
    signal_ts: int,
    signal_bar: pd.Series,
    bars: pd.DataFrame,
    end_i: int,
    initial_result: Dict[str, Any],
) -> Tuple[bool, Optional[int], Dict[str, Any], str]:
    next_raw_idx = int(signal_bar["raw_end_idx"]) + 1
    if lane == "long_only_core" and side != "long":
        return False, None, initial_result, "short_routed_to_observer"
    if lane == "utc_00_07_hold" and utc_session(signal_ts) == "utc_00_07":
        return False, None, initial_result, "utc_00_07_hold"
    if lane == "link_reserve" and symbol == "LINKUSDT":
        return False, None, initial_result, "link_observer_only"

    if side != "short" or lane not in {"short_followthrough_1h", "short_reconfirm_1h"}:
        return True, next_raw_idx, initial_result, "immediate"

    confirm_bar = next_complete_bar(bars, end_i=end_i, signal_bar=signal_bar)
    if confirm_bar is None:
        return False, None, initial_result, "confirmation_bar_unavailable"
    confirm_entry_idx = int(confirm_bar["raw_end_idx"]) + 1

    if lane == "short_followthrough_1h":
        if not short_followthrough_pass(signal_bar, confirm_bar):
            return False, None, initial_result, "short_followthrough_failed"
        return True, confirm_entry_idx, initial_result, "short_followthrough_passed"

    reconfirmed = reconfirm_short(bars, end_i=end_i)
    if reconfirmed is None:
        return False, None, initial_result, "short_reconfirmation_failed"
    return True, confirm_entry_idx, reconfirmed, "short_reconfirmation_passed"


def run_symbol(
    raw: pd.DataFrame,
    *,
    symbol: str,
    window_name: str,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Dict[str, int]]]:
    bars = V2.BASE.make_bars(raw, V2.TIMEFRAME_MIN)
    trades: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    blocked_until: Dict[str, int] = defaultdict(lambda: -1)
    reasons: Dict[str, Dict[str, int]] = {
        lane: defaultdict(int) for lane in LANES
    }
    config = V2.Config(confirmation_mode="candle_direction")

    for end_i in range(V2.WINDOW_BARS, len(bars)):
        window = bars.iloc[end_i - V2.WINDOW_BARS : end_i]
        if not V2.window_is_contiguous(window):
            for lane in LANES:
                reasons[lane]["non_contiguous_window"] += 1
            continue
        signal_bar = bars.iloc[end_i - 1]
        immediate_idx = int(signal_bar["raw_end_idx"]) + 1
        if immediate_idx >= len(raw):
            for lane in LANES:
                reasons[lane]["no_next_open"] += 1
            continue

        result = V2.strategy(
            window[["ts", "open", "high", "low", "close", "volume"]].copy(),
            config=config,
        )
        base_reason = str(result.get("why", "unknown")) if isinstance(result, dict) else "invalid_result"
        if not isinstance(result, dict) or str(result.get("action", "")).lower() != "enter":
            continue
        if not V2.entry_pass(BASE_ENTRY, result):
            for lane in LANES:
                reasons[lane]["proximity_guard_block"] += 1
            continue
        side = str(result.get("side", "")).lower()
        if side not in {"long", "short"}:
            for lane in LANES:
                reasons[lane]["invalid_side"] += 1
            continue
        signal_ts = int(signal_bar["ts"])

        for lane in LANES:
            passed, entry_idx, lane_result, decision_reason = lane_decision(
                lane,
                symbol=symbol,
                side=side,
                signal_ts=signal_ts,
                signal_bar=signal_bar,
                bars=bars,
                end_i=end_i,
                initial_result=result,
            )
            reasons[lane][decision_reason] += 1
            if not passed or entry_idx is None:
                continue
            if entry_idx >= len(raw):
                reasons[lane]["entry_after_data_end"] += 1
                continue
            entry_ts = int(raw.iloc[entry_idx]["ts"])
            if entry_ts <= blocked_until[lane]:
                reasons[lane]["cooldown"] += 1
                continue
            try:
                signal_entry = float(lane_result["entry"])
                native_stop = float(lane_result["sl"])
            except (KeyError, TypeError, ValueError):
                reasons[lane]["invalid_contract"] += 1
                continue
            trade = V2.simulate_policy(
                raw,
                entry_idx=entry_idx,
                side=side,
                signal_entry=signal_entry,
                native_stop=native_stop,
                policy_name=BASE_EXIT,
            )
            if trade is None:
                reasons[lane]["simulation_reject"] += 1
                continue
            trade.update(
                {
                    "lane": lane,
                    "lane_kind": LANES[lane]["kind"],
                    "entry_candidate": BASE_ENTRY,
                    "exit_policy": BASE_EXIT,
                    "symbol": symbol,
                    "window": window_name,
                    "side": side,
                    "signal_ts": signal_ts,
                    "entry_delay_min": int((entry_ts - signal_ts) / MINUTE_MS),
                    "decision_reason": decision_reason,
                    "why": base_reason,
                    **V2.signal_metadata(lane_result),
                }
            )
            trades[lane].append(trade)
            blocked_until[lane] = int(trade["exit_ts"]) + V2.COOLDOWN_MIN * MINUTE_MS

    return trades, {
        lane: dict(sorted(counts.items()))
        for lane, counts in reasons.items()
    }


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


def assess_lane(
    lane: str,
    *,
    prior: Dict[str, Any],
    second: Dict[str, Any],
    combined: Dict[str, Any],
    cost020: Dict[str, Any],
    blocks: Dict[str, Any],
    retention_pct: float,
) -> Dict[str, Any]:
    kind = LANES[lane]["kind"]
    if kind == "baseline":
        return {
            "pass": False,
            "checks": {},
            "failed_checks": ["baseline_reference_only"],
            "retention_pct": retention_pct,
        }
    gate = LONG_SPECIALIST_GATE if kind == "specialized_long" else GENERAL_GATE
    checks = {
        "events": int(combined["events"]) >= gate["events_min"],
        "combined_avg": float(combined["avg_net_R"]) >= gate["combined_avg_R_min"],
        "combined_pf": float(combined["profit_factor_R"]) >= gate["combined_pf_min"],
        "combined_mdd": float(combined["max_drawdown_R"]) <= gate["combined_mdd_R_max"],
        "positive_symbols": int(combined["positive_symbols"]) >= gate["positive_symbols_min"],
        "cost020": float(cost020["avg_net_R"]) > gate["cost_020_avg_R_min_exclusive"],
        "prior_window": float(prior["avg_net_R"]) >= gate["prior_avg_R_min"],
        "second_window": float(second["avg_net_R"]) >= gate["second_avg_R_min"],
        "block_stability": float(blocks["nonnegative_block_ratio"]) >= gate["nonnegative_block_ratio_min"],
    }
    if kind != "specialized_long":
        checks["retention"] = retention_pct >= gate["retention_pct_min"]
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "failed_checks": [key for key, value in checks.items() if not value],
        "retention_pct": retention_pct,
        "gate": gate,
    }


def side_metrics(rows: Sequence[Dict[str, Any]], cost_pct: float = 0.15) -> Dict[str, Any]:
    return {
        side: V2.metrics([row for row in rows if str(row.get("side")) == side], cost_pct)
        for side in ("long", "short")
    }


def compact_trade(row: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "lane",
        "window",
        "symbol",
        "side",
        "signal_ts",
        "entry_ts",
        "exit_ts",
        "entry_delay_min",
        "decision_reason",
        "outcome",
        "entry",
        "exit",
        "stop",
        "target",
        "gross_r",
        "base_risk",
    )
    return {key: row.get(key) for key in keys}


def confirmation_diagnostic(
    all_trades: Dict[Tuple[str, str], List[Dict[str, Any]]]
) -> Dict[str, Any]:
    baseline_second = all_trades[("proximity_baseline", V2.WINDOWS[1])]
    baseline_short = [row for row in baseline_second if str(row.get("side")) == "short"]
    output: Dict[str, Any] = {
        "baseline_second_short": V2.metrics(baseline_short, 0.15),
        "lanes": {},
    }
    baseline_ids = {
        (row["symbol"], int(row["signal_ts"])): row
        for row in baseline_short
    }
    for lane in ("short_followthrough_1h", "short_reconfirm_1h"):
        rows = [
            row for row in all_trades[(lane, V2.WINDOWS[1])]
            if str(row.get("side")) == "short"
        ]
        passed_ids = {(row["symbol"], int(row["signal_ts"])) for row in rows}
        blocked = [row for key, row in baseline_ids.items() if key not in passed_ids]
        output["lanes"][lane] = {
            "second_short": V2.metrics(rows, 0.15),
            "blocked_original_short_events": len(blocked),
            "blocked_original_short_net_R": float(sum(V2.net_r(row, 0.15) for row in blocked)),
            "blocked_original_short_losses": sum(V2.net_r(row, 0.15) < 0 for row in blocked),
            "blocked_original_short_wins": sum(V2.net_r(row, 0.15) > 0 for row in blocked),
            "top_blocked_losses": [
                compact_trade(row)
                for row in sorted(blocked, key=lambda item: V2.net_r(item, 0.15))[:10]
            ],
        }
    return output


def main() -> None:
    raw_integrity: Dict[str, Any] = {}
    reason_counts: Dict[str, Any] = {}
    all_trades: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)

    for window in V2.WINDOWS:
        raw_integrity[window] = {}
        reason_counts[window] = {}
        for symbol in V2.SYMBOLS:
            raw, report = V2.load_raw(V2.raw_path(window, symbol))
            raw_integrity[window][symbol] = report
            result, reasons = run_symbol(raw, symbol=symbol, window_name=window)
            reason_counts[window][symbol] = reasons
            for lane, rows in result.items():
                all_trades[(lane, window)].extend(rows)

    baseline_combined = (
        all_trades[("proximity_baseline", V2.WINDOWS[0])]
        + all_trades[("proximity_baseline", V2.WINDOWS[1])]
    )
    baseline_events = max(len(baseline_combined), 1)

    evaluations: Dict[str, Any] = {}
    ranking: List[Dict[str, Any]] = []
    for lane, spec in LANES.items():
        prior_rows = all_trades[(lane, V2.WINDOWS[0])]
        second_rows = all_trades[(lane, V2.WINDOWS[1])]
        combined_rows = prior_rows + second_rows
        costs: Dict[str, Any] = {}
        for cost in COST_LEVELS:
            key = f"cost_{int(round(cost * 100)):03d}"
            costs[key] = {
                V2.WINDOWS[0]: V2.metrics(prior_rows, cost),
                V2.WINDOWS[1]: V2.metrics(second_rows, cost),
                "combined_independent_180d": V2.metrics(combined_rows, cost),
            }
        blocks = monthly_blocks(combined_rows, 0.15)
        combined015 = costs["cost_015"]["combined_independent_180d"]
        prior015 = costs["cost_015"][V2.WINDOWS[0]]
        second015 = costs["cost_015"][V2.WINDOWS[1]]
        cost020 = costs["cost_020"]["combined_independent_180d"]
        retention = float(len(combined_rows) / baseline_events * 100.0)
        assessment = assess_lane(
            lane,
            prior=prior015,
            second=second015,
            combined=combined015,
            cost020=cost020,
            blocks=blocks,
            retention_pct=retention,
        )
        evaluations[lane] = {
            "spec": spec,
            "costs": costs,
            "monthly_purged_blocks_cost_015": blocks,
            "side_metrics_cost_015": side_metrics(combined_rows, 0.15),
            "gate": assessment,
        }
        ranking.append(
            {
                "lane": lane,
                "kind": spec["kind"],
                "gate_pass": assessment["pass"],
                "failed_checks": assessment["failed_checks"],
                "events": combined015["events"],
                "retention_pct": retention,
                "avg_net_R": combined015["avg_net_R"],
                "net_sum_R": combined015["net_sum_R"],
                "positive_rate_pct": combined015["positive_rate_pct"],
                "profit_factor_R": combined015["profit_factor_R"],
                "max_drawdown_R": combined015["max_drawdown_R"],
                "positive_symbols": combined015["positive_symbols"],
                "cost_020_avg_net_R": cost020["avg_net_R"],
                "prior_avg_net_R": prior015["avg_net_R"],
                "second_avg_net_R": second015["avg_net_R"],
                "nonnegative_block_ratio": blocks["nonnegative_block_ratio"],
                "second_short_avg_net_R": side_metrics(second_rows, 0.15)["short"]["avg_net_R"],
                "second_long_avg_net_R": side_metrics(second_rows, 0.15)["long"]["avg_net_R"],
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
    queue = [row["lane"] for row in ranking if row["gate_pass"]][:2]
    diagnostic = confirmation_diagnostic(all_trades)

    payload = {
        "status": "PASS_Q4R3_ROUTE_A_RASCHKE_CAUSAL_SPLIT_REPLAY",
        "verdict": (
            "RASCHKE_CAUSAL_SPLIT_CANDIDATE_FOUND"
            if queue
            else "RASCHKE_CAUSAL_SPLIT_NO_GATE_PASS_YET"
        ),
        "base_lane": "proximity_baseline",
        "contract": {
            "entry": BASE_ENTRY,
            "exit": BASE_EXIT,
            "target_R": 2.0,
            "loss_cap_R": -0.5,
            "timeout_min": V2.TIMEOUT_MIN,
            "cooldown_min": V2.COOLDOWN_MIN,
            "cost_levels_pct": COST_LEVELS,
        },
        "lanes": LANES,
        "general_gate": GENERAL_GATE,
        "long_specialist_gate": LONG_SPECIALIST_GATE,
        "evaluations": evaluations,
        "ranking": ranking,
        "third_holdout_queue": queue,
        "short_confirmation_diagnostic": diagnostic,
        "raw_integrity": raw_integrity,
        "reason_counts": reason_counts,
        "outputs": {
            "result": str(OUT),
            "trades": str(TRADES_OUT),
            "short_diagnostic": str(DIAGNOSTIC_OUT),
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
    trades_payload = {
        "status": "PASS_Q4R3_RASCHKE_CAUSAL_SPLIT_TRADES",
        "trades": {
            lane: {
                window: all_trades[(lane, window)]
                for window in V2.WINDOWS
            }
            for lane in LANES
        },
    }
    diagnostic_payload = {
        "status": "PASS_Q4R3_RASCHKE_SHORT_CONFIRMATION_DIAGNOSTIC",
        **diagnostic,
    }
    atomic_json(TRADES_OUT, trades_payload)
    atomic_json(DIAGNOSTIC_OUT, diagnostic_payload)
    atomic_json(OUT, payload)
    print(json.dumps({
        "status": payload["status"],
        "verdict": payload["verdict"],
        "third_holdout_queue": queue,
        "ranking": ranking,
        "short_confirmation_diagnostic": diagnostic,
        "authority": payload["authority"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
