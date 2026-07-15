#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

UTC = timezone.utc
CANARY_TARGET = 20
COVERAGE_EVENT_TYPES = {"skill_triggered", "skill_blocked"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.exists():
        return rows, [{"line": 0, "error": "FILE_MISSING"}]
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except Exception as exc:
            errors.append({"line": line_no, "error": f"{type(exc).__name__}:{exc}"})
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            errors.append({"line": line_no, "error": "ROW_NOT_OBJECT"})
    return rows, errors


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def position_id(row: Mapping[str, Any]) -> str:
    for key in ("position_id", "positionId", "trade_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def issue(code: str, severity: str, detail: str, position: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "detail": detail,
        "action": "hold",
    }
    if position:
        value["position_id"] = position
    return value


def evaluate(
    *,
    activation: Mapping[str, Any],
    formal_rows: list[dict[str, Any]],
    formal_errors: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    event_errors: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    baseline_formal = int(activation.get("baseline_formal_ledger_rows") or 0)
    baseline_events = int(activation.get("baseline_skill_event_rows") or 0)
    known_prior_gap_count = int(activation.get("known_prior_gap_count") or 0)

    if activation.get("schema") != "q4r3_exact25_lineage_cadence_repair_activation_v1":
        issues.append(issue("REPAIR_ACTIVATION_SCHEMA_INVALID", "C", str(activation.get("schema"))))
    if activation.get("historical_backfill_allowed") is not False:
        issues.append(issue("UNSAFE_HISTORICAL_BACKFILL_FLAG", "C", str(activation.get("historical_backfill_allowed"))))
    if activation.get("root_cause") != "MISSED_OPEN_WINDOW_NO_OBSERVER_TICK":
        issues.append(issue("ROOT_CAUSE_NOT_PINNED", "C", str(activation.get("root_cause"))))
    if baseline_formal > len(formal_rows):
        issues.append(issue("FORMAL_LEDGER_TRUNCATED_BELOW_REPAIR_BASELINE", "C", f"baseline={baseline_formal}:current={len(formal_rows)}"))
    if baseline_events > len(event_rows):
        issues.append(issue("SKILL_EVENT_LEDGER_TRUNCATED_BELOW_REPAIR_BASELINE", "C", f"baseline={baseline_events}:current={len(event_rows)}"))

    for error in formal_errors:
        issues.append(issue("FORMAL_LEDGER_PARSE_ERROR", "C", f"line={error['line']}:{error['error']}"))
    for error in event_errors:
        issues.append(issue("SKILL_EVENT_PARSE_ERROR", "C", f"line={error['line']}:{error['error']}"))

    post_formal = formal_rows[baseline_formal:]
    post_events = event_rows[baseline_events:]

    duplicate_event_ids = [
        value for value, count in Counter(str(row.get("event_id") or "") for row in post_events if row.get("event_id")).items() if count > 1
    ]
    for value in duplicate_event_ids:
        issues.append(issue("DUPLICATE_POST_REPAIR_SKILL_EVENT_ID", "C", value))

    events_by_position: defaultdict[str, set[str]] = defaultdict(set)
    for row in event_rows:
        pid = position_id(row)
        if pid:
            events_by_position[pid].add(str(row.get("event_type") or ""))

    uncovered: list[str] = []
    covered = 0
    eligible = 0
    for row in post_formal:
        pid = position_id(row)
        if not pid:
            issues.append(issue("POST_REPAIR_CLOSE_POSITION_ID_MISSING", "C", str(row.get("event_id"))))
            continue
        eligible += 1
        event_types = events_by_position.get(pid, set())
        if event_types.intersection(COVERAGE_EVENT_TYPES):
            covered += 1
        else:
            uncovered.append(pid)
            issues.append(issue("POST_REPAIR_CLOSE_WITHOUT_SKILL_LINEAGE", "C", "no skill_triggered or skill_blocked event after cadence repair", pid))

    coverage_pct = 100.0 if eligible == 0 else round(covered * 100.0 / eligible, 4)
    critical_count = sum(row["severity"] == "C" for row in issues)
    if critical_count:
        state = "HOLD"
        verdict = "LINEAGE_CADENCE_REPAIR_NEW_GAP_DETECTED"
    elif eligible >= CANARY_TARGET:
        state = "PASS"
        verdict = "LINEAGE_CADENCE_REPAIR_20C_PASS"
    elif eligible:
        state = "PASS"
        verdict = "LINEAGE_CADENCE_REPAIR_ACCUMULATING"
    else:
        state = "PASS"
        verdict = "LINEAGE_CADENCE_REPAIR_ARMED_WAITING_FORWARD_CLOSE"

    status = {
        "schema": "q4r3_exact25_lineage_cadence_repair_status_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "root_cause": "MISSED_OPEN_WINDOW_NO_OBSERVER_TICK",
        "repair_mode": "SHORTER_OBSERVER_CADENCE_PLUS_FORWARD_ONLY_CANARY",
        "observer_interval_sec": int(activation.get("observer_interval_sec") or 0),
        "baseline_formal_ledger_rows": baseline_formal,
        "baseline_skill_event_rows": baseline_events,
        "current_formal_ledger_rows": len(formal_rows),
        "current_skill_event_rows": len(event_rows),
        "post_repair_close_count": eligible,
        "post_repair_lineage_covered_count": covered,
        "post_repair_uncovered_count": len(uncovered),
        "post_repair_uncovered_position_ids": uncovered[:100],
        "post_repair_coverage_pct": coverage_pct,
        "canary_target_close_count": CANARY_TARGET,
        "remaining_to_canary": max(0, CANARY_TARGET - eligible),
        "known_prior_gap_count": known_prior_gap_count,
        "known_prior_gaps_preserved": True,
        "known_prior_gaps_used_for_skill_performance": False,
        "historical_backfill_performed": False,
        "automatic_patch_allowed": False,
        "comparison_decision_enabled": False,
        "ranking_enabled": False,
        "promotion_enabled": False,
        "observer_only": True,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
        "strategy_modified": False,
        "trade_method_modified": False,
        "skill_registry_modified": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "violation_count": len(issues),
        "violation_severity": "C" if critical_count else None,
        "action": "hold",
    }
    violations = {
        "schema": "q4r3_exact25_lineage_cadence_repair_violations_v1",
        "generated_at": now_iso(),
        "state": "VIOLATION" if issues else "CLEAR",
        "count": len(issues),
        "severity": status["violation_severity"],
        "notify": bool(critical_count),
        "violations": issues,
        "action": "hold",
    }
    return status, violations


def run(args: argparse.Namespace) -> int:
    formal_rows, formal_errors = read_jsonl(args.formal_ledger)
    event_rows, event_errors = read_jsonl(args.skill_events)
    status, violations = evaluate(
        activation=read_json(args.activation, {}),
        formal_rows=formal_rows,
        formal_errors=formal_errors,
        event_rows=event_rows,
        event_errors=event_errors,
    )
    atomic_json(args.status, status)
    atomic_json(args.violations, violations)
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0 if status["state"] == "PASS" else 2


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--activation", type=Path, required=True)
    value.add_argument("--formal-ledger", type=Path, required=True)
    value.add_argument("--skill-events", type=Path, required=True)
    value.add_argument("--status", type=Path, required=True)
    value.add_argument("--violations", type=Path, required=True)
    return value


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
