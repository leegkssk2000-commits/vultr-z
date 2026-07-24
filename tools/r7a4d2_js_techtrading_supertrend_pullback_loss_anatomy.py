#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

SYMBOLS = ("XRPUSDT", "LINKUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = ("5m", "15m")


class AuditError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise AuditError("NONFINITE_METRIC")
    return number


def profit_factor(values: Sequence[float]) -> float:
    winners = sum(value for value in values if value > 0.0)
    losers = abs(sum(value for value in values if value < 0.0))
    return winners / losers if losers else (float("inf") if winners else 0.0)


def median(values: Sequence[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def mean(values: Sequence[float]) -> float:
    return float(statistics.fmean(values)) if values else 0.0


def pct(numerator: int, denominator: int) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def paired_trade_rows(gross: Mapping[str, Any], net4: Mapping[str, Any]) -> List[Tuple[Mapping[str, Any], Mapping[str, Any]]]:
    gross_rows = list(gross.get("trade_rows", []))
    net_rows = list(net4.get("trade_rows", []))
    if len(gross_rows) != len(net_rows):
        raise AuditError("COST_PROFILE_TRADE_COUNT_MISMATCH")
    pairs: List[Tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    identity_fields = ("side", "entry_index", "exit_index", "entry_ts_ms", "exit_ts_ms", "exit_reason")
    for gross_row, net_row in zip(gross_rows, net_rows):
        if any(gross_row.get(field) != net_row.get(field) for field in identity_fields):
            raise AuditError("COST_PROFILE_TRADE_IDENTITY_MISMATCH")
        pairs.append((gross_row, net_row))
    return pairs


def summarize_pairs(pairs: Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]]) -> Dict[str, Any]:
    gross_r = [finite(gross["gross_r"]) for gross, _ in pairs]
    net4_r = [finite(net["net_r"]) for _, net in pairs]
    gross_returns = [finite(gross["gross_return"]) for gross, _ in pairs]
    net4_returns = [finite(net["net_return_on_entry_notional"]) for _, net in pairs]
    winners = [index for index, value in enumerate(gross_r) if value > 0.0]
    losers = [index for index, value in enumerate(gross_r) if value < 0.0]
    flats = [index for index, value in enumerate(gross_r) if value == 0.0]
    loser_mfe_r = [finite(pairs[index][0]["mfe_return"]) / 0.01 for index in losers]
    loser_mae_r = [finite(pairs[index][0]["mae_return"]) / 0.01 for index in losers]
    winner_mfe_r = [finite(pairs[index][0]["mfe_return"]) / 0.01 for index in winners]
    winner_mae_r = [finite(pairs[index][0]["mae_return"]) / 0.01 for index in winners]
    hold_bars = [int(gross["hold_bars"]) for gross, _ in pairs]
    exit_reasons = Counter(str(gross["exit_reason"]) for gross, _ in pairs)
    sides = Counter(str(gross["side"]) for gross, _ in pairs)
    cost_drag_r = [net_value - gross_value for gross_value, net_value in zip(gross_r, net4_r)]
    return {
        "trade_count": len(pairs),
        "win_count": len(winners),
        "loss_count": len(losers),
        "flat_count": len(flats),
        "win_rate_pct": pct(len(winners), len(winners) + len(losers)),
        "gross_pf": profit_factor(gross_returns),
        "net4bps_pf": profit_factor(net4_returns),
        "gross_expectancy_r": mean(gross_r),
        "net4bps_expectancy_r": mean(net4_r),
        "cost_drag_r_per_trade": mean(cost_drag_r),
        "gross_sum_r": sum(gross_r),
        "net4bps_sum_r": sum(net4_r),
        "long_trade_count": int(sides.get("long", 0)),
        "short_trade_count": int(sides.get("short", 0)),
        "exit_reason_counts": dict(sorted(exit_reasons.items())),
        "median_hold_bars": median(hold_bars),
        "loser_median_mfe_r": median(loser_mfe_r),
        "loser_median_mae_r": median(loser_mae_r),
        "winner_median_mfe_r": median(winner_mfe_r),
        "winner_median_mae_r": median(winner_mae_r),
        "loser_mfe_ge_0_25r_count": sum(value >= 0.25 for value in loser_mfe_r),
        "loser_mfe_ge_0_50r_count": sum(value >= 0.50 for value in loser_mfe_r),
        "loser_mfe_ge_0_75r_count": sum(value >= 0.75 for value in loser_mfe_r),
        "loser_mfe_ge_1_00r_count": sum(value >= 1.00 for value in loser_mfe_r),
        "loser_mfe_ge_0_50r_pct": pct(sum(value >= 0.50 for value in loser_mfe_r), len(loser_mfe_r)),
        "loser_mfe_ge_1_00r_pct": pct(sum(value >= 1.00 for value in loser_mfe_r), len(loser_mfe_r)),
    }


def subset_pairs(
    pairs: Iterable[Tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    side: str | None = None,
    exit_reason: str | None = None,
) -> List[Tuple[Mapping[str, Any], Mapping[str, Any]]]:
    result = []
    for gross, net in pairs:
        if side is not None and str(gross.get("side")) != side:
            continue
        if exit_reason is not None and str(gross.get("exit_reason")) != exit_reason:
            continue
        result.append((gross, net))
    return result


def dominant_failure(summary: Mapping[str, Any]) -> str:
    if summary["trade_count"] == 0:
        return "NO_TRADES"
    if summary["gross_expectancy_r"] >= 0.0 and summary["net4bps_expectancy_r"] < 0.0:
        return "COST_EROSION"
    if summary["gross_expectancy_r"] < 0.0:
        if summary["loser_mfe_ge_0_50r_pct"] >= 40.0:
            return "EXIT_CAPTURE_SUSPECT"
        return "ENTRY_SELECTIVITY_OR_REGIME_SUSPECT"
    return "NO_PRIMARY_FAILURE"


def load_summary(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise AuditError(f"SUMMARY_MISSING:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "r7a4d2_js_techtrading_supertrend_pullback_exact_oos_replay_v1":
        raise AuditError("SUMMARY_SCHEMA_MISMATCH")
    if not payload.get("source_contract_pass"):
        raise AuditError("SOURCE_CONTRACT_NOT_PASS")
    if not payload.get("signal_parity_pass"):
        raise AuditError("SIGNAL_PARITY_NOT_PASS")
    if payload.get("blockers"):
        raise AuditError("UPSTREAM_BLOCKERS_PRESENT")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    summary_path = Path(args.summary).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = load_summary(summary_path)

    cell_results: Dict[str, Any] = {}
    timeframe_pairs: Dict[str, List[Tuple[Mapping[str, Any], Mapping[str, Any]]]] = defaultdict(list)
    global_pairs: List[Tuple[Mapping[str, Any], Mapping[str, Any]]] = []

    for symbol in SYMBOLS:
        if symbol not in source.get("symbols", {}):
            raise AuditError(f"SYMBOL_MISSING:{symbol}")
        for timeframe in TIMEFRAMES:
            tf = source["symbols"][symbol]["timeframes"].get(timeframe)
            if not isinstance(tf, Mapping):
                raise AuditError(f"TIMEFRAME_MISSING:{symbol}:{timeframe}")
            profiles = tf.get("cost_profiles", {})
            if "0.0" not in profiles or "4.0" not in profiles:
                raise AuditError(f"COST_PROFILE_MISSING:{symbol}:{timeframe}")
            pairs = paired_trade_rows(profiles["0.0"], profiles["4.0"])
            cell_key = f"{symbol}|{timeframe}"
            combined = summarize_pairs(pairs)
            combined["dominant_failure"] = dominant_failure(combined)
            combined["side"] = {
                side: summarize_pairs(subset_pairs(pairs, side=side))
                for side in ("long", "short")
            }
            combined["exit_reason"] = {
                reason: summarize_pairs(subset_pairs(pairs, exit_reason=reason))
                for reason in sorted({str(gross["exit_reason"]) for gross, _ in pairs})
            }
            cell_results[cell_key] = combined
            timeframe_pairs[timeframe].extend(pairs)
            global_pairs.extend(pairs)

    timeframe_results: Dict[str, Any] = {}
    for timeframe in TIMEFRAMES:
        combined = summarize_pairs(timeframe_pairs[timeframe])
        combined["dominant_failure"] = dominant_failure(combined)
        combined["side"] = {
            side: summarize_pairs(subset_pairs(timeframe_pairs[timeframe], side=side))
            for side in ("long", "short")
        }
        timeframe_results[timeframe] = combined

    global_result = summarize_pairs(global_pairs)
    global_result["dominant_failure"] = dominant_failure(global_result)
    global_result["side"] = {
        side: summarize_pairs(subset_pairs(global_pairs, side=side))
        for side in ("long", "short")
    }

    ranked_cells = sorted(
        (
            {
                "cell": cell,
                "gross_expectancy_r": result["gross_expectancy_r"],
                "net4bps_expectancy_r": result["net4bps_expectancy_r"],
                "gross_pf": result["gross_pf"],
                "trade_count": result["trade_count"],
                "dominant_failure": result["dominant_failure"],
            }
            for cell, result in cell_results.items()
        ),
        key=lambda item: (item["gross_expectancy_r"], item["gross_pf"]),
    )

    output = {
        "schema": "r7a4d2_js_techtrading_supertrend_pullback_loss_anatomy_v1",
        "input_summary": str(summary_path),
        "input_summary_sha256": sha256_file(summary_path),
        "source_commit": source.get("source_commit"),
        "source_blob_sha": source.get("source_blob_sha"),
        "source_contract_pass": source.get("source_contract_pass"),
        "signal_parity_pass": source.get("signal_parity_pass"),
        "cell_results": cell_results,
        "timeframe_results": timeframe_results,
        "global_result": global_result,
        "ranked_cells_worst_first": ranked_cells,
        "mutation_count": 0,
        "next_stage": "R7.A4D2_JS_TECHTRADING_SUPERTREND_PULLBACK_LOSS_ANATOMY_DECISION_GATE",
        "blockers": [],
        "state": "PASS_JS_TECHTRADING_SUPERTREND_PULLBACK_LOSS_ANATOMY",
        "rc": 0,
    }
    output_path = output_dir / "js_techtrading_supertrend_pullback_loss_anatomy_v1.json"
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=True) + "\n", encoding="utf-8")

    print(f"STATE={output['state']}")
    print("BLOCKER_COUNT=0")
    for timeframe in TIMEFRAMES:
        result = timeframe_results[timeframe]
        print(
            "TIMEFRAME_DECOMP="
            f"{timeframe}|TRADES={result['trade_count']}|WINS={result['win_count']}|LOSSES={result['loss_count']}"
            f"|WIN_RATE_PCT={result['win_rate_pct']:.6f}|GROSS_PF={result['gross_pf']:.6f}"
            f"|GROSS_EXP_R={result['gross_expectancy_r']:.6f}|NET4BPS_PF={result['net4bps_pf']:.6f}"
            f"|NET4BPS_EXP_R={result['net4bps_expectancy_r']:.6f}|COST_DRAG_R={result['cost_drag_r_per_trade']:.6f}"
            f"|LOSER_MFE_GE_0_5R_PCT={result['loser_mfe_ge_0_50r_pct']:.6f}"
            f"|LOSER_MFE_GE_1R_PCT={result['loser_mfe_ge_1_00r_pct']:.6f}"
            f"|PRIMARY={result['dominant_failure']}"
        )
        for side in ("long", "short"):
            side_result = result["side"][side]
            print(
                "SIDE_DECOMP="
                f"{timeframe}|{side}|TRADES={side_result['trade_count']}|WINS={side_result['win_count']}"
                f"|LOSSES={side_result['loss_count']}|WIN_RATE_PCT={side_result['win_rate_pct']:.6f}"
                f"|GROSS_PF={side_result['gross_pf']:.6f}|GROSS_EXP_R={side_result['gross_expectancy_r']:.6f}"
                f"|NET4BPS_EXP_R={side_result['net4bps_expectancy_r']:.6f}"
            )
    for ranked in ranked_cells:
        print(
            "CELL_DECOMP="
            f"{ranked['cell']}|TRADES={ranked['trade_count']}|GROSS_PF={ranked['gross_pf']:.6f}"
            f"|GROSS_EXP_R={ranked['gross_expectancy_r']:.6f}|NET4BPS_EXP_R={ranked['net4bps_expectancy_r']:.6f}"
            f"|PRIMARY={ranked['dominant_failure']}"
        )
    print(
        "GLOBAL_DECOMP="
        f"TRADES={global_result['trade_count']}|WINS={global_result['win_count']}|LOSSES={global_result['loss_count']}"
        f"|WIN_RATE_PCT={global_result['win_rate_pct']:.6f}|GROSS_PF={global_result['gross_pf']:.6f}"
        f"|GROSS_EXP_R={global_result['gross_expectancy_r']:.6f}|NET4BPS_PF={global_result['net4bps_pf']:.6f}"
        f"|NET4BPS_EXP_R={global_result['net4bps_expectancy_r']:.6f}|COST_DRAG_R={global_result['cost_drag_r_per_trade']:.6f}"
        f"|LOSER_MFE_GE_0_5R_PCT={global_result['loser_mfe_ge_0_50r_pct']:.6f}"
        f"|LOSER_MFE_GE_1R_PCT={global_result['loser_mfe_ge_1_00r_pct']:.6f}"
        f"|PRIMARY={global_result['dominant_failure']}"
    )
    print(f"OUTPUT_JSON={output_path}")
    print("MUTATION_COUNT=0")
    print(f"NEXT_STAGE={output['next_stage']}")
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print("STATE=HOLD_JS_TECHTRADING_SUPERTREND_PULLBACK_LOSS_ANATOMY")
        print("BLOCKER_COUNT=1")
        print(f"BLOCKERS=[\"{exc}\"]")
        print("RC=2")
        raise SystemExit(2)
