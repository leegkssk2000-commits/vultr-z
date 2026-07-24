#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


class AuditError(RuntimeError):
    pass


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def median(values: Sequence[float]) -> float:
    return statistics.median(values) if values else 0.0


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def pct(count: int, total: int) -> float:
    return 100.0 * count / total if total else 0.0


def profit_factor(values: Iterable[float]) -> float:
    values_list = [float(value) for value in values]
    positive = sum(value for value in values_list if value > 0.0)
    negative = abs(sum(value for value in values_list if value < 0.0))
    return positive / negative if negative else (float("inf") if positive else 0.0)


def inferred_initial_risk_pct(trade: Mapping[str, Any]) -> float:
    gross_return = float(trade.get("gross_return", 0.0))
    gross_r = float(trade.get("gross_r", 0.0))
    if abs(gross_r) <= 1e-12:
        return 0.0
    risk = abs(gross_return / gross_r) * 100.0
    return risk if math.isfinite(risk) else 0.0


def validate_trade(trade: Mapping[str, Any]) -> None:
    required = (
        "side",
        "entry_ts_ms",
        "exit_ts_ms",
        "exit_reason",
        "gross_return",
        "net_return",
        "gross_r",
        "net_r",
        "hold_bars",
        "mfe_r",
        "mae_r",
    )
    missing = [key for key in required if key not in trade]
    if missing:
        raise AuditError(f"TRADE_FIELDS_MISSING:{','.join(missing)}")
    numeric = ("gross_return", "net_return", "gross_r", "net_r", "hold_bars", "mfe_r", "mae_r")
    if any(not finite(trade[key]) for key in numeric):
        raise AuditError("TRADE_NONFINITE")


def summarize_trades(trades: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    for trade in trades:
        validate_trade(trade)

    winners = [trade for trade in trades if float(trade["net_r"]) > 0.0]
    losers = [trade for trade in trades if float(trade["net_r"]) < 0.0]
    flats = [trade for trade in trades if float(trade["net_r"]) == 0.0]
    net_r = [float(trade["net_r"]) for trade in trades]
    gross_r = [float(trade["gross_r"]) for trade in trades]
    loser_mfe = [float(trade["mfe_r"]) for trade in losers]
    loser_mae = [float(trade["mae_r"]) for trade in losers]
    winner_mfe = [float(trade["mfe_r"]) for trade in winners]
    winner_mae = [float(trade["mae_r"]) for trade in winners]
    winner_hold = [float(trade["hold_bars"]) for trade in winners]
    loser_hold = [float(trade["hold_bars"]) for trade in losers]
    risks = [risk for trade in trades if (risk := inferred_initial_risk_pct(trade)) > 0.0]
    exit_reasons = Counter(str(trade["exit_reason"]) for trade in trades)
    sides = Counter(str(trade["side"]) for trade in trades)

    loser_mfe_lt_025 = sum(value < 0.25 for value in loser_mfe)
    loser_mfe_ge_05 = sum(value >= 0.5 for value in loser_mfe)
    loser_mfe_ge_10 = sum(value >= 1.0 for value in loser_mfe)
    loser_mae_le_m05 = sum(value <= -0.5 for value in loser_mae)
    loser_mae_le_m10 = sum(value <= -1.0 for value in loser_mae)
    immediate_failure = sum(
        float(trade["mfe_r"]) < 0.25 and float(trade["mae_r"]) <= -0.5
        for trade in losers
    )
    exit_capture_suspect = sum(
        float(trade["mfe_r"]) >= 0.5 and float(trade["net_r"]) < 0.0
        for trade in losers
    )
    winner_capture_ratios = [
        max(-5.0, min(5.0, float(trade["net_r"]) / float(trade["mfe_r"])))
        for trade in winners
        if float(trade["mfe_r"]) > 1e-12
    ]

    return {
        "trade_count": len(trades),
        "winner_count": len(winners),
        "loser_count": len(losers),
        "flat_count": len(flats),
        "win_rate_pct": pct(len(winners), len(trades)),
        "profit_factor_r": profit_factor(net_r),
        "gross_expectancy_r": mean(gross_r),
        "net_expectancy_r": mean(net_r),
        "median_net_r": median(net_r),
        "net_r_p10": percentile(net_r, 0.10),
        "net_r_p90": percentile(net_r, 0.90),
        "median_initial_risk_pct": median(risks),
        "median_winner_mfe_r": median(winner_mfe),
        "median_winner_mae_r": median(winner_mae),
        "median_loser_mfe_r": median(loser_mfe),
        "median_loser_mae_r": median(loser_mae),
        "median_winner_hold_bars": median(winner_hold),
        "median_loser_hold_bars": median(loser_hold),
        "loser_mfe_lt_0_25r_pct": pct(loser_mfe_lt_025, len(losers)),
        "loser_mfe_ge_0_5r_pct": pct(loser_mfe_ge_05, len(losers)),
        "loser_mfe_ge_1_0r_pct": pct(loser_mfe_ge_10, len(losers)),
        "loser_mae_le_minus_0_5r_pct": pct(loser_mae_le_m05, len(losers)),
        "loser_mae_le_minus_1_0r_pct": pct(loser_mae_le_m10, len(losers)),
        "immediate_entry_failure_pct_of_losers": pct(immediate_failure, len(losers)),
        "exit_capture_suspect_pct_of_losers": pct(exit_capture_suspect, len(losers)),
        "median_winner_mfe_capture_ratio": median(winner_capture_ratios),
        "exit_reason_counts": dict(sorted(exit_reasons.items())),
        "side_counts": dict(sorted(sides.items())),
    }


def primary_mechanism(metrics: Mapping[str, Any]) -> str:
    entry_failure = float(metrics["immediate_entry_failure_pct_of_losers"])
    no_excursion = float(metrics["loser_mfe_lt_0_25r_pct"])
    exit_capture = float(metrics["exit_capture_suspect_pct_of_losers"])
    if entry_failure >= 40.0 or no_excursion >= 55.0:
        return "ENTRY_SELECTIVITY_OR_REGIME_PRIMARY"
    if exit_capture >= 30.0:
        return "EXIT_CAPTURE_PRIMARY"
    if no_excursion >= 35.0 and exit_capture >= 20.0:
        return "MIXED_ENTRY_AND_EXIT_FAILURE"
    return "LOW_EDGE_DISTRIBUTED_FAILURE"


def load_summary(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise AuditError(f"SUMMARY_MISSING:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "r7a4d2_user_supplied_video_bundle_upgrade_v1":
        raise AuditError("SUMMARY_SCHEMA_MISMATCH")
    if payload.get("state") != "PASS_USER_SUPPLIED_VIDEO_BUNDLE_UPGRADE":
        raise AuditError("SUMMARY_STATE_NOT_PASS")
    if payload.get("source_video_ids") != ["R2hZlnh37fQ", "g-PLctW8aU0", "cKKLujAdvzk"]:
        raise AuditError("VIDEO_SOURCE_IDS_MISMATCH")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-summary", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    input_path = Path(args.input_summary).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = load_summary(input_path)

    output: Dict[str, Any] = {
        "schema": "r7a4d2_user_video_dema_supertrend_loss_anatomy_v1",
        "state": "PASS_USER_VIDEO_DEMA_SUPERTREND_LOSS_ANATOMY",
        "source_summary": str(input_path),
        "source_target_sha": source.get("target_sha"),
        "source_video_id": "g-PLctW8aU0",
        "strategy_id": "tradinglab_dema200_supertrend12x3_video_v1",
        "timeframes": {},
        "mutation_count": 0,
        "blockers": [],
        "diagnostic_limitations": [
            "MFE and MAE do not reveal intratrade event ordering.",
            "Exit-capture percentages are diagnostic upper bounds, not executable counterfactual returns.",
            "Manual pullback videos R2hZlnh37fQ and cKKLujAdvzk remain unexecuted because objective level and trendline geometry are not defined."
        ],
    }

    overall_trades: List[Mapping[str, Any]] = []
    mechanisms: List[str] = []
    gross_pf_values: List[float] = []
    for timeframe, timeframe_payload in sorted(source["dema_supertrend_oos"].items()):
        symbol_outputs: Dict[str, Any] = {}
        timeframe_trades: List[Mapping[str, Any]] = []
        for symbol, symbol_payload in sorted(timeframe_payload["symbols"].items()):
            gross_trades = symbol_payload["0.0"]["trade_rows"]
            net_trades = symbol_payload["4.0"]["trade_rows"]
            if len(gross_trades) != len(net_trades):
                raise AuditError(f"TRADE_COUNT_PROFILE_MISMATCH:{timeframe}:{symbol}")
            metrics = summarize_trades(net_trades)
            metrics["gross_profile_profit_factor"] = float(symbol_payload["0.0"]["net_profit_factor"])
            metrics["net4bps_profile_profit_factor"] = float(symbol_payload["4.0"]["net_profit_factor"])
            metrics["cost_expectancy_drag_r"] = (
                float(symbol_payload["0.0"]["net_expectancy_r"])
                - float(symbol_payload["4.0"]["net_expectancy_r"])
            )
            metrics["primary_mechanism"] = primary_mechanism(metrics)
            symbol_outputs[symbol] = metrics
            timeframe_trades.extend(net_trades)
            print(
                "LOSS_CELL="
                f"{symbol}|TF={timeframe}|TRADES={metrics['trade_count']}"
                f"|WIN_RATE_PCT={metrics['win_rate_pct']:.6f}"
                f"|PF4={metrics['net4bps_profile_profit_factor']:.6f}"
                f"|EXP4_R={metrics['net_expectancy_r']:.6f}"
                f"|NO_MFE_025_PCT={metrics['loser_mfe_lt_0_25r_pct']:.6f}"
                f"|MFE05_LOSS_PCT={metrics['exit_capture_suspect_pct_of_losers']:.6f}"
                f"|IMMEDIATE_FAIL_PCT={metrics['immediate_entry_failure_pct_of_losers']:.6f}"
                f"|MECHANISM={metrics['primary_mechanism']}"
            )

        timeframe_metrics = summarize_trades(timeframe_trades)
        timeframe_metrics["gross_profile_profit_factor"] = float(timeframe_payload["gross"]["profit_factor"])
        timeframe_metrics["net4bps_profile_profit_factor"] = float(timeframe_payload["net4bps"]["profit_factor"])
        timeframe_metrics["cost_expectancy_drag_r"] = (
            float(timeframe_payload["gross"]["expectancy_r"])
            - float(timeframe_payload["net4bps"]["expectancy_r"])
        )
        timeframe_metrics["primary_mechanism"] = primary_mechanism(timeframe_metrics)
        timeframe_metrics["symbols"] = symbol_outputs
        output["timeframes"][timeframe] = timeframe_metrics
        overall_trades.extend(timeframe_trades)
        mechanisms.append(timeframe_metrics["primary_mechanism"])
        gross_pf_values.append(timeframe_metrics["gross_profile_profit_factor"])
        print(
            "LOSS_TIMEFRAME="
            f"{timeframe}|TRADES={timeframe_metrics['trade_count']}"
            f"|GROSS_PF={timeframe_metrics['gross_profile_profit_factor']:.6f}"
            f"|NET4BPS_PF={timeframe_metrics['net4bps_profile_profit_factor']:.6f}"
            f"|NET4BPS_EXP_R={timeframe_metrics['net_expectancy_r']:.6f}"
            f"|NO_MFE_025_PCT={timeframe_metrics['loser_mfe_lt_0_25r_pct']:.6f}"
            f"|MFE05_LOSS_PCT={timeframe_metrics['exit_capture_suspect_pct_of_losers']:.6f}"
            f"|IMMEDIATE_FAIL_PCT={timeframe_metrics['immediate_entry_failure_pct_of_losers']:.6f}"
            f"|MECHANISM={timeframe_metrics['primary_mechanism']}"
        )

    overall = summarize_trades(overall_trades)
    overall["primary_mechanism"] = primary_mechanism(overall)
    overall["all_timeframes_gross_edge_fail"] = all(value < 1.0 for value in gross_pf_values)
    output["overall"] = overall

    if overall["primary_mechanism"] == "EXIT_CAPTURE_PRIMARY":
        next_stage = "R7.A4D2_USER_VIDEO_FBB_EXIT_AND_PROFIT_PROTECTION_AUDIT"
    elif overall["primary_mechanism"] == "ENTRY_SELECTIVITY_OR_REGIME_PRIMARY":
        next_stage = "R7.A4D2_USER_VIDEO_DEMA_SUPERTREND_ENTRY_STATE_AND_REGIME_AUDIT"
    else:
        next_stage = "R7.A4D2_USER_VIDEO_DEMA_SUPERTREND_SPLIT_ENTRY_EXIT_AUDIT"
    output["next_stage"] = next_stage
    output["redesign_allowed"] = False

    output_path = output_dir / "user_video_dema_supertrend_loss_anatomy_v1.json"
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=True) + "\n", encoding="utf-8")
    print(
        "LOSS_OVERALL="
        f"TRADES={overall['trade_count']}"
        f"|WIN_RATE_PCT={overall['win_rate_pct']:.6f}"
        f"|PF_R={overall['profit_factor_r']:.6f}"
        f"|EXP_R={overall['net_expectancy_r']:.6f}"
        f"|NO_MFE_025_PCT={overall['loser_mfe_lt_0_25r_pct']:.6f}"
        f"|MFE05_LOSS_PCT={overall['exit_capture_suspect_pct_of_losers']:.6f}"
        f"|IMMEDIATE_FAIL_PCT={overall['immediate_entry_failure_pct_of_losers']:.6f}"
        f"|MECHANISM={overall['primary_mechanism']}"
        f"|ALL_GROSS_EDGE_FAIL={str(overall['all_timeframes_gross_edge_fail']).lower()}"
    )
    print(f"STATE={output['state']}")
    print(f"SUMMARY_JSON={output_path}")
    print("MUTATION_COUNT=0")
    print("REDESIGN_ALLOWED=false")
    print(f"NEXT_STAGE={next_stage}")
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print("STATE=HOLD_USER_VIDEO_DEMA_SUPERTREND_LOSS_ANATOMY_INPUT")
        print(f"BLOCKERS=[\"{str(exc)}\"]")
        print("RC=2")
        raise SystemExit(2)
