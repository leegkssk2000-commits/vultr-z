from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

UTC = timezone.utc


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_json(path: Path, default: Any = None) -> Any:
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
            payload = json.loads(line)
        except Exception as exc:
            errors.append({"line": line_no, "error": f"{type(exc).__name__}:{exc}"})
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        else:
            errors.append({"line": line_no, "error": "ROW_NOT_OBJECT"})
    return rows, errors


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def first(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None:
            return value
    return None


def parse_ts(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return number if math.isfinite(number) else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_ts(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def issue(code: str, severity: str, detail: str, source: str, position_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "detail": detail,
        "source": source,
        "action": "hold",
    }
    if position_id:
        payload["position_id"] = position_id
    return payload


def position_id(row: Mapping[str, Any]) -> str:
    return str(first(row, ("position_id", "positionId", "trade_id")) or "").strip()


def close_event_id(row: Mapping[str, Any]) -> str:
    return str(first(row, ("event_id", "close_event_id")) or "").strip()


def open_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("positions")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def duplicate_values(values: Iterable[str]) -> dict[str, int]:
    counts = Counter(value for value in values if value)
    return {value: count for value, count in counts.items() if count > 1}


def check_exact(payload: Mapping[str, Any], key: str, expected: Any, source: str, issues: list[dict[str, Any]]) -> None:
    observed = payload.get(key)
    if observed != expected:
        issues.append(issue("CONTRACT_VALUE_MISMATCH", "C", f"{key}={observed}:expected={expected}", source))


def check_observer(name: str, payload: Mapping[str, Any], issues: list[dict[str, Any]]) -> None:
    if payload.get("state") != "PASS":
        issues.append(issue("UPSTREAM_NOT_PASS", "C", f"{name}:{payload.get('verdict')}", name))
    if payload.get("observer_only") is not True:
        issues.append(issue("UPSTREAM_NOT_OBSERVER_ONLY", "C", name, name))
    for key in (
        "strategy_modified",
        "trade_method_modified",
        "skill_registry_modified",
        "producer_modified",
        "writer_modified",
        "formal_ledger_modified",
    ):
        if key in payload and payload.get(key) is not False:
            issues.append(issue("UPSTREAM_MUTATION_FLAG", "C", f"{name}:{key}={payload.get(key)}", name))


def audit(
    *,
    static_audit: Mapping[str, Any],
    storage: Mapping[str, Any],
    activation: Mapping[str, Any],
    ledger_rows: list[dict[str, Any]],
    ledger_errors: list[dict[str, Any]],
    events: list[dict[str, Any]],
    event_errors: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
    trigger_status: Mapping[str, Any],
    coverage: Mapping[str, Any],
    projection_status: Mapping[str, Any],
    projection: Mapping[str, Any],
    pair_status: Mapping[str, Any],
    pairs_report: Mapping[str, Any],
    risk_status: Mapping[str, Any],
    risk_grid: Mapping[str, Any],
    scoreboard_status: Mapping[str, Any],
    scoreboard: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    if static_audit.get("state") != "PASS" or not str(static_audit.get("verdict") or "").startswith("ACTIVE_IMPORT_CALL_SURFACE_PASS"):
        issues.append(issue("STATIC_SKILL_AUDIT_NOT_PASS", "C", str(static_audit.get("verdict")), "static_audit"))
    for key, expected in (
        ("strategy_import_pass_count", 25),
        ("strategy_empty_call_pass_count", 25),
        ("method_declaration_count", 6),
        ("resolver_pass_count", 18),
        ("compatibility_matrix_rows", 2700),
    ):
        check_exact(static_audit, key, expected, "static_audit", issues)

    if storage.get("state") != "PASS" or storage.get("verdict") != "STORAGE_REGROWTH_GUARD_HEALTHY":
        issues.append(issue("STORAGE_GUARD_NOT_HEALTHY", "C", str(storage.get("verdict")), "storage"))

    upstreams = {
        "skill_trigger_lineage": trigger_status,
        "six_profile_projection": projection_status,
        "future_pair_join": pair_status,
        "risk_scenario_grid": risk_status,
        "method_scoreboard": scoreboard_status,
        "checkpoint_100c": checkpoint,
    }
    for name, payload in upstreams.items():
        check_observer(name, payload, issues)

    check_exact(coverage, "matrix_rows", 2700, "coverage", issues)
    check_exact(projection_status, "profile_count", 6, "projection", issues)
    check_exact(risk_status, "scenario_count", 12, "risk_grid", issues)
    check_exact(scoreboard_status, "method_count", 6, "scoreboard", issues)
    check_exact(checkpoint, "target_closed_count", 100, "checkpoint", issues)

    for error in ledger_errors:
        issues.append(issue("FORMAL_LEDGER_PARSE_ERROR", "C", f"line={error['line']}:{error['error']}", "formal_ledger"))
    for error in event_errors:
        issues.append(issue("SKILL_EVENT_PARSE_ERROR", "C", f"line={error['line']}:{error['error']}", "skill_events"))

    baseline_rows = int(activation.get("baseline_ledger_rows") or 0)
    baseline_positions = {str(value) for value in activation.get("baseline_position_ids", []) if str(value)}
    activated_at = parse_ts(activation.get("activated_at"))
    if activated_at is None:
        issues.append(issue("ACTIVATION_TIMESTAMP_MISSING", "C", str(activation.get("activated_at")), "activation"))
    if activation.get("historical_backfill_allowed") is not False:
        issues.append(issue("UNSAFE_HISTORICAL_BACKFILL_FLAG", "C", str(activation.get("historical_backfill_allowed")), "activation"))
    if baseline_rows > len(ledger_rows):
        issues.append(issue("FORMAL_LEDGER_TRUNCATED_BELOW_BASELINE", "C", f"baseline={baseline_rows}:current={len(ledger_rows)}", "formal_ledger"))

    post_rows = ledger_rows[baseline_rows:]
    checkpoint_closed = int(checkpoint.get("current_closed_count") or 0)
    checkpoint_post = int(checkpoint.get("post_activation_closed_count") or 0)
    if checkpoint_closed != len(ledger_rows):
        issues.append(issue("CHECKPOINT_LEDGER_COUNT_MISMATCH", "C", f"checkpoint={checkpoint_closed}:ledger={len(ledger_rows)}", "checkpoint"))
    if checkpoint_post != len(post_rows):
        issues.append(issue("CHECKPOINT_POST_ACTIVATION_COUNT_MISMATCH", "C", f"checkpoint={checkpoint_post}:ledger={len(post_rows)}", "checkpoint"))
    if int(checkpoint.get("activation_baseline_ledger_rows") or 0) != baseline_rows:
        issues.append(issue("CHECKPOINT_BASELINE_MISMATCH", "C", f"checkpoint={checkpoint.get('activation_baseline_ledger_rows')}:activation={baseline_rows}", "checkpoint"))

    duplicate_close_ids = duplicate_values(close_event_id(row) for row in post_rows)
    for value, count in duplicate_close_ids.items():
        issues.append(issue("POST_ACTIVATION_DUPLICATE_CLOSE_EVENT_ID", "C", f"close_event_id={value}:count={count}", "formal_ledger"))
    duplicate_event_ids = duplicate_values(str(row.get("event_id") or "") for row in events)
    for value, count in duplicate_event_ids.items():
        issues.append(issue("DUPLICATE_SKILL_EVENT_ID", "C", f"event_id={value}:count={count}", "skill_events"))

    event_type_counts = Counter(str(row.get("event_type") or "") for row in events)
    trigger_count = event_type_counts["skill_triggered"]
    blocked_count = event_type_counts["skill_blocked"]
    close_join_count = event_type_counts["close_outcome_joined"]
    expected_status_counts = (
        ("skill_triggered_count", trigger_count),
        ("skill_blocked_count", blocked_count),
        ("close_outcome_joined_count", close_join_count),
    )
    for key, expected in expected_status_counts:
        if int(trigger_status.get(key) or 0) != expected:
            issues.append(issue("TRIGGER_STATUS_COUNT_MISMATCH", "C", f"{key}={trigger_status.get(key)}:events={expected}", "skill_trigger_lineage"))

    if int(pair_status.get("event_count") or 0) != len(events):
        issues.append(issue("PAIR_EVENT_COUNT_MISMATCH", "C", f"pair={pair_status.get('event_count')}:events={len(events)}", "future_pair_join"))
    for key, expected in (
        ("trigger_count", trigger_count),
        ("blocked_count", blocked_count),
        ("close_join_event_count", close_join_count),
    ):
        if int(pair_status.get(key) or 0) != expected:
            issues.append(issue("PAIR_STATUS_COUNT_MISMATCH", "C", f"{key}={pair_status.get(key)}:events={expected}", "future_pair_join"))

    if int(projection_status.get("total_trigger_count") or 0) != trigger_count:
        issues.append(issue("PROJECTION_TRIGGER_COUNT_MISMATCH", "C", f"projection={projection_status.get('total_trigger_count')}:events={trigger_count}", "six_profile_projection"))
    if int(projection_status.get("total_blocked_count") or 0) != blocked_count:
        issues.append(issue("PROJECTION_BLOCKED_COUNT_MISMATCH", "C", f"projection={projection_status.get('total_blocked_count')}:events={blocked_count}", "six_profile_projection"))
    if int(projection_status.get("total_outcome_join_count") or 0) != close_join_count:
        issues.append(issue("PROJECTION_OUTCOME_COUNT_MISMATCH", "C", f"projection={projection_status.get('total_outcome_join_count')}:events={close_join_count}", "six_profile_projection"))

    if int(risk_status.get("exact_pair_count") or 0) != int(pair_status.get("exact_pair_count") or 0):
        issues.append(issue("RISK_PAIR_COUNT_MISMATCH", "C", f"risk={risk_status.get('exact_pair_count')}:pair={pair_status.get('exact_pair_count')}", "risk_scenario_grid"))

    scoreboard_rows = scoreboard.get("rows") if isinstance(scoreboard, dict) else []
    scoreboard_rows = [row for row in scoreboard_rows if isinstance(row, dict)] if isinstance(scoreboard_rows, list) else []
    if len(scoreboard_rows) != 6:
        issues.append(issue("SCOREBOARD_ROW_COUNT_MISMATCH", "C", f"rows={len(scoreboard_rows)}", "method_scoreboard"))
    scoreboard_trigger_methods = sum(int(row.get("trigger_count") or 0) > 0 for row in scoreboard_rows)
    scoreboard_outcome_methods = sum(int(row.get("outcome_join_count") or 0) > 0 for row in scoreboard_rows)
    if int(scoreboard_status.get("methods_with_trigger") or 0) != scoreboard_trigger_methods:
        issues.append(issue("SCOREBOARD_TRIGGER_METHOD_COUNT_MISMATCH", "C", f"status={scoreboard_status.get('methods_with_trigger')}:rows={scoreboard_trigger_methods}", "method_scoreboard"))
    if int(scoreboard_status.get("methods_with_outcome") or 0) != scoreboard_outcome_methods:
        issues.append(issue("SCOREBOARD_OUTCOME_METHOD_COUNT_MISMATCH", "C", f"status={scoreboard_status.get('methods_with_outcome')}:rows={scoreboard_outcome_methods}", "method_scoreboard"))

    events_by_position: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    ledger_by_close: dict[str, dict[str, Any]] = {}
    post_position_ids: list[str] = []
    baseline_exempt_count = 0
    for row in post_rows:
        pid = position_id(row)
        cid = close_event_id(row)
        if pid:
            post_position_ids.append(pid)
        else:
            issues.append(issue("POST_ACTIVATION_CLOSE_POSITION_ID_MISSING", "C", f"close_event_id={cid}", "formal_ledger"))
        if not cid:
            issues.append(issue("POST_ACTIVATION_CLOSE_EVENT_ID_MISSING", "C", f"position_id={pid}", "formal_ledger", pid or None))
        elif cid not in ledger_by_close:
            ledger_by_close[cid] = row
        if pid in baseline_positions:
            baseline_exempt_count += 1

    for row in events:
        pid = str(row.get("position_id") or "").strip()
        if pid:
            events_by_position[pid].append(row)
        else:
            issues.append(issue("SKILL_EVENT_POSITION_ID_MISSING", "C", f"event_id={row.get('event_id')}", "skill_events"))
        event_ts = parse_ts(row.get("event_ts"))
        if activated_at is not None and event_ts is not None and event_ts < activated_at:
            issues.append(issue("PRE_ACTIVATION_SKILL_EVENT_CONTAMINATION", "C", f"event_id={row.get('event_id')}:event_ts={row.get('event_ts')}", "skill_events", pid or None))
        if pid in baseline_positions:
            issues.append(issue("BASELINE_POSITION_SKILL_EVENT_CONTAMINATION", "C", f"event_id={row.get('event_id')}", "skill_events", pid))

    uncovered: list[str] = []
    blocked_positions: list[str] = []
    triggered_without_close: list[str] = []
    lineage_eligible = 0
    lineage_covered = 0
    for row in post_rows:
        pid = position_id(row)
        if not pid or pid in baseline_positions:
            continue
        lineage_eligible += 1
        rows = events_by_position.get(pid, [])
        types = {str(item.get("event_type") or "") for item in rows}
        has_trigger = "skill_triggered" in types
        has_block = "skill_blocked" in types
        has_close_join = "close_outcome_joined" in types
        if has_trigger and has_block:
            issues.append(issue("POSITION_HAS_TRIGGER_AND_BLOCK", "C", f"types={sorted(types)}", "skill_events", pid))
        if not has_trigger and not has_block:
            uncovered.append(pid)
            issues.append(issue("POST_ACTIVATION_CLOSE_WITHOUT_SKILL_LINEAGE", "C", "closed position has neither trigger nor block event", "formal_ledger+skill_events", pid))
            continue
        lineage_covered += 1
        if has_block:
            blocked_positions.append(pid)
        if has_trigger and not has_close_join:
            triggered_without_close.append(pid)
            issues.append(issue("TRIGGERED_CLOSE_WITHOUT_OUTCOME_JOIN", "C", "formal close exists but close outcome event is absent", "formal_ledger+skill_events", pid))

    for row in events:
        if row.get("event_type") != "close_outcome_joined":
            continue
        pid = str(row.get("position_id") or "").strip()
        cid = str(row.get("close_event_id") or "").strip()
        ledger_row = ledger_by_close.get(cid)
        if not cid or ledger_row is None:
            issues.append(issue("CLOSE_OUTCOME_NOT_IN_POST_ACTIVATION_LEDGER", "C", f"close_event_id={cid}", "skill_events+formal_ledger", pid or None))
        elif position_id(ledger_row) != pid:
            issues.append(issue("CLOSE_OUTCOME_CROSS_POSITION_JOIN", "C", f"close_event_id={cid}:ledger_position={position_id(ledger_row)}", "skill_events+formal_ledger", pid or None))

    open_without_lineage: list[str] = []
    for row in open_positions:
        pid = position_id(row)
        if not pid or pid in baseline_positions:
            continue
        entry_ts = parse_ts(first(row, ("entry_ts", "opened_at", "created_at", "entry_time")))
        if activated_at is not None and entry_ts is not None and entry_ts < activated_at:
            continue
        types = {str(item.get("event_type") or "") for item in events_by_position.get(pid, [])}
        if "skill_triggered" not in types and "skill_blocked" not in types:
            open_without_lineage.append(pid)
            issues.append(issue("OPEN_POSITION_WITHOUT_SKILL_LINEAGE_EVENT", "M", "post-activation open has neither trigger nor block event", "open_positions+skill_events", pid))

    pair_rows = pairs_report.get("pairs") if isinstance(pairs_report, dict) else []
    pair_rows = [row for row in pair_rows if isinstance(row, dict)] if isinstance(pair_rows, list) else []
    exact_pairs = sum(row.get("exact_join") is True and row.get("pair_state") == "EXACT_CLOSE_JOINED" for row in pair_rows)
    pending_pairs = sum(row.get("pair_state") == "OPEN_PENDING_CLOSE" for row in pair_rows)
    if int(pair_status.get("exact_pair_count") or 0) != exact_pairs:
        issues.append(issue("PAIR_REPORT_EXACT_COUNT_MISMATCH", "C", f"status={pair_status.get('exact_pair_count')}:report={exact_pairs}", "future_pair_join"))
    if int(pair_status.get("pending_close_count") or 0) != pending_pairs:
        issues.append(issue("PAIR_REPORT_PENDING_COUNT_MISMATCH", "C", f"status={pair_status.get('pending_close_count')}:report={pending_pairs}", "future_pair_join"))

    critical_count = sum(row["severity"] == "C" for row in issues)
    major_count = sum(row["severity"] == "M" for row in issues)
    state = "HOLD" if issues else "PASS"
    if critical_count:
        verdict = "PRE100_INTEGRITY_CRITICAL_GAP"
    elif major_count:
        verdict = "PRE100_INTEGRITY_GAPS_DETECTED"
    else:
        verdict = "PRE100_INTEGRITY_PASS_ACCUMULATING"

    coverage_ratio = 100.0 if lineage_eligible == 0 else round(lineage_covered * 100.0 / lineage_eligible, 4)
    status = {
        "schema": "q4r3_exact25_pre100_integrity_status_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "current_closed_count": len(ledger_rows),
        "target_closed_count": 100,
        "remaining_closed_count": max(0, 100 - len(ledger_rows)),
        "activation_baseline_ledger_rows": baseline_rows,
        "post_activation_closed_count": len(post_rows),
        "baseline_exempt_close_count": baseline_exempt_count,
        "lineage_eligible_close_count": lineage_eligible,
        "lineage_covered_close_count": lineage_covered,
        "lineage_coverage_pct": coverage_ratio,
        "skill_triggered_count": trigger_count,
        "skill_blocked_count": blocked_count,
        "close_outcome_joined_count": close_join_count,
        "exact_pair_count": int(pair_status.get("exact_pair_count") or 0),
        "uncovered_close_count": len(uncovered),
        "uncovered_position_ids": sorted(set(uncovered))[:100],
        "blocked_close_count": len(set(blocked_positions)),
        "blocked_position_ids": sorted(set(blocked_positions))[:100],
        "triggered_without_close_join_count": len(set(triggered_without_close)),
        "triggered_without_close_join_position_ids": sorted(set(triggered_without_close))[:100],
        "open_without_lineage_count": len(set(open_without_lineage)),
        "open_without_lineage_position_ids": sorted(set(open_without_lineage))[:100],
        "duplicate_post_close_event_id_count": len(duplicate_close_ids),
        "duplicate_skill_event_id_count": len(duplicate_event_ids),
        "critical_count": critical_count,
        "major_count": major_count,
        "violation_count": len(issues),
        "violation_severity": "C" if critical_count else ("M" if major_count else None),
        "integrity_gate_locked": bool(issues),
        "comparison_decision_enabled": False,
        "ranking_enabled": False,
        "promotion_enabled": False,
        "deep_performance_audit_enabled": False,
        "observer_only": True,
        "historical_backfill_performed": False,
        "strategy_modified": False,
        "trade_method_modified": False,
        "skill_registry_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "action": "hold",
    }
    violations = {
        "schema": "q4r3_exact25_pre100_integrity_violations_v1",
        "generated_at": now_iso(),
        "state": "VIOLATION" if issues else "CLEAR",
        "count": len(issues),
        "severity": status["violation_severity"],
        "notify": bool(critical_count),
        "violations": issues,
        "action": "hold",
    }
    fix_queue = {
        "schema": "q4r3_exact25_pre100_fix_queue_v1",
        "generated_at": now_iso(),
        "state": "OPEN" if issues else "CLEAR",
        "count": len(issues),
        "automatic_patch_allowed": False,
        "items": [
            {
                "priority": "P0" if row["severity"] == "C" else "P1",
                "code": row["code"],
                "source": row["source"],
                "position_id": row.get("position_id"),
                "detail": row["detail"],
                "required_action": "READ_ONLY_ROOT_CAUSE_THEN_MINIMAL_PATCH",
                "action": "hold",
            }
            for row in issues
        ],
        "action": "hold",
    }
    return status, violations, fix_queue


def run(args: argparse.Namespace) -> int:
    ledger_rows, ledger_errors = read_jsonl(args.formal_ledger)
    events, event_errors = read_jsonl(args.skill_events)
    status, violations, fix_queue = audit(
        static_audit=load_json(args.static_audit, {}),
        storage=load_json(args.storage_status, {}),
        activation=load_json(args.activation, {}),
        ledger_rows=ledger_rows,
        ledger_errors=ledger_errors,
        events=events,
        event_errors=event_errors,
        open_positions=open_rows(load_json(args.open_positions, {})),
        trigger_status=load_json(args.trigger_status, {}),
        coverage=load_json(args.coverage, {}),
        projection_status=load_json(args.projection_status, {}),
        projection=load_json(args.projection, {}),
        pair_status=load_json(args.pair_status, {}),
        pairs_report=load_json(args.pairs_report, {}),
        risk_status=load_json(args.risk_status, {}),
        risk_grid=load_json(args.risk_grid, {}),
        scoreboard_status=load_json(args.scoreboard_status, {}),
        scoreboard=load_json(args.scoreboard, {}),
        checkpoint=load_json(args.checkpoint_status, {}),
    )
    atomic_json(args.status, status)
    atomic_json(args.violations, violations)
    atomic_json(args.fix_queue, fix_queue)
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--static-audit", type=Path, required=True)
    value.add_argument("--storage-status", type=Path, required=True)
    value.add_argument("--activation", type=Path, required=True)
    value.add_argument("--formal-ledger", type=Path, required=True)
    value.add_argument("--skill-events", type=Path, required=True)
    value.add_argument("--open-positions", type=Path, required=True)
    value.add_argument("--trigger-status", type=Path, required=True)
    value.add_argument("--coverage", type=Path, required=True)
    value.add_argument("--projection-status", type=Path, required=True)
    value.add_argument("--projection", type=Path, required=True)
    value.add_argument("--pair-status", type=Path, required=True)
    value.add_argument("--pairs-report", type=Path, required=True)
    value.add_argument("--risk-status", type=Path, required=True)
    value.add_argument("--risk-grid", type=Path, required=True)
    value.add_argument("--scoreboard-status", type=Path, required=True)
    value.add_argument("--scoreboard", type=Path, required=True)
    value.add_argument("--checkpoint-status", type=Path, required=True)
    value.add_argument("--status", type=Path, required=True)
    value.add_argument("--violations", type=Path, required=True)
    value.add_argument("--fix-queue", type=Path, required=True)
    return value


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
