#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

UTC = timezone.utc
POSITION_KEYS = ("position_id", "positionId", "trade_id", "id")
ENTRY_KEYS = ("entry_ts", "opened_at", "open_ts", "entry_time", "created_at")
EXIT_KEYS = ("exit_ts", "closed_at", "close_ts", "exit_time", "captured_at", "measurement_written_at")
SKILL_KEYS = (
    "skill_id", "skill_ids", "skill", "skills", "skill_name", "skill_names",
    "selected_skill", "selected_skills", "applied_skill", "applied_skills",
    "action_skill", "skill_tag", "skill_tags",
)
COVERAGE_TYPES = {"skill_triggered", "skill_blocked"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_ts(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        if number > 10_000_000_000:
            number /= 1000.0
        return number
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_ts(float(text))
    except ValueError:
        pass
    try:
        value_dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value_dt.tzinfo is None:
        value_dt = value_dt.replace(tzinfo=UTC)
    return value_dt.timestamp()


def iso(value: float | None) -> str | None:
    return None if value is None else datetime.fromtimestamp(value, UTC).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.is_file():
        return rows, [{"line": 0, "error": "FILE_MISSING", "path": str(path)}]
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
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def first(row: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None:
            return value
    return None


def position_id(row: Mapping[str, Any]) -> str:
    return str(first(row, POSITION_KEYS) or "").strip()


def event_type(row: Mapping[str, Any]) -> str:
    return str(row.get("event_type") or row.get("type") or "").strip().lower()


def walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def flatten(value: Any) -> list[str]:
    if isinstance(value, dict):
        values: list[str] = []
        for child in value.values():
            values.extend(flatten(child))
        return values
    if isinstance(value, (list, tuple, set)):
        values = []
        for child in value:
            values.extend(flatten(child))
        return values
    text = str(value or "").strip()
    return [text] if text else []


def skill_values(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        for key in SKILL_KEYS:
            if key in row:
                values.extend(flatten(row.get(key)))
    return sorted(set(values))


def journal_invocations(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, errors = read_jsonl(path)
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    anonymous = 0
    for row in rows:
        invocation = str(row.get("_SYSTEMD_INVOCATION_ID") or "").strip()
        if not invocation:
            anonymous += 1
            invocation = f"anonymous:{anonymous}"
        grouped[invocation].append(row)

    invocations: list[dict[str, Any]] = []
    for invocation, items in grouped.items():
        timestamps = [parse_ts(item.get("__REALTIME_TIMESTAMP")) for item in items]
        timestamps = [value for value in timestamps if value is not None]
        if not timestamps:
            continue
        messages = [str(item.get("MESSAGE") or "") for item in items]
        failed = any(
            "fail" in message.lower() or "traceback" in message.lower() or "error" in message.lower()
            for message in messages
        ) or any(str(item.get("PRIORITY") or "") in {"0", "1", "2", "3"} for item in items)
        invocations.append({
            "invocation_id": invocation,
            "start_ts": min(timestamps),
            "end_ts": max(timestamps),
            "failed": failed,
            "message_count": len(items),
            "error_messages": [message[:300] for message in messages if any(token in message.lower() for token in ("fail", "error", "traceback"))][:5],
        })
    invocations.sort(key=lambda item: item["start_ts"])
    return invocations, errors


def bounded_position_evidence(root: Path, activated_at: float, max_files: int = 600) -> dict[str, list[dict[str, Any]]]:
    candidates: list[tuple[float, Path]] = []
    patterns = (
        "exact25_edge_v1/**/*.json",
        "exact25_edge_v1/**/*.jsonl",
    )
    for pattern in patterns:
        for path in root.glob(pattern):
            try:
                stat = path.stat()
            except OSError:
                continue
            if not path.is_file() or stat.st_size > 5_000_000 or stat.st_mtime < activated_at - 900:
                continue
            if any(part.lower() in {"lineage_cadence_repair", "formal_exact5_measurement"} for part in path.parts):
                continue
            candidates.append((stat.st_mtime, path))

    by_position: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for _mtime, path in sorted(candidates, reverse=True)[:max_files]:
        if path.suffix == ".jsonl":
            payload, _ = read_jsonl(path)
        else:
            payload = load_json(path, None)
        if payload is None:
            continue
        for row in walk(payload):
            pid = position_id(row)
            if not pid:
                continue
            enriched = dict(row)
            enriched["_source_path"] = str(path)
            by_position[pid].append(enriched)
    return dict(by_position)


def classify_gap(
    close: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    invocations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    pid = position_id(close)
    entry_ts = parse_ts(first(close, ENTRY_KEYS))
    exit_ts = parse_ts(first(close, EXIT_KEYS))
    duration = None if entry_ts is None or exit_ts is None else max(0.0, exit_ts - entry_ts)
    between = [
        item for item in invocations
        if entry_ts is not None and exit_ts is not None and entry_ts <= float(item["start_ts"]) <= exit_ts
    ]
    failed_between = [item for item in between if item.get("failed")]
    skills = skill_values(evidence)

    if entry_ts is None or exit_ts is None:
        cause, confidence = "TIMESTAMP_UNCERTAIN", "LOW"
    elif not between:
        cause, confidence = "MISSED_OPEN_WINDOW_NO_OBSERVER_INVOCATION", "HIGH"
    elif failed_between:
        cause, confidence = "OBSERVER_INVOCATION_FAILED_DURING_OPEN", "HIGH"
    elif not skills:
        cause, confidence = "OBSERVER_INVOKED_WITHOUT_EXPLICIT_SKILL", "HIGH"
    else:
        cause, confidence = "OBSERVER_INVOKED_WITH_SKILL_BUT_NO_EVENT", "HIGH"

    return {
        "position_id": pid,
        "strategy_id": close.get("strategy_id"),
        "method_id": close.get("method_id") or close.get("trade_method_id"),
        "symbol": close.get("symbol"),
        "side": close.get("side"),
        "entry_ts": iso(entry_ts),
        "exit_ts": iso(exit_ts),
        "duration_sec": None if duration is None else round(duration, 3),
        "observer_invocation_count_between": len(between),
        "observer_failed_invocation_count_between": len(failed_between),
        "observer_invocations_between": [iso(float(item["start_ts"])) for item in between[:20]],
        "explicit_skill_values": skills,
        "evidence_row_count": len(evidence),
        "evidence_paths": sorted({str(item.get("_source_path") or "") for item in evidence if item.get("_source_path")})[:20],
        "cause": cause,
        "confidence": confidence,
        "action": "hold",
    }


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return round(ordered[index], 3)


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    activation = load_json(args.activation, {})
    repair_status = load_json(args.repair_status, {})
    activated_at = parse_ts(activation.get("activated_at"))
    if activated_at is None:
        raise RuntimeError("REPAIR_ACTIVATION_TIMESTAMP_REQUIRED")
    baseline_formal = int(activation.get("baseline_formal_ledger_rows") or 0)
    baseline_events = int(activation.get("baseline_skill_event_rows") or 0)

    formal_rows, formal_errors = read_jsonl(args.formal_ledger)
    event_rows, event_errors = read_jsonl(args.skill_events)
    invocations, journal_errors = journal_invocations(args.observer_journal_jsonl)
    evidence_by_position = bounded_position_evidence(args.runtime_root, activated_at)

    post_closes = formal_rows[baseline_formal:]
    events_by_position: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows[baseline_events:]:
        pid = position_id(row)
        if pid:
            events_by_position[pid].append(row)

    gaps: list[dict[str, Any]] = []
    covered = 0
    for close in post_closes:
        pid = position_id(close)
        covered_events = [row for row in events_by_position.get(pid, []) if event_type(row) in COVERAGE_TYPES]
        if covered_events:
            covered += 1
            continue
        gaps.append(classify_gap(close, evidence_by_position.get(pid, []), invocations))

    invocation_starts = [float(item["start_ts"]) for item in invocations]
    invocation_intervals = [b - a for a, b in zip(invocation_starts, invocation_starts[1:]) if b >= a]
    durations = [float(item["duration_sec"]) for item in gaps if item.get("duration_sec") is not None]
    cause_counts = Counter(str(item["cause"]) for item in gaps)
    failed_invocations = [item for item in invocations if item.get("failed")]

    coverage_pct = 100.0 if not post_closes else round(covered * 100.0 / len(post_closes), 4)
    if gaps:
        state = "HOLD"
        verdict = "POSTREPAIR_LINEAGE_GAPS_CLASSIFIED"
    elif formal_errors or event_errors or journal_errors:
        state = "HOLD"
        verdict = "POSTREPAIR_AUDIT_INPUT_INTEGRITY_FAILURE"
    else:
        state = "PASS"
        verdict = "POSTREPAIR_LINEAGE_NO_GAP_PRESENT"

    dominant_cause = cause_counts.most_common(1)[0][0] if cause_counts else None
    likely_fix_route = {
        "MISSED_OPEN_WINDOW_NO_OBSERVER_INVOCATION": "EVENT_DRIVEN_OPEN_CAPTURE_OR_PRODUCER_EMITTED_OPEN_EVENT",
        "OBSERVER_INVOCATION_FAILED_DURING_OPEN": "OBSERVER_SERVICE_FAILURE_REPAIR",
        "OBSERVER_INVOKED_WITHOUT_EXPLICIT_SKILL": "EXPLICIT_SKILL_ENVELOPE_REPAIR",
        "OBSERVER_INVOKED_WITH_SKILL_BUT_NO_EVENT": "OBSERVER_EVENT_WRITE_OR_DEDUP_REPAIR",
        "TIMESTAMP_UNCERTAIN": "TIMESTAMP_LINEAGE_REPAIR",
    }.get(dominant_cause, "NO_PATCH_REQUIRED")

    return {
        "schema": "q4r3_exact25_lineage_postrepair_root_cause_v2",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "repair_activation": {
            "activated_at": activation.get("activated_at"),
            "baseline_formal_ledger_rows": baseline_formal,
            "baseline_skill_event_rows": baseline_events,
            "configured_observer_interval_sec": activation.get("observer_interval_sec"),
            "known_prior_gap_count": activation.get("known_prior_gap_count"),
        },
        "repair_status_snapshot": {
            "state": repair_status.get("state"),
            "verdict": repair_status.get("verdict"),
            "post_repair_close_count": repair_status.get("post_repair_close_count"),
            "post_repair_uncovered_count": repair_status.get("post_repair_uncovered_count"),
            "post_repair_coverage_pct": repair_status.get("post_repair_coverage_pct"),
        },
        "formal_ledger_rows": len(formal_rows),
        "skill_event_rows": len(event_rows),
        "post_repair_close_count": len(post_closes),
        "post_repair_covered_count": covered,
        "post_repair_gap_count": len(gaps),
        "post_repair_coverage_pct": coverage_pct,
        "cause_counts": dict(sorted(cause_counts.items())),
        "dominant_cause": dominant_cause,
        "likely_fix_route": likely_fix_route,
        "observer_invocation_count": len(invocations),
        "observer_failed_invocation_count": len(failed_invocations),
        "observer_first_invocation": iso(invocation_starts[0]) if invocation_starts else None,
        "observer_last_invocation": iso(invocation_starts[-1]) if invocation_starts else None,
        "observer_interval_sec": {
            "min": round(min(invocation_intervals), 3) if invocation_intervals else None,
            "median": round(statistics.median(invocation_intervals), 3) if invocation_intervals else None,
            "p95": percentile(invocation_intervals, 0.95),
            "max": round(max(invocation_intervals), 3) if invocation_intervals else None,
        },
        "gap_duration_sec": {
            "min": round(min(durations), 3) if durations else None,
            "median": round(statistics.median(durations), 3) if durations else None,
            "p95": percentile(durations, 0.95),
            "max": round(max(durations), 3) if durations else None,
        },
        "parse_errors": {
            "formal_ledger": formal_errors,
            "skill_events": event_errors,
            "observer_journal": journal_errors,
        },
        "gaps": gaps,
        "automatic_patch_allowed": False,
        "historical_backfill_performed": False,
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
        "action": "hold",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--activation", type=Path, required=True)
    parser.add_argument("--repair-status", type=Path, required=True)
    parser.add_argument("--formal-ledger", type=Path, required=True)
    parser.add_argument("--skill-events", type=Path, required=True)
    parser.add_argument("--observer-journal-jsonl", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args)
    atomic_json(args.output, result)
    print(json.dumps({
        "state": result["state"],
        "verdict": result["verdict"],
        "post_repair_close_count": result["post_repair_close_count"],
        "post_repair_gap_count": result["post_repair_gap_count"],
        "post_repair_coverage_pct": result["post_repair_coverage_pct"],
        "cause_counts": result["cause_counts"],
        "dominant_cause": result["dominant_cause"],
        "likely_fix_route": result["likely_fix_route"],
        "observer_interval_sec": result["observer_interval_sec"],
        "gap_duration_sec": result["gap_duration_sec"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
