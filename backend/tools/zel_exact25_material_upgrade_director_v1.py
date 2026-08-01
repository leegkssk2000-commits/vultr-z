from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_EXACT25_MATERIAL_UPGRADE_DIRECTOR_V1"
EXPECTED_STRATEGY_COUNT = 25
LOW_SAMPLE_MIN = 20
RESEARCH_SAMPLE_MIN = 100
MATERIAL_SAMPLE_MIN = 300


@dataclass(frozen=True)
class Row:
    strategy_id: str
    interval: str
    strategy_call_count: int
    signal_count: int
    valid_entry_count: int
    open_count: int
    close_count: int
    censored_open_at_window_end: int
    error_count: int
    net_r: float | None
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float | None
    win_rate_pct: float | None
    average_mfe_r: float | None
    average_mae_r: float | None
    average_exposure_min: float | None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def finite_float(value: Any) -> float | None:
    if value in (None, "", "None", "null"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def integer(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def read_scoreboard(path: Path, interval: str) -> dict[str, Row]:
    if not path.is_file():
        raise RuntimeError(f"SCOREBOARD_MISSING:{interval}:{path}")
    rows: dict[str, Row] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for source in csv.DictReader(handle):
            strategy_id = str(source.get("strategy_id") or "").strip()
            if not strategy_id:
                raise RuntimeError(f"STRATEGY_ID_MISSING:{interval}")
            if strategy_id in rows:
                raise RuntimeError(f"DUPLICATE_STRATEGY:{interval}:{strategy_id}")
            rows[strategy_id] = Row(
                strategy_id=strategy_id,
                interval=interval,
                strategy_call_count=integer(source.get("strategy_call_count")),
                signal_count=integer(source.get("signal_count")),
                valid_entry_count=integer(source.get("valid_entry_count")),
                open_count=integer(source.get("open_count")),
                close_count=integer(source.get("close_count")),
                censored_open_at_window_end=integer(source.get("censored_open_at_window_end")),
                error_count=integer(source.get("error_count")),
                net_r=finite_float(source.get("net_R_ex_funding")),
                expectancy_r=finite_float(source.get("expectancy_R_ex_funding")),
                profit_factor=finite_float(source.get("profit_factor_ex_funding")),
                max_drawdown_r=finite_float(source.get("max_drawdown_R_ex_funding")),
                win_rate_pct=finite_float(source.get("win_rate_pct")),
                average_mfe_r=finite_float(source.get("average_MFE_R")),
                average_mae_r=finite_float(source.get("average_MAE_R")),
                average_exposure_min=finite_float(source.get("average_exposure_min")),
            )
    if len(rows) != EXPECTED_STRATEGY_COUNT:
        raise RuntimeError(f"NOT_EXACT25:{interval}:{len(rows)}")
    return rows


def sum_int(rows: Iterable[Row], field: str) -> int:
    return sum(int(getattr(row, field)) for row in rows)


def weighted(rows: Iterable[Row], field: str, weight_field: str = "close_count") -> float | None:
    pairs = []
    for row in rows:
        value = getattr(row, field)
        weight = int(getattr(row, weight_field))
        if value is not None and weight > 0:
            pairs.append((float(value), weight))
    if not pairs:
        return None
    total = sum(weight for _, weight in pairs)
    return sum(value * weight for value, weight in pairs) / total


def add_optional(rows: Iterable[Row], field: str) -> float | None:
    values = [float(getattr(row, field)) for row in rows if getattr(row, field) is not None]
    return sum(values) if values else None


def root_cause(counters: Mapping[str, int], metrics: Mapping[str, float | None]) -> tuple[str, str, str]:
    if counters["error_count"] > 0:
        return "STRATEGY_EXECUTION_ERROR", "SOURCE_OR_RUNTIME_CONTRACT", "SOURCE_AUDIT"
    if counters["signal_count"] == 0:
        return "NO_SIGNAL_DORMANT", "ENTRY_TRIGGER_THRESHOLD", "COUNTERFACTUAL_TRIGGER_PROBE"
    if counters["valid_entry_count"] == 0:
        return "SIGNAL_WITH_INVALID_ENTRY", "ENTRY_SCHEMA_OR_RISK_FIELDS", "OUTPUT_CONTRACT_REPAIR"
    if counters["open_count"] == 0:
        return "VALID_ENTRY_NOT_OPENED", "POSITION_CONSTRUCTION_CONTRACT", "OPEN_PATH_REPAIR"
    if counters["close_count"] == 0:
        return "OPEN_WITHOUT_CLOSE", "EXIT_COVERAGE", "EXIT_PATH_REPAIR"
    if counters["close_count"] < LOW_SAMPLE_MIN:
        return "LOW_SAMPLE_RARE_OR_OVERFILTERED", "ENTRY_FILTER_SELECTIVITY", "SINGLE_FILTER_RELAXATION"
    if counters["close_count"] < RESEARCH_SAMPLE_MIN:
        return "THIN_SAMPLE", "ENTRY_FILTER_SELECTIVITY", "SINGLE_FILTER_RELAXATION"
    expectancy = metrics.get("expectancy_r")
    pf = metrics.get("profit_factor")
    if expectancy is None or pf is None:
        return "METRIC_INCOMPLETE", "MEASUREMENT_CONTRACT", "MEASUREMENT_REPAIR"
    if expectancy < 0.0 or pf < 1.0:
        mfe = metrics.get("average_mfe_r")
        mae = metrics.get("average_mae_r")
        exposure = metrics.get("average_exposure_min")
        if mfe is not None and mae is not None and mfe > abs(mae):
            return "NEGATIVE_EDGE_WITH_CAPTURE_LEAK", "EXIT_CAPTURE", "SINGLE_EXIT_VARIANT"
        if exposure is not None and exposure >= 90.0:
            return "NEGATIVE_EDGE_WITH_LONG_EXPOSURE", "TIME_EXPOSURE", "SINGLE_TIME_STOP_VARIANT"
        return "NEGATIVE_OR_UNSTABLE_EDGE", "REGIME_FILTER", "SINGLE_REGIME_VARIANT"
    if counters["close_count"] < MATERIAL_SAMPLE_MIN:
        return "POSITIVE_EDGE_RESEARCH_SAMPLE", "DURABILITY", "W2_W3_CONFIRMATION"
    return "MATERIAL_READY_CANDIDATE", "NONE", "MATERIAL_QUALITY_GATE"


def material_gate(counters: Mapping[str, int], metrics: Mapping[str, float | None], fingerprint: str) -> dict[str, Any]:
    expectancy = metrics.get("expectancy_r")
    pf = metrics.get("profit_factor")
    checks = {
        "no_execution_errors": counters["error_count"] == 0,
        "sample_ge_300": counters["close_count"] >= MATERIAL_SAMPLE_MIN,
        "expectancy_positive": expectancy is not None and expectancy > 0.0,
        "profit_factor_ge_1": pf is not None and pf >= 1.0,
        "not_dormant": fingerprint != "NO_SIGNAL_DORMANT",
        "closed_trade_integrity": counters["open_count"] >= counters["close_count"],
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "synthesis_eligible": all(checks.values()),
        "promotion_authority": False,
    }


def make_card(strategy_id: str, rows: list[Row]) -> dict[str, Any]:
    counters = {
        field: sum_int(rows, field)
        for field in (
            "strategy_call_count", "signal_count", "valid_entry_count", "open_count",
            "close_count", "censored_open_at_window_end", "error_count",
        )
    }
    metrics = {
        "net_r": add_optional(rows, "net_r"),
        "expectancy_r": weighted(rows, "expectancy_r"),
        "profit_factor": weighted(rows, "profit_factor"),
        "max_drawdown_r_sum": add_optional(rows, "max_drawdown_r"),
        "win_rate_pct": weighted(rows, "win_rate_pct"),
        "average_mfe_r": weighted(rows, "average_mfe_r"),
        "average_mae_r": weighted(rows, "average_mae_r"),
        "average_exposure_min": weighted(rows, "average_exposure_min"),
    }
    fingerprint, axis, repair = root_cause(counters, metrics)
    gate = material_gate(counters, metrics, fingerprint)
    return {
        "strategy_id": strategy_id,
        "intervals": {
            row.interval: {
                "strategy_call_count": row.strategy_call_count,
                "signal_count": row.signal_count,
                "valid_entry_count": row.valid_entry_count,
                "open_count": row.open_count,
                "close_count": row.close_count,
                "censored_open_at_window_end": row.censored_open_at_window_end,
                "error_count": row.error_count,
                "net_r": row.net_r,
                "expectancy_r": row.expectancy_r,
                "profit_factor": row.profit_factor,
                "max_drawdown_r": row.max_drawdown_r,
                "win_rate_pct": row.win_rate_pct,
                "average_mfe_r": row.average_mfe_r,
                "average_mae_r": row.average_mae_r,
                "average_exposure_min": row.average_exposure_min,
            }
            for row in rows
        },
        "combined_counters": counters,
        "combined_metrics": metrics,
        "failure_fingerprint": fingerprint,
        "causal_axis": axis,
        "next_repair": repair,
        "max_changed_axes": 1,
        "material_gate": gate,
        "next_validation_order": [
            "SOURCE_AUDIT",
            "ONE_AXIS_CHILD_VARIANT",
            "DATA_B_15M_AND_1M_REPLAY",
            "W2_NEW_FORWARD",
            "W3_TEMPORAL_DURABILITY",
            "SEALED_FINAL_HOLDOUT",
            "REAL_SHADOW",
        ],
        "canonical_strategy_mutation_allowed": False,
        "canonical_registry_mutation_allowed": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def build_report(scoreboard_15m: Path, scoreboard_1m: Path) -> dict[str, Any]:
    rows_15m = read_scoreboard(scoreboard_15m, "15m")
    rows_1m = read_scoreboard(scoreboard_1m, "1m")
    if set(rows_15m) != set(rows_1m):
        raise RuntimeError("STRATEGY_SET_MISMATCH_15M_1M")
    cards = [make_card(strategy_id, [rows_15m[strategy_id], rows_1m[strategy_id]]) for strategy_id in sorted(rows_15m)]
    queue = [
        {
            "strategy_id": card["strategy_id"],
            "failure_fingerprint": card["failure_fingerprint"],
            "causal_axis": card["causal_axis"],
            "next_repair": card["next_repair"],
            "priority": (
                0 if card["failure_fingerprint"] in {"STRATEGY_EXECUTION_ERROR", "SIGNAL_WITH_INVALID_ENTRY", "VALID_ENTRY_NOT_OPENED", "OPEN_WITHOUT_CLOSE"}
                else 1 if card["failure_fingerprint"] in {"NO_SIGNAL_DORMANT", "LOW_SAMPLE_RARE_OR_OVERFILTERED", "THIN_SAMPLE"}
                else 2 if not card["material_gate"]["pass"]
                else 3
            ),
            "synthesis_eligible": card["material_gate"]["synthesis_eligible"],
        }
        for card in cards
    ]
    queue.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    fingerprint_counts: dict[str, int] = {}
    for card in cards:
        key = str(card["failure_fingerprint"])
        fingerprint_counts[key] = fingerprint_counts.get(key, 0) + 1
    material_ready = [card["strategy_id"] for card in cards if card["material_gate"]["pass"]]
    repair_required = [card["strategy_id"] for card in cards if not card["material_gate"]["pass"]]
    report = {
        "schema_version": "zel.exact25.material_upgrade_director.v1",
        "version": VERSION,
        "state": "PASS_EXACT25_MATERIAL_DIAGNOSIS_AND_QUEUE",
        "generated_at": now_iso(),
        "strategy_count": len(cards),
        "fingerprint_counts": fingerprint_counts,
        "material_ready_count": len(material_ready),
        "repair_required_count": len(repair_required),
        "material_ready_strategies": material_ready,
        "repair_required_strategies": repair_required,
        "synthesis_policy": {
            "raw_strategy_count": len(cards),
            "eligible_material_count": len(material_ready),
            "zero_or_low_sample_as_direct_material": False,
            "negative_edge_as_direct_material": False,
            "upgrade_before_synthesis": True,
            "max_changed_axes_per_epoch": 1,
        },
        "automatic_loop": [
            "DIAGNOSE_ALL25",
            "SOURCE_SURFACE_DISCOVERY",
            "ONE_AXIS_CHILD_VARIANT",
            "DATA_B_15M_AND_1M_REPLAY",
            "W2_NEW_FORWARD_IF_PASS",
            "W3_DURABILITY_IF_PASS",
            "MATERIAL_POOL_IF_PASS",
            "NEXT_EPOCH_ONLY_ON_NEW_EVIDENCE",
        ],
        "queue": queue,
        "strategies": cards,
        "canonical_strategy_files_mutated": False,
        "canonical_registry_mutated": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
    }
    digest_source = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    report["report_sha256"] = hashlib.sha256(digest_source).hexdigest()
    return report


def self_test() -> None:
    counters = {
        "strategy_call_count": 1000,
        "signal_count": 0,
        "valid_entry_count": 0,
        "open_count": 0,
        "close_count": 0,
        "censored_open_at_window_end": 0,
        "error_count": 0,
    }
    fingerprint, axis, repair = root_cause(counters, {})
    assert (fingerprint, axis, repair) == (
        "NO_SIGNAL_DORMANT", "ENTRY_TRIGGER_THRESHOLD", "COUNTERFACTUAL_TRIGGER_PROBE"
    )
    counters["signal_count"] = 5
    fingerprint, axis, repair = root_cause(counters, {})
    assert fingerprint == "SIGNAL_WITH_INVALID_ENTRY"
    counters.update(valid_entry_count=5, open_count=5, close_count=5)
    metrics = {"expectancy_r": -0.1, "profit_factor": 0.8, "average_mfe_r": 0.7, "average_mae_r": -0.4, "average_exposure_min": 70.0}
    fingerprint, axis, repair = root_cause(counters, metrics)
    assert fingerprint == "LOW_SAMPLE_RARE_OR_OVERFILTERED"
    counters["close_count"] = 500
    counters["open_count"] = 500
    fingerprint, axis, repair = root_cause(counters, metrics)
    assert (fingerprint, axis, repair) == ("NEGATIVE_EDGE_WITH_CAPTURE_LEAK", "EXIT_CAPTURE", "SINGLE_EXIT_VARIANT")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scoreboard-15m", type=Path)
    parser.add_argument("--scoreboard-1m", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("PASS_SELF_TEST")
        return
    if args.scoreboard_15m is None or args.scoreboard_1m is None or args.out is None:
        parser.error("--scoreboard-15m --scoreboard-1m --out are required")
    report = build_report(args.scoreboard_15m, args.scoreboard_1m)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(report["state"], report["material_ready_count"], report["repair_required_count"])


if __name__ == "__main__":
    main()
