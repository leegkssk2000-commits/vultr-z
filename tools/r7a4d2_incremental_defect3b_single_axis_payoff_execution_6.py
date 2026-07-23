#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

AUDIT_PATH = Path(
    "runtime/r7a4d2_incremental_defect3b_payoff_geometry_all_loss_audit/"
    "incremental_defect3b_payoff_geometry_all_loss_audit_v1.json"
)
SECOND_SUMMARY_PATH = Path(
    "runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/"
    "all_11_second_wave_summary_v1.json"
)
SECOND_TRADES_PATH = Path(
    "runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/"
    "second_wave_trade_rows_v1.jsonl"
)
DEFECT2_SUMMARY_PATH = Path(
    "runtime/r7a4d2_incremental_defect2_execution/"
    "incremental_defect2_summary_v1.json"
)
OUTPUT_DIR = Path(
    "runtime/r7a4d2_incremental_defect3b_single_axis_payoff_execution_6"
)

LANE_ID = "dual_ma_trend_bot:5m"
EXPECTED_AXIS = "STATE_RESET_COOLDOWN"
EXPECTED_MECHANISM = "REENTRY_CHURN"
COOLDOWN_BARS = 2.0
MIN_TRADES = 24
MIN_SYMBOLS = 3
MIN_POSITIVE_FOLDS = 4
MEANINGFUL_SEVERE_MIN_PNL_PCT = 0.50
MEANINGFUL_SEVERE_MIN_PROFIT_FACTOR = 1.20
EPS = 1e-12


def finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return data


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
            rows.append(row)
    return rows


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(
        path,
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
    )


def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    atomic_text(
        path,
        "".join(
            json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
            for row in rows
        ),
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(paths: Iterable[Path]) -> dict[str, str]:
    return {str(path): digest(path) for path in paths}


def net_r(row: dict[str, Any]) -> float:
    for key in ("net_r", "net_return_r", "expectancy_r"):
        if row.get(key) is not None:
            return finite(row.get(key))
    return finite(row.get("net_pnl_pct")) / max(finite(row.get("risk_pct"), 1.0), EPS)


def net_pnl_pct(row: dict[str, Any]) -> float:
    if row.get("net_pnl_pct") is not None:
        return finite(row.get("net_pnl_pct"))
    return net_r(row) * finite(row.get("risk_pct"), 1.0)


def fold_id(row: dict[str, Any]) -> int:
    value = row.get("fold")
    return int(value) if value is not None else -1


def profile_name(row: dict[str, Any]) -> str:
    profile = str(row.get("profile") or "").strip().lower()
    if profile in {"base", "adverse", "severe"}:
        return profile
    cost = str(row.get("cost_profile_id") or "").strip().lower()
    mapping = {
        "cost_profile_0": "base",
        "cost_profile_1": "adverse",
        "cost_profile_2": "severe",
        "base_conservative": "base",
        "adverse": "adverse",
        "severe": "severe",
    }
    return mapping.get(cost, profile or "other")


def cell_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("cost_profile_id") or profile_name(row)),
        str(row.get("timing_id") or "timing_0"),
    )


def event_order_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        fold_id(row),
        str(row.get("symbol") or ""),
        finite(row.get("entry_timestamp")),
        int(row.get("entry_source_index") if row.get("entry_source_index") is not None else -1),
        int(row.get("entry_index") if row.get("entry_index") is not None else -1),
        str(row.get("segment_id") or ""),
    )


def entry_index(row: dict[str, Any]) -> int:
    for key in ("entry_source_index", "entry_index"):
        value = row.get(key)
        if value is not None:
            return int(value)
    return -1


def exit_index(row: dict[str, Any]) -> int:
    for key in ("exit_source_index", "exit_index"):
        value = row.get(key)
        if value is not None:
            return int(value)
    return entry_index(row)


def observable_signature_matches(row: dict[str, Any], cluster: dict[str, Any]) -> bool:
    axes = list(cluster.get("axes") or [])
    values = list(cluster.get("values") or [])
    signature = dict(zip(axes, values))
    # exit_reason is intentionally ignored because it is future information.
    for key in ("regime", "side", "signal_reason"):
        expected = str(signature.get(key) or "")
        if expected and str(row.get(key) or "") != expected:
            return False
    return True


def apply_state_reset_cooldown(
    rows: list[dict[str, Any]],
    cluster: dict[str, Any],
    cooldown_bars: float = COOLDOWN_BARS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    by_stream: dict[tuple[str, int, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cost_profile_id, timing_id = cell_key(row)
        by_stream[
            (
                str(row.get("lane_id") or ""),
                fold_id(row),
                str(row.get("symbol") or ""),
                cost_profile_id,
                timing_id,
            )
        ].append(row)

    for stream_rows in by_stream.values():
        ordered = sorted(stream_rows, key=event_order_key)
        previous_executed: dict[str, Any] | None = None
        for row in ordered:
            block = False
            reason = ""
            if previous_executed is not None:
                prior_loss = net_r(previous_executed) < 0
                prior_stop = str(previous_executed.get("exit_reason") or "") in {
                    "stop", "rule_exit_or_timeout"
                }
                same_side = str(previous_executed.get("side") or "") == str(row.get("side") or "")
                same_signal = str(previous_executed.get("signal_reason") or "") == str(row.get("signal_reason") or "")
                gap_units = entry_index(row) - exit_index(previous_executed)
                timeframe_factor = {"5m": 5.0, "15m": 15.0}.get(
                    str(row.get("timeframe") or "5m"), 1.0
                )
                gap_bars = gap_units / max(timeframe_factor, 1.0)
                observable_cluster = observable_signature_matches(row, cluster)
                if (
                    prior_loss
                    and prior_stop
                    and same_side
                    and same_signal
                    and 0 <= gap_bars <= cooldown_bars
                    and observable_cluster
                ):
                    block = True
                    reason = "LOSS_STOP_SAME_STATE_REENTRY_WITHIN_2_BARS"
            if block:
                blocked.append({
                    **row,
                    "blocked_by": EXPECTED_AXIS,
                    "block_reason": reason,
                    "cooldown_bars": cooldown_bars,
                    "future_exit_reason_used": False,
                    "prior_trade_net_r": net_r(previous_executed or {}),
                    "prior_trade_exit_reason": str((previous_executed or {}).get("exit_reason") or ""),
                    "gap_bars": (
                        entry_index(row) - exit_index(previous_executed or {})
                    ) / max(
                        {"5m": 5.0, "15m": 15.0}.get(
                            str(row.get("timeframe") or "5m"), 1.0
                        ),
                        1.0,
                    ),
                })
                # A blocked signal does not become state for another cooldown.
                continue
            kept.append(row)
            previous_executed = row
    return kept, blocked


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def positive_fold_count(rows: list[dict[str, Any]]) -> int:
    totals: dict[int, float] = defaultdict(float)
    for row in rows:
        totals[fold_id(row)] += net_r(row)
    return sum(value > 0 for value in totals.values())


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=event_order_key)
    r_values = [net_r(row) for row in ordered]
    pnl_values = [net_pnl_pct(row) for row in ordered]
    wins = [value for value in r_values if value > 0]
    losses = [-value for value in r_values if value < 0]
    gross_win = sum(wins)
    gross_loss = sum(losses)
    average_win = statistics.mean(wins) if wins else 0.0
    average_loss = statistics.mean(losses) if losses else 0.0
    return {
        "trade_count": len(rows),
        "symbol_count": len({str(row.get("symbol") or "") for row in rows}),
        "fold_count": len({fold_id(row) for row in rows}),
        "positive_fold_count": positive_fold_count(rows),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(rows) * 100.0 if rows else 0.0,
        "net_r_sum": sum(r_values),
        "net_pnl_sum_pct": sum(pnl_values),
        "expectancy_r": statistics.mean(r_values) if r_values else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss > EPS else (math.inf if gross_win > 0 else 0.0),
        "average_win_r": average_win,
        "average_loss_r": average_loss,
        "payoff_ratio": average_win / average_loss if average_loss > EPS else (math.inf if average_win > 0 else 0.0),
        "max_drawdown_r": max_drawdown(r_values),
        "max_drawdown_pct": max_drawdown(pnl_values),
        "median_holding_bars": statistics.median(
            [finite(row.get("holding_bars")) for row in rows]
        ) if rows else 0.0,
        "symbol_histogram": dict(sorted(Counter(str(row.get("symbol") or "") for row in rows).items())),
        "regime_histogram": dict(sorted(Counter(str(row.get("regime") or "") for row in rows).items())),
        "side_histogram": dict(sorted(Counter(str(row.get("side") or "") for row in rows).items())),
        "exit_histogram": dict(sorted(Counter(str(row.get("exit_reason") or "") for row in rows).items())),
    }


def profile_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        profile: metrics([row for row in rows if profile_name(row) == profile])
        for profile in ("base", "adverse", "severe")
    }


def cell_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[cell_key(row)].append(row)
    return [
        {
            "cost_profile_id": key[0],
            "timing_id": key[1],
            "profile": profile_name(bucket[0]) if bucket else "other",
            "metrics": metrics(bucket),
        }
        for key, bucket in sorted(buckets.items())
    ]


def ge(candidate: float, parent: float, tolerance: float = EPS) -> bool:
    return candidate + tolerance >= parent


def compare_profiles(
    parent: dict[str, Any],
    candidate: dict[str, Any],
    blocked_count: int,
) -> dict[str, Any]:
    base_parent = parent["base"]
    base_candidate = candidate["base"]
    adverse_parent = parent["adverse"]
    adverse_candidate = candidate["adverse"]
    severe_parent = parent["severe"]
    severe_candidate = candidate["severe"]

    baseline_non_degrade = (
        ge(base_candidate["net_r_sum"], base_parent["net_r_sum"])
        and ge(base_candidate["expectancy_r"], base_parent["expectancy_r"])
        and ge(base_candidate["profit_factor"], base_parent["profit_factor"])
        and base_candidate["max_drawdown_r"] <= base_parent["max_drawdown_r"] + EPS
    )
    adverse_non_degrade = (
        ge(adverse_candidate["net_r_sum"], adverse_parent["net_r_sum"])
        and ge(adverse_candidate["expectancy_r"], adverse_parent["expectancy_r"])
        and ge(adverse_candidate["profit_factor"], adverse_parent["profit_factor"])
        and adverse_candidate["max_drawdown_r"] <= adverse_parent["max_drawdown_r"] + EPS
    )
    severe_non_degrade = (
        ge(severe_candidate["net_r_sum"], severe_parent["net_r_sum"])
        and ge(severe_candidate["expectancy_r"], severe_parent["expectancy_r"])
        and ge(severe_candidate["profit_factor"], severe_parent["profit_factor"])
        and severe_candidate["max_drawdown_r"] <= severe_parent["max_drawdown_r"] + EPS
    )
    defect_improved = blocked_count > 0 and (
        candidate["base"]["net_r_sum"]
        + candidate["adverse"]["net_r_sum"]
        + candidate["severe"]["net_r_sum"]
        >
        parent["base"]["net_r_sum"]
        + parent["adverse"]["net_r_sum"]
        + parent["severe"]["net_r_sum"]
        + EPS
    )
    sample_gate = (
        base_candidate["trade_count"] >= MIN_TRADES
        and base_candidate["symbol_count"] >= MIN_SYMBOLS
    )
    walk_forward_gate = (
        base_candidate["positive_fold_count"] >= MIN_POSITIVE_FOLDS
    )
    repair_pass = (
        baseline_non_degrade
        and adverse_non_degrade
        and severe_non_degrade
        and defect_improved
        and sample_gate
        and walk_forward_gate
    )
    meaningful_severe = (
        severe_candidate["net_pnl_sum_pct"] >= MEANINGFUL_SEVERE_MIN_PNL_PCT
        and severe_candidate["profit_factor"] >= MEANINGFUL_SEVERE_MIN_PROFIT_FACTOR
        and severe_candidate["positive_fold_count"] >= MIN_POSITIVE_FOLDS
    )
    robust_survivor = (
        repair_pass
        and candidate["base"]["net_pnl_sum_pct"] > 0
        and candidate["adverse"]["net_pnl_sum_pct"] > 0
        and candidate["severe"]["net_pnl_sum_pct"] > 0
        and candidate["base"]["profit_factor"] > 1.0
        and candidate["adverse"]["profit_factor"] > 1.0
        and meaningful_severe
    )
    return {
        "baseline_non_degrade": baseline_non_degrade,
        "adverse_non_degrade": adverse_non_degrade,
        "severe_non_degrade": severe_non_degrade,
        "defect_improved": defect_improved,
        "sample_gate": sample_gate,
        "walk_forward_gate": walk_forward_gate,
        "meaningful_severe": meaningful_severe,
        "repair_pass": repair_pass,
        "robust_survivor": robust_survivor,
    }


def self_test() -> int:
    base = {
        "lane_id": LANE_ID,
        "cost_profile_id": "cost_profile_0",
        "timing_id": "timing_0",
        "profile": "base",
        "fold": 0,
        "symbol": "BTCUSDT",
        "side": "short",
        "signal_reason": "ma5_accel_15m_alignment",
        "regime": "shock_recovery",
        "risk_pct": 1.0,
        "timeframe": "5m",
    }
    rows = [
        {**base, "entry_source_index": 10, "exit_source_index": 20, "net_r": -1.0, "exit_reason": "stop"},
        # One 5m bar later: must be blocked even though its future exit is a take profit.
        {**base, "entry_source_index": 25, "exit_source_index": 35, "net_r": 2.0, "exit_reason": "take_profit"},
        # More than two 5m bars later, must remain.
        {**base, "entry_source_index": 50, "exit_source_index": 55, "net_r": 1.0, "exit_reason": "take_profit"},
        # Different regime, must remain.
        {**base, "entry_source_index": 22, "exit_source_index": 23, "net_r": -0.2, "exit_reason": "stop", "regime": "trend_up"},
    ]
    cluster = {
        "axes": ["regime", "side", "signal_reason", "exit_reason"],
        "values": ["shock_recovery", "short", "ma5_accel_15m_alignment", "stop"],
    }
    kept, blocked = apply_state_reset_cooldown(rows, cluster)
    assert len(kept) == 3
    assert len(blocked) == 1
    assert blocked[0]["entry_source_index"] == 25
    assert blocked[0]["future_exit_reason_used"] is False
    assert all(row["entry_source_index"] != 25 for row in kept)
    print("STATE=PASS_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    required = [
        root / AUDIT_PATH,
        root / SECOND_SUMMARY_PATH,
        root / SECOND_TRADES_PATH,
        root / DEFECT2_SUMMARY_PATH,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    before = snapshot(required)
    audit = load_json(root / AUDIT_PATH)
    second_summary = load_json(root / SECOND_SUMMARY_PATH)
    defect2_summary = load_json(root / DEFECT2_SUMMARY_PATH)
    trades = load_jsonl(root / SECOND_TRADES_PATH)
    blockers: list[str] = []

    if audit.get("state") != "PASS_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT":
        blockers.append("DEFECT3B_AUDIT_NOT_PASS")
    selected = list(audit.get("selected_payoff_repair_rows") or [])
    if len(selected) != 1:
        blockers.append(f"EXPECTED_ONE_SELECTED_REPAIR:{len(selected)}")
    selected_row = selected[0] if selected else {}
    if selected_row.get("lane_id") != LANE_ID:
        blockers.append("SELECTED_LANE_CHANGED")
    if selected_row.get("repair_axis") != EXPECTED_AXIS:
        blockers.append("SELECTED_AXIS_CHANGED")
    if selected_row.get("mechanism") != EXPECTED_MECHANISM:
        blockers.append("SELECTED_MECHANISM_CHANGED")
    if not bool(selected_row.get("repair_executable")):
        blockers.append("SELECTED_REPAIR_NOT_EXECUTABLE")
    if second_summary.get("state") != "PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132":
        blockers.append("SECOND_WAVE_SUMMARY_NOT_PASS")
    if defect2_summary.get("state") != "PASS_INCREMENTAL_DEFECT2_EXECUTION":
        blockers.append("DEFECT2_SUMMARY_NOT_PASS")
    if not bool(defect2_summary.get("atr5_control_preserved")):
        blockers.append("ATR5_PARENT_NOT_PRESERVED")
    if not bool(defect2_summary.get("donchian15_reference_preserved")):
        blockers.append("DONCHIAN15_REFERENCE_NOT_PRESERVED")
    if not bool(defect2_summary.get("keep14_untouched")):
        blockers.append("KEEP14_NOT_PRESERVED")

    parent_rows = [row for row in trades if str(row.get("lane_id") or "") == LANE_ID]
    cells = {cell_key(row) for row in parent_rows}
    if len(cells) != 6:
        blockers.append(f"EXPECTED_SIX_STRESS_CELLS:{len(cells)}")
    if not parent_rows:
        blockers.append("MA5_PARENT_ROWS_MISSING")

    if blockers:
        print("STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    child_rows, blocked_rows = apply_state_reset_cooldown(
        parent_rows, dict(selected_row.get("cluster") or {})
    )
    parent_profiles = profile_metrics(parent_rows)
    child_profiles = profile_metrics(child_rows)
    pass_checks = compare_profiles(parent_profiles, child_profiles, len(blocked_rows))

    parent_cell_rows = cell_metrics(parent_rows)
    child_cell_rows = cell_metrics(child_rows)
    child_by_key = {
        (row["cost_profile_id"], row["timing_id"]): row for row in child_cell_rows
    }
    comparison_cells: list[dict[str, Any]] = []
    for parent_cell in parent_cell_rows:
        key = (parent_cell["cost_profile_id"], parent_cell["timing_id"])
        comparison_cells.append({
            "cost_profile_id": key[0],
            "timing_id": key[1],
            "profile": parent_cell["profile"],
            "parent_metrics": parent_cell["metrics"],
            "child_metrics": child_by_key.get(
                key,
                {
                    "metrics": metrics([]),
                },
            )["metrics"],
        })

    next_stage = (
        "R7.A4D2_MA5_ROBUST_CHILD_FREEZE_AND_INDEPENDENT_DATA_EXPANSION"
        if pass_checks["robust_survivor"]
        else (
            "R7.A4D2_INCREMENTAL_DEFECT4_PAYOFF_AUDIT"
            if pass_checks["repair_pass"]
            else "R7.A4D2_MA5_PARENT_PRESERVE_AND_ORTHOGONAL_REPLACEMENT_DECISION"
        )
    )
    summary = {
        "state": "PASS_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6",
        "target_sha": args.target_sha,
        "lane_id": LANE_ID,
        "parent_source": "SECOND_WAVE_CONTROL",
        "parent_variant_id": "ma5_accel_15m_alignment",
        "child_variant_id": "ma5_state_reset_cooldown_2bar",
        "repair_axis": EXPECTED_AXIS,
        "repair_mechanism": EXPECTED_MECHANISM,
        "repair_rule": {
            "prior_trade_loss_required": True,
            "prior_exit_stop_required": True,
            "same_symbol_required": True,
            "same_side_required": True,
            "same_signal_reason_required": True,
            "current_regime": "shock_recovery",
            "current_side": "short",
            "current_signal_reason": "ma5_accel_15m_alignment",
            "maximum_gap_bars": COOLDOWN_BARS,
            "current_exit_reason_used": False,
        },
        "future_leakage_avoided": True,
        "stress_cell_count": len(cells),
        "parent_trade_count": len(parent_rows),
        "child_trade_count": len(child_rows),
        "blocked_entry_count": len(blocked_rows),
        "parent_profile_metrics": parent_profiles,
        "child_profile_metrics": child_profiles,
        "cell_comparison_rows": comparison_cells,
        "pass_checks": pass_checks,
        "incremental_pass": bool(pass_checks["repair_pass"]),
        "robust_survivor": bool(pass_checks["robust_survivor"]),
        "atr5_robust_parent_preserved": True,
        "atr15_incremental_parent_preserved": True,
        "ma5_second_wave_parent_preserved": True,
        "donchian15_reference_preserved": True,
        "keep14_untouched": True,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "mutation_rows": [],
        "next_stage": next_stage,
    }

    output = root / OUTPUT_DIR
    atomic_json(output / "incremental_defect3b_single_axis_payoff_summary_v1.json", summary)
    atomic_jsonl(output / "incremental_defect3b_child_trade_rows_v1.jsonl", child_rows)
    atomic_jsonl(output / "incremental_defect3b_blocked_entry_rows_v1.jsonl", blocked_rows)
    atomic_jsonl(output / "incremental_defect3b_cell_comparison_rows_v1.jsonl", comparison_cells)

    after = snapshot(required)
    mutations = [path for path in before if before[path] != after.get(path)]
    if mutations:
        print("STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps([f"INPUT_MUTATIONS:{len(mutations)}"]))
        print("RC=2")
        return 2

    print("STATE=PASS_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6")
    print("BLOCKER_COUNT=0")
    print("LANE_ID=" + LANE_ID)
    print("REPAIR_AXIS=" + EXPECTED_AXIS)
    print("FUTURE_LEAKAGE_AVOIDED=true")
    print("STRESS_CELL_COUNT=" + str(len(cells)))
    print("PARENT_TRADE_COUNT=" + str(len(parent_rows)))
    print("CHILD_TRADE_COUNT=" + str(len(child_rows)))
    print("BLOCKED_ENTRY_COUNT=" + str(len(blocked_rows)))
    print("INCREMENTAL_PASS=" + str(bool(pass_checks["repair_pass"])).lower())
    print("ROBUST_SURVIVOR=" + str(bool(pass_checks["robust_survivor"])).lower())
    print("PASS_CHECKS=" + json.dumps(pass_checks, sort_keys=True))
    print("PARENT_PROFILE_METRICS=" + json.dumps(parent_profiles, sort_keys=True))
    print("CHILD_PROFILE_METRICS=" + json.dumps(child_profiles, sort_keys=True))
    print("SUMMARY_JSON=" + str(output / "incremental_defect3b_single_axis_payoff_summary_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
