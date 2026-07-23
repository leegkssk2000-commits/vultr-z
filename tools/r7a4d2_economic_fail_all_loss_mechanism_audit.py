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
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

SEMANTIC = Path("runtime/r7a4d2_remaining_oos_batch_result_semantic_repair/remaining_oos_batch_semantic_repair_summary_v1.json")
BATCH_SUMMARY = Path("runtime/r7a4d2_remaining_survivor_independent_oos_batch_execution/remaining_survivor_independent_oos_batch_summary_v1.json")
TRADE_ROWS = Path("runtime/r7a4d2_remaining_survivor_independent_oos_batch_execution/remaining_oos_trade_rows_v1.jsonl")
CELL_ROWS = Path("runtime/r7a4d2_remaining_survivor_independent_oos_batch_execution/remaining_oos_cell_rows_v1.jsonl")
OUTPUT_DIR = Path("runtime/r7a4d2_economic_fail_all_loss_mechanism_audit")
SUMMARY_OUT = OUTPUT_DIR / "economic_fail_all_loss_mechanism_audit_summary_v1.json"
EVENTS_OUT = OUTPUT_DIR / "economic_fail_base_event_anatomy_v1.jsonl"
GROUPS_OUT = OUTPUT_DIR / "economic_fail_group_decomposition_v1.jsonl"

EXPECTED_ECONOMIC_FAILS = 4
EXPECTED_STRESS_CELLS = 6
EXPECTED_FOLDS = 6
BASE_COST = "cost_profile_0"
BASE_TIMING = "timing_0"
EPS = 1e-12
MFE_NONE_R = 0.25
MFE_CAPTURE_R = 0.75
DOMINANT_LOSS_SHARE = 0.50


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
            rows.append(value)
    return rows


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(paths: Iterable[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return count, digest.hexdigest()


def safe_relative_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_PATH:{value!r}")
    return pure.as_posix()


def source_rows(path: Path, expected_sha: str) -> list[list[float]]:
    actual_sha = sha256_file(path)
    if actual_sha != expected_sha:
        raise ValueError(f"SOURCE_SHA_MISMATCH:{path}:{actual_sha}:{expected_sha}")
    payload = load_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"SOURCE_ROWS_INVALID:{path}")
    parsed: list[list[float]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 6:
            raise ValueError(f"SOURCE_LAYOUT_INVALID:{path}:{index}")
        values = [finite(value, math.nan) for value in row]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"SOURCE_NUMERIC_INVALID:{path}:{index}")
        parsed.append(values)
    return parsed


def risk_scaled(row: dict[str, Any], field: str) -> float:
    risk = finite(row.get("risk_pct"))
    return finite(row.get(field)) / risk if risk > EPS else 0.0


def event_path_anatomy(row: dict[str, Any], market_rows: list[list[float]]) -> dict[str, Any]:
    entry_index = int(row.get("entry_source_index", -1))
    exit_index = int(row.get("exit_source_index", -1))
    if not (0 <= entry_index <= exit_index < len(market_rows)):
        raise ValueError(f"EVENT_SOURCE_RANGE_INVALID:{entry_index}:{exit_index}:{len(market_rows)}")

    side = str(row.get("side") or "")
    entry = finite(row.get("entry_price"), math.nan)
    stop = finite(row.get("stop_price"), math.nan)
    target = finite(row.get("target_price"), math.nan)
    risk_pct = finite(row.get("risk_pct"), math.nan)
    if side not in {"long", "short"} or not all(math.isfinite(value) for value in (entry, stop, target, risk_pct)):
        raise ValueError("EVENT_GEOMETRY_INVALID")
    if entry <= 0 or risk_pct <= 0:
        raise ValueError("EVENT_RISK_INVALID")

    first_hit = "NONE"
    first_hit_source_index: int | None = None
    path_end = exit_index
    for source_index in range(entry_index, exit_index + 1):
        _, _, high_v, low_v, _, _ = market_rows[source_index]
        if side == "long":
            stop_hit = low_v <= stop
            target_hit = high_v >= target
        else:
            stop_hit = high_v >= stop
            target_hit = low_v <= target
        if stop_hit and target_hit:
            first_hit = "AMBIGUOUS"
            first_hit_source_index = source_index
            path_end = source_index
            break
        if stop_hit:
            first_hit = "STOP"
            first_hit_source_index = source_index
            path_end = source_index
            break
        if target_hit:
            first_hit = "TARGET"
            first_hit_source_index = source_index
            path_end = source_index
            break

    sample = market_rows[entry_index:path_end + 1]
    highest = max(row_[2] for row_ in sample)
    lowest = min(row_[3] for row_ in sample)
    if side == "long":
        mfe_pct = max(0.0, (highest - entry) / entry * 100.0)
        mae_pct = max(0.0, (entry - lowest) / entry * 100.0)
        target_gross_pct = (target - entry) / entry * 100.0
    else:
        mfe_pct = max(0.0, (entry - lowest) / entry * 100.0)
        mae_pct = max(0.0, (highest - entry) / entry * 100.0)
        target_gross_pct = (entry - target) / entry * 100.0

    exit_reason = str(row.get("exit_reason") or "")
    if first_hit == "AMBIGUOUS":
        order_status = "SAME_1M_BAR_AMBIGUOUS"
    elif exit_reason == "stop" and first_hit == "TARGET":
        order_status = "TARGET_BEFORE_RECORDED_STOP"
    elif exit_reason == "take_profit" and first_hit == "STOP":
        order_status = "STOP_BEFORE_RECORDED_TARGET"
    elif exit_reason in {"rule_exit_or_timeout", "segment_end"} and first_hit in {"STOP", "TARGET"}:
        order_status = "BARRIER_HIT_BEFORE_RECORDED_RULE_EXIT"
    else:
        order_status = "CONSISTENT"

    gross_r = risk_scaled(row, "gross_return_pct")
    round_trip_cost_r = risk_scaled(row, "round_trip_cost_pct")
    funding_cost_r = risk_scaled(row, "funding_cost_pct")
    net_r = finite(row.get("net_r"))
    target_net_r = (target_gross_pct - finite(row.get("round_trip_cost_pct")) - finite(row.get("funding_cost_pct"))) / risk_pct

    return {
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "mfe_r": mfe_pct / risk_pct,
        "mae_r": mae_pct / risk_pct,
        "gross_r": gross_r,
        "round_trip_cost_r": round_trip_cost_r,
        "funding_cost_r": funding_cost_r,
        "execution_drag_r": round_trip_cost_r + funding_cost_r,
        "net_r": net_r,
        "target_net_r_counterfactual": target_net_r,
        "first_barrier_hit": first_hit,
        "first_barrier_source_index": first_hit_source_index,
        "order_status": order_status,
    }


def loss_mechanism(row: dict[str, Any]) -> str:
    if finite(row.get("net_r")) >= 0:
        return "NON_LOSS"
    status = str(row.get("order_status") or "")
    if status == "TARGET_BEFORE_RECORDED_STOP":
        return "EXECUTION_ORDER_BIAS"
    if status == "SAME_1M_BAR_AMBIGUOUS":
        return "INTRABAR_AMBIGUITY"
    if finite(row.get("gross_r")) > 0:
        return "COST_EROSION"
    if finite(row.get("mfe_r")) >= MFE_CAPTURE_R:
        return "EXIT_CAPTURE_FAILURE"
    if finite(row.get("mfe_r")) < MFE_NONE_R:
        return "NO_FAVORABLE_EXCURSION"
    if finite(row.get("mae_r")) >= 1.0 and finite(row.get("mfe_r")) < 0.5:
        return "ADVERSE_ENTRY_GEOMETRY"
    return "GROSS_LOSS_OTHER"


def basic_group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    net_values = [finite(row.get("net_r")) for row in rows]
    gross_values = [finite(row.get("gross_r")) for row in rows]
    drag_values = [finite(row.get("execution_drag_r")) for row in rows]
    wins = [value for value in net_values if value > 0]
    losses = [-value for value in net_values if value < 0]
    return {
        "event_count": len(rows),
        "gross_r_sum": sum(gross_values),
        "execution_drag_r_sum": sum(drag_values),
        "net_r_sum": sum(net_values),
        "profit_factor": sum(wins) / sum(losses) if sum(losses) > EPS else (math.inf if wins else 0.0),
        "win_count": len(wins),
        "loss_count": len(losses),
        "mfe_r_median": statistics.median([finite(row.get("mfe_r")) for row in rows]) if rows else 0.0,
        "mae_r_median": statistics.median([finite(row.get("mae_r")) for row in rows]) if rows else 0.0,
    }


def decompose(candidate_key: str, rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(field) or "UNKNOWN")].append(row)
    output: list[dict[str, Any]] = []
    for value, group in sorted(grouped.items()):
        output.append({
            "candidate_key": candidate_key,
            "dimension": field,
            "value": value,
            **basic_group_metrics(group),
        })
    return output


def dominant_mechanism(rows: list[dict[str, Any]]) -> tuple[str, float, dict[str, dict[str, float]]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"event_count": 0.0, "loss_r": 0.0})
    total_loss = 0.0
    for row in rows:
        if finite(row.get("net_r")) >= 0:
            continue
        mechanism = str(row.get("loss_mechanism") or "GROSS_LOSS_OTHER")
        loss = -finite(row.get("net_r"))
        totals[mechanism]["event_count"] += 1.0
        totals[mechanism]["loss_r"] += loss
        total_loss += loss
    if not totals:
        return "NONE", 0.0, {}
    dominant = max(totals, key=lambda key: totals[key]["loss_r"])
    share = totals[dominant]["loss_r"] / total_loss if total_loss > EPS else 0.0
    return dominant, share, dict(sorted(totals.items()))


def positive_partition(group_rows: list[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    return [row for row in group_rows if row.get("dimension") == dimension and finite(row.get("net_r_sum")) > 0 and int(row.get("event_count") or 0) >= 12]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    required = [root / SEMANTIC, root / BATCH_SUMMARY, root / TRADE_ROWS, root / CELL_ROWS]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT_INPUT")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    semantic = load_json(root / SEMANTIC)
    batch = load_json(root / BATCH_SUMMARY)
    trades = load_jsonl(root / TRADE_ROWS)
    cells = load_jsonl(root / CELL_ROWS)

    blockers: list[str] = []
    if semantic.get("state") != "PASS_REMAINING_OOS_BATCH_RESULT_SEMANTIC_REPAIR":
        blockers.append("SEMANTIC_REPAIR_NOT_PASS")
    if batch.get("state") != "PASS_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH":
        blockers.append("BATCH_NOT_PASS")
    if int(batch.get("mutation_path_count") or 0) != 0:
        blockers.append("BATCH_INPUT_MUTATION_DETECTED")

    economic_rows = [
        row for row in semantic.get("candidate_results", [])
        if isinstance(row, dict) and row.get("semantic_classification") == "ECONOMIC_FAIL"
    ]
    if len(economic_rows) != EXPECTED_ECONOMIC_FAILS:
        blockers.append(f"ECONOMIC_FAIL_COUNT_INVALID:{len(economic_rows)}")

    candidate_keys = {
        f"{row.get('lane_id')}|{row.get('variant_id')}": row for row in economic_rows
    }
    batch_rows = [row for row in batch.get("candidate_results", []) if isinstance(row, dict)]
    batch_map = {f"{row.get('lane_id')}|{row.get('variant_id')}": row for row in batch_rows}
    if set(candidate_keys) - set(batch_map):
        blockers.append("ECONOMIC_FAIL_BATCH_RESULT_MISSING")

    economic_trades = [
        row for row in trades
        if f"{row.get('lane_id')}|{row.get('variant_id')}" in candidate_keys
    ]
    economic_cells = [
        row for row in cells
        if f"{row.get('lane_id')}|{row.get('variant_id')}" in candidate_keys
    ]
    for key in sorted(candidate_keys):
        row = batch_map.get(key, {})
        if not bool(row.get("coverage_ready")):
            blockers.append(f"CANDIDATE_NOT_COVERAGE_READY:{key}")
        if int(row.get("stress_cell_count") or 0) != EXPECTED_STRESS_CELLS:
            blockers.append(f"CANDIDATE_CELL_COUNT_INVALID:{key}")
        if int(row.get("signal_fold_count") or 0) != EXPECTED_FOLDS:
            blockers.append(f"CANDIDATE_FOLD_COUNT_INVALID:{key}")
        if len([cell for cell in economic_cells if f"{cell.get('lane_id')}|{cell.get('variant_id')}" == key]) != EXPECTED_STRESS_CELLS:
            blockers.append(f"CELL_ROWS_MISSING:{key}")

    source_expectations: dict[str, str] = {}
    for row in economic_trades:
        source_path = safe_relative_path(str(row.get("source_path") or ""))
        source_sha = str(row.get("source_sha256") or "")
        if not source_sha:
            blockers.append("SOURCE_SHA_MISSING")
            continue
        previous = source_expectations.setdefault(source_path, source_sha)
        if previous != source_sha:
            blockers.append(f"SOURCE_SHA_CONFLICT:{source_path}")

    source_paths = [root / path for path in sorted(source_expectations)]
    if any(not path.is_file() for path in source_paths):
        blockers.append("MARKET_SOURCE_MISSING")

    input_paths = required + source_paths
    before = snapshot(input_paths)
    if blockers:
        blockers = list(dict.fromkeys(blockers))
        print("STATE=HOLD_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    market_cache: dict[str, list[list[float]]] = {}
    try:
        for relative, expected_sha in sorted(source_expectations.items()):
            market_cache[relative] = source_rows(root / relative, expected_sha)
    except Exception as exc:
        print("STATE=HOLD_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT_INTEGRITY")
        print("BLOCKERS=" + json.dumps([f"MARKET_SOURCE_LOAD_FAILED:{type(exc).__name__}:{exc}"]))
        print("RC=2")
        return 2

    event_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    candidate_audits: list[dict[str, Any]] = []
    anatomy_failures: list[str] = []

    for key in sorted(candidate_keys):
        lane_id, variant_id = key.split("|", 1)
        candidate_trade_rows = [
            row for row in economic_trades
            if str(row.get("lane_id")) == lane_id and str(row.get("variant_id")) == variant_id
        ]
        base_rows = [
            row for row in candidate_trade_rows
            if str(row.get("cost_profile_id")) == BASE_COST and str(row.get("timing_id")) == BASE_TIMING
        ]
        seen_events: set[str] = set()
        anatomy_rows: list[dict[str, Any]] = []
        for row in base_rows:
            event_id = str(row.get("event_id") or "")
            if not event_id or event_id in seen_events:
                continue
            seen_events.add(event_id)
            try:
                relative = safe_relative_path(str(row.get("source_path") or ""))
                anatomy = event_path_anatomy(row, market_cache[relative])
                enriched = {
                    "candidate_key": key,
                    "lane_id": lane_id,
                    "variant_id": variant_id,
                    "event_id": event_id,
                    "symbol": str(row.get("symbol") or ""),
                    "regime": str(row.get("regime") or ""),
                    "side": str(row.get("side") or ""),
                    "exit_reason": str(row.get("exit_reason") or ""),
                    "signal_reason": str(row.get("signal_reason") or ""),
                    "level_id": row.get("level_id"),
                    "fold": int(row.get("fold") or 0),
                    "holding_bars": int(row.get("holding_bars") or 0),
                    "risk_pct": finite(row.get("risk_pct")),
                    "entry_price": finite(row.get("entry_price")),
                    "stop_price": finite(row.get("stop_price")),
                    "target_price": finite(row.get("target_price")),
                    "source_path": relative,
                    "entry_source_index": int(row.get("entry_source_index", -1)),
                    "exit_source_index": int(row.get("exit_source_index", -1)),
                    **anatomy,
                }
                enriched["loss_mechanism"] = loss_mechanism(enriched)
                anatomy_rows.append(enriched)
                event_rows.append(enriched)
            except Exception as exc:
                anatomy_failures.append(f"{key}:{event_id}:{type(exc).__name__}:{exc}")

        if not anatomy_rows:
            anatomy_failures.append(f"{key}:BASE_EVENT_ANATOMY_ZERO")
            continue

        for dimension in ("side", "regime", "symbol", "exit_reason", "loss_mechanism"):
            group_rows.extend(decompose(key, anatomy_rows, dimension))

        candidate_groups = [row for row in group_rows if row.get("candidate_key") == key]
        base_metrics = basic_group_metrics(anatomy_rows)
        dominant, dominant_share, mechanism_totals = dominant_mechanism(anatomy_rows)
        target_first = [row for row in anatomy_rows if row.get("order_status") == "TARGET_BEFORE_RECORDED_STOP"]
        ambiguous = [row for row in anatomy_rows if row.get("order_status") == "SAME_1M_BAR_AMBIGUOUS"]
        corrected_net = base_metrics["net_r_sum"] + sum(
            finite(row.get("target_net_r_counterfactual")) - finite(row.get("net_r")) for row in target_first
        )
        ambiguity_upper = corrected_net + sum(
            max(0.0, finite(row.get("target_net_r_counterfactual")) - finite(row.get("net_r"))) for row in ambiguous
        )
        positive_sides = positive_partition(candidate_groups, "side")
        positive_regimes = positive_partition(candidate_groups, "regime")

        if corrected_net > 0:
            evidence_action = "EXECUTION_ORDER_MODEL_REPLAY"
            redesign_allowed = False
        elif positive_sides:
            evidence_action = "SIDE_SPECIALIZATION_CHILD_AUDIT"
            redesign_allowed = True
        elif positive_regimes:
            evidence_action = "REGIME_SPECIALIST_CHILD_AUDIT"
            redesign_allowed = True
        elif base_metrics["gross_r_sum"] > 0 and base_metrics["net_r_sum"] < 0:
            evidence_action = "COST_TURNOVER_ARCHITECTURE_AUDIT"
            redesign_allowed = True
        elif dominant == "EXIT_CAPTURE_FAILURE" and dominant_share >= DOMINANT_LOSS_SHARE:
            evidence_action = "EXIT_STATE_MACHINE_CHILD_AUDIT"
            redesign_allowed = True
        else:
            evidence_action = "ARCHITECTURE_REJECT_OR_CANONICAL25_DIRECT_REPLAY"
            redesign_allowed = False

        candidate_audits.append({
            "candidate_key": key,
            "lane_id": lane_id,
            "variant_id": variant_id,
            "base_primary_cell": {"cost_profile_id": BASE_COST, "timing_id": BASE_TIMING},
            "base_primary_event_count": len(anatomy_rows),
            "base_primary_metrics": base_metrics,
            "dominant_loss_mechanism": dominant,
            "dominant_loss_share": dominant_share,
            "loss_mechanism_totals": mechanism_totals,
            "target_before_recorded_stop_count": len(target_first),
            "same_1m_bar_ambiguous_count": len(ambiguous),
            "recorded_base_net_r": base_metrics["net_r_sum"],
            "target_first_corrected_base_net_r": corrected_net,
            "ambiguity_upper_bound_base_net_r": ambiguity_upper,
            "positive_side_partitions": positive_sides,
            "positive_regime_partitions": positive_regimes,
            "evidence_action": evidence_action,
            "single_axis_redesign_allowed": redesign_allowed,
            "blind_redesign_allowed": False,
        })

    after = snapshot(input_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    integrity_blockers: list[str] = []
    if anatomy_failures:
        integrity_blockers.append(f"EVENT_ANATOMY_FAILURES:{len(anatomy_failures)}")
    if len(candidate_audits) != EXPECTED_ECONOMIC_FAILS:
        integrity_blockers.append(f"CANDIDATE_AUDIT_COUNT_INVALID:{len(candidate_audits)}")
    if mutation_paths:
        integrity_blockers.append(f"INPUT_MUTATION:{len(mutation_paths)}")

    action_counts = dict(sorted(Counter(row["evidence_action"] for row in candidate_audits).items()))
    dominant_counts = dict(sorted(Counter(row["dominant_loss_mechanism"] for row in candidate_audits).items()))
    common_failure = max(dominant_counts, key=dominant_counts.get) if dominant_counts else "NONE"
    common_count = dominant_counts.get(common_failure, 0)
    common_failure_mode = common_failure if common_count >= 3 else "MIXED"
    redesign_queue = [
        {"lane_id": row["lane_id"], "variant_id": row["variant_id"], "action": row["evidence_action"]}
        for row in candidate_audits if row["single_axis_redesign_allowed"]
    ]

    state = "PASS_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT" if not integrity_blockers else "HOLD_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT_INTEGRITY"
    next_stage = (
        "R7.A4D2_ECONOMIC_FAIL_MECHANISM_DECISION_GATE"
        if not integrity_blockers else "R7.A4D2_ECONOMIC_FAIL_AUDIT_REPAIR"
    )
    output = root / OUTPUT_DIR
    event_count, event_sha = atomic_jsonl(output / EVENTS_OUT.name, event_rows)
    group_count, group_sha = atomic_jsonl(output / GROUPS_OUT.name, group_rows)
    summary = {
        "schema": "r7a4d2_economic_fail_all_loss_mechanism_audit_v1",
        "official_stage": "R7.A4D2_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(integrity_blockers),
        "blockers": integrity_blockers,
        "economic_fail_candidate_count": len(candidate_audits),
        "base_primary_cell": {"cost_profile_id": BASE_COST, "timing_id": BASE_TIMING},
        "diagnostic_thresholds": {
            "no_favorable_excursion_mfe_r": MFE_NONE_R,
            "exit_capture_failure_mfe_r": MFE_CAPTURE_R,
            "dominant_loss_share": DOMINANT_LOSS_SHARE,
        },
        "candidate_audits": candidate_audits,
        "common_failure_mode": common_failure_mode,
        "dominant_mechanism_counts": dominant_counts,
        "evidence_action_counts": action_counts,
        "single_axis_redesign_queue": redesign_queue,
        "event_row_count": event_count,
        "event_sha256": event_sha,
        "group_row_count": group_count,
        "group_sha256": group_sha,
        "anatomy_failures": anatomy_failures[:100],
        "mutation_path_count": len(mutation_paths),
        "mutation_paths": mutation_paths,
        "blind_redesign_allowed": False,
        "parameter_optimization_allowed": False,
        "threshold_relaxation_allowed": False,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": next_stage,
    }
    atomic_json(output / SUMMARY_OUT.name, summary)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(integrity_blockers)))
    print("ECONOMIC_FAIL_CANDIDATE_COUNT=" + str(len(candidate_audits)))
    print("COMMON_FAILURE_MODE=" + common_failure_mode)
    print("SINGLE_AXIS_REDESIGN_QUEUE_COUNT=" + str(len(redesign_queue)))
    for row in candidate_audits:
        metrics = row["base_primary_metrics"]
        print(
            "MECHANISM_RESULT="
            f"{row['lane_id']}|{row['variant_id']}|PRIMARY={row['dominant_loss_mechanism']}|"
            f"SHARE={row['dominant_loss_share']:.6f}|EVENTS={row['base_primary_event_count']}|"
            f"GROSS_R={metrics['gross_r_sum']:.6f}|DRAG_R={metrics['execution_drag_r_sum']:.6f}|"
            f"NET_R={metrics['net_r_sum']:.6f}|PF={metrics['profit_factor']:.6f}|"
            f"MFE_MED_R={metrics['mfe_r_median']:.6f}|MAE_MED_R={metrics['mae_r_median']:.6f}|"
            f"TARGET_FIRST={row['target_before_recorded_stop_count']}|AMBIG_1M={row['same_1m_bar_ambiguous_count']}|"
            f"CORRECTED_NET_R={row['target_first_corrected_base_net_r']:.6f}|"
            f"ACTION={row['evidence_action']}|REDESIGN={str(row['single_axis_redesign_allowed']).lower()}"
        )
    print("EVENT_ROWS_JSONL=" + str(output / EVENTS_OUT.name))
    print("GROUP_ROWS_JSONL=" + str(output / GROUPS_OUT.name))
    print("SUMMARY_JSON=" + str(output / SUMMARY_OUT.name))
    print("MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(integrity_blockers))
    print("RC=" + ("0" if not integrity_blockers else "2"))
    return 0 if not integrity_blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
