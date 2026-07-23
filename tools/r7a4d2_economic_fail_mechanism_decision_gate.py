#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

INPUT = Path("runtime/r7a4d2_economic_fail_all_loss_mechanism_audit/economic_fail_all_loss_mechanism_audit_summary_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_economic_fail_mechanism_decision_gate")
OUTPUT = OUTPUT_DIR / "economic_fail_mechanism_decision_gate_v1.json"

EXPECTED_STATE = "PASS_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT"
EXPECTED_CANDIDATES = 4
EXPECTED_COMMON_FAILURE = "NO_FAVORABLE_EXCURSION"
EXPECTED_SELECTED_LANE = "dual_atr_volatility_bot:15m"
EXPECTED_SELECTED_VARIANT = "atr15_persistence_5m_trigger"
EXPECTED_SELECTED_ACTION = "SIDE_SPECIALIZATION_CHILD_AUDIT"
EPS = 1e-12


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


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


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def rank_key(row: dict[str, Any]) -> tuple[float, float, float, float, float, str]:
    metrics = row.get("base_primary_metrics") if isinstance(row.get("base_primary_metrics"), dict) else {}
    gross_r = finite(metrics.get("gross_r_sum"), -math.inf)
    net_r = finite(metrics.get("net_r_sum"), -math.inf)
    pf = finite(metrics.get("profit_factor"), 0.0)
    drag_r = finite(metrics.get("execution_drag_r_sum"), math.inf)
    event_count = int(row.get("base_primary_event_count") or 0)
    action = str(row.get("evidence_action") or "")
    action_priority = {
        "SIDE_SPECIALIZATION_CHILD_AUDIT": 4.0,
        "REGIME_SPECIALIST_CHILD_AUDIT": 3.0,
        "COST_TURNOVER_ARCHITECTURE_AUDIT": 2.0,
        "EXIT_STATE_MACHINE_CHILD_AUDIT": 1.0,
    }.get(action, 0.0)
    recoverable_gross = 1.0 if gross_r > 0 else 0.0
    drag_ratio = drag_r / max(abs(gross_r), EPS) if math.isfinite(drag_r) else math.inf
    return (
        recoverable_gross,
        pf,
        net_r,
        action_priority,
        -drag_ratio,
        f"{event_count:08d}:{row.get('lane_id')}|{row.get('variant_id')}",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source_path = root / INPUT
    if not source_path.is_file():
        print("STATE=HOLD_ECONOMIC_FAIL_MECHANISM_DECISION_GATE_INPUT")
        print('BLOCKERS=["MECHANISM_AUDIT_SUMMARY_MISSING"]')
        print("RC=2")
        return 2

    before_sha = sha256_file(source_path)
    source = load_json(source_path)
    blockers: list[str] = []

    if source.get("state") != EXPECTED_STATE:
        blockers.append("MECHANISM_AUDIT_STATE_NOT_PASS")
    if int(source.get("blocker_count") or 0) != 0:
        blockers.append("MECHANISM_AUDIT_BLOCKED")
    if int(source.get("economic_fail_candidate_count") or -1) != EXPECTED_CANDIDATES:
        blockers.append("ECONOMIC_FAIL_CANDIDATE_COUNT_CHANGED")
    if str(source.get("common_failure_mode") or "") != EXPECTED_COMMON_FAILURE:
        blockers.append("COMMON_FAILURE_MODE_CHANGED")
    if int(source.get("mutation_path_count") or 0) != 0:
        blockers.append("MECHANISM_AUDIT_INPUT_MUTATION_DETECTED")
    if bool(source.get("blind_redesign_allowed")):
        blockers.append("BLIND_REDESIGN_UNEXPECTEDLY_ALLOWED")

    rows = [row for row in source.get("candidate_audits", []) if isinstance(row, dict)]
    if len(rows) != EXPECTED_CANDIDATES:
        blockers.append("CANDIDATE_AUDIT_ROWS_INVALID")

    eligible = [
        row for row in rows
        if bool(row.get("single_axis_redesign_allowed"))
        and str(row.get("evidence_action") or "") in {
            "SIDE_SPECIALIZATION_CHILD_AUDIT",
            "REGIME_SPECIALIST_CHILD_AUDIT",
            "COST_TURNOVER_ARCHITECTURE_AUDIT",
            "EXIT_STATE_MACHINE_CHILD_AUDIT",
        }
    ]
    if len(eligible) != EXPECTED_CANDIDATES:
        blockers.append(f"ELIGIBLE_SINGLE_AXIS_COUNT_INVALID:{len(eligible)}")

    selected = max(eligible, key=rank_key) if eligible else None
    if not selected:
        blockers.append("NO_SINGLE_AXIS_SELECTION")
    else:
        if str(selected.get("lane_id")) != EXPECTED_SELECTED_LANE:
            blockers.append("SELECTED_LANE_DRIFT")
        if str(selected.get("variant_id")) != EXPECTED_SELECTED_VARIANT:
            blockers.append("SELECTED_VARIANT_DRIFT")
        if str(selected.get("evidence_action")) != EXPECTED_SELECTED_ACTION:
            blockers.append("SELECTED_ACTION_DRIFT")
        metrics = selected.get("base_primary_metrics") if isinstance(selected.get("base_primary_metrics"), dict) else {}
        if finite(metrics.get("gross_r_sum")) <= 0:
            blockers.append("SELECTED_GROSS_EDGE_NOT_POSITIVE")
        if finite(metrics.get("net_r_sum")) >= 0:
            blockers.append("SELECTED_ALREADY_NET_POSITIVE")
        positive_sides = [row for row in selected.get("positive_side_partitions", []) if isinstance(row, dict)]
        if not positive_sides:
            blockers.append("SELECTED_POSITIVE_SIDE_PARTITION_MISSING")

    after_sha = sha256_file(source_path)
    if before_sha != after_sha:
        blockers.append("READ_ONLY_SOURCE_MUTATION")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        print("STATE=HOLD_ECONOMIC_FAIL_MECHANISM_DECISION_GATE")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    assert selected is not None
    selected_metrics = selected["base_primary_metrics"]
    positive_sides = sorted(
        [row for row in selected.get("positive_side_partitions", []) if isinstance(row, dict)],
        key=lambda row: (finite(row.get("net_r_sum")), int(row.get("event_count") or 0), str(row.get("value") or "")),
        reverse=True,
    )
    selected_side = positive_sides[0]

    queue: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda candidate: str(candidate.get("candidate_key") or "")):
        metrics = row.get("base_primary_metrics") if isinstance(row.get("base_primary_metrics"), dict) else {}
        key = f"{row.get('lane_id')}|{row.get('variant_id')}"
        if row is selected:
            disposition = "SELECTED_SINGLE_AXIS_CHILD_AUDIT"
            reason = "BEST_RECOVERABLE_GROSS_EDGE_HIGHEST_PF_CLOSEST_TO_NET_BREAKEVEN_WITH_POSITIVE_SIDE_PARTITION"
        elif finite(metrics.get("gross_r_sum")) <= 0:
            disposition = "ARCHITECTURE_REJECT"
            reason = "BASE_GROSS_EDGE_NON_POSITIVE"
        else:
            disposition = "DEFERRED_REDUNDANT_MECHANISM"
            reason = "ONE_REPRESENTATIVE_ONLY_UNTIL_SELECTED_CHILD_NEW_OOS_RESULT"
        queue.append({
            "candidate_key": key,
            "lane_id": row.get("lane_id"),
            "variant_id": row.get("variant_id"),
            "evidence_action": row.get("evidence_action"),
            "dominant_loss_mechanism": row.get("dominant_loss_mechanism"),
            "gross_r_sum": finite(metrics.get("gross_r_sum")),
            "execution_drag_r_sum": finite(metrics.get("execution_drag_r_sum")),
            "net_r_sum": finite(metrics.get("net_r_sum")),
            "profit_factor": finite(metrics.get("profit_factor")),
            "mfe_r_median": finite(metrics.get("mfe_r_median")),
            "mae_r_median": finite(metrics.get("mae_r_median")),
            "disposition": disposition,
            "reason": reason,
        })

    output = {
        "schema": "r7a4d2_economic_fail_mechanism_decision_gate_v1",
        "official_stage": "R7.A4D2_ECONOMIC_FAIL_MECHANISM_DECISION_GATE",
        "state": "PASS_ECONOMIC_FAIL_MECHANISM_DECISION_GATE",
        "target_commit": args.target_sha,
        "source_summary_path": str(INPUT),
        "common_failure_mode": source.get("common_failure_mode"),
        "decision_policy": "ONE_REPRESENTATIVE_SINGLE_AXIS_CHILD_ONLY_NO_PARALLEL_REDESIGN",
        "selected_candidate": {
            "lane_id": selected.get("lane_id"),
            "variant_id": selected.get("variant_id"),
            "parent_immutable": True,
            "child_audit_type": selected.get("evidence_action"),
            "selected_side": selected_side.get("value"),
            "selected_side_event_count": int(selected_side.get("event_count") or 0),
            "selected_side_gross_r_sum": finite(selected_side.get("gross_r_sum")),
            "selected_side_execution_drag_r_sum": finite(selected_side.get("execution_drag_r_sum")),
            "selected_side_net_r_sum": finite(selected_side.get("net_r_sum")),
            "selected_side_profit_factor": finite(selected_side.get("profit_factor")),
            "parent_base_event_count": int(selected.get("base_primary_event_count") or 0),
            "parent_gross_r_sum": finite(selected_metrics.get("gross_r_sum")),
            "parent_execution_drag_r_sum": finite(selected_metrics.get("execution_drag_r_sum")),
            "parent_net_r_sum": finite(selected_metrics.get("net_r_sum")),
            "parent_profit_factor": finite(selected_metrics.get("profit_factor")),
            "parent_mfe_r_median": finite(selected_metrics.get("mfe_r_median")),
            "parent_mae_r_median": finite(selected_metrics.get("mae_r_median")),
        },
        "candidate_dispositions": queue,
        "parallel_redesign_allowed": False,
        "blind_redesign_allowed": False,
        "parameter_optimization_allowed": False,
        "threshold_relaxation_allowed": False,
        "stop_target_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "input_mutation_count": 0,
        "next_stage": "R7.A4D2_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT",
        "blockers": [],
    }
    atomic_json(root / OUTPUT, output)

    print("STATE=PASS_ECONOMIC_FAIL_MECHANISM_DECISION_GATE")
    print("BLOCKER_COUNT=0")
    print("COMMON_FAILURE_MODE=" + str(source.get("common_failure_mode")))
    print("SELECTED_LANE=" + str(selected.get("lane_id")))
    print("SELECTED_VARIANT=" + str(selected.get("variant_id")))
    print("SELECTED_ACTION=" + str(selected.get("evidence_action")))
    print("SELECTED_SIDE=" + str(selected_side.get("value")))
    print("SELECTED_SIDE_EVENTS=" + str(int(selected_side.get("event_count") or 0)))
    print("SELECTED_SIDE_NET_R=" + f"{finite(selected_side.get('net_r_sum')):.12f}")
    print("SELECTED_SIDE_PF=" + f"{finite(selected_side.get('profit_factor')):.12f}")
    print("PARENT_GROSS_R=" + f"{finite(selected_metrics.get('gross_r_sum')):.12f}")
    print("PARENT_DRAG_R=" + f"{finite(selected_metrics.get('execution_drag_r_sum')):.12f}")
    print("PARENT_NET_R=" + f"{finite(selected_metrics.get('net_r_sum')):.12f}")
    print("PARENT_PF=" + f"{finite(selected_metrics.get('profit_factor')):.12f}")
    print("PARALLEL_REDESIGN_ALLOWED=false")
    for row in queue:
        print(
            "DECISION_RESULT="
            f"{row['lane_id']}|{row['variant_id']}|DISPOSITION={row['disposition']}|"
            f"GROSS_R={row['gross_r_sum']:.6f}|DRAG_R={row['execution_drag_r_sum']:.6f}|"
            f"NET_R={row['net_r_sum']:.6f}|PF={row['profit_factor']:.6f}|REASON={row['reason']}"
        )
    print("SUMMARY_JSON=" + str(root / OUTPUT))
    print("INPUT_MUTATION_COUNT=0")
    print("NEXT_STAGE=R7.A4D2_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT")
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
