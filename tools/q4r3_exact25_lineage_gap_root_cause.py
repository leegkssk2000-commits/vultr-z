#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

UTC = timezone.utc

SKILL_KEYS = (
    "skill_id", "skill_ids", "skill", "skills", "skill_name", "skill_names",
    "selected_skill", "selected_skills", "applied_skill", "applied_skills",
    "action_skill", "skill_tag", "skill_tags",
)
METHOD_KEYS = ("method_id", "trade_method_id", "method", "trade_method")
POSITION_KEYS = ("position_id", "positionId", "id")
ENTRY_KEYS = ("entry_ts", "opened_at", "open_ts", "entry_time", "created_at")
EXIT_KEYS = ("exit_ts", "closed_at", "close_ts", "exit_time", "captured_at")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_ts(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        if not math.isfinite(n):
            return None
        if n > 10_000_000_000:
            n /= 1000.0
        return n
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_ts(float(text))
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.is_file():
        return rows, errors
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


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def first(row: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None:
            return value
    return None


def walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def position_id(row: Mapping[str, Any]) -> str:
    return str(first(row, POSITION_KEYS) or "").strip()


def flatten_values(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(flatten_values(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(flatten_values(item))
        return out
    text = str(value or "").strip()
    return [text] if text else []


def evidence_values(objects: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> list[str]:
    values: list[str] = []
    for obj in objects:
        for key in keys:
            if key in obj:
                values.extend(flatten_values(obj.get(key)))
    return sorted(set(values))


def journal_run_timestamps(path: Path) -> list[float]:
    if not path.is_file():
        return []
    timestamps: list[float] = []
    pattern = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[+-]\d{4}|[+-]\d\d:\d\d))")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        raw = match.group(1).replace(",", ".")
        if re.search(r"[+-]\d{4}$", raw):
            raw = raw[:-5] + raw[-5:-2] + ":" + raw[-2:]
        ts = parse_ts(raw)
        if ts is not None:
            timestamps.append(ts)
    buckets: dict[int, float] = {}
    for ts in timestamps:
        buckets.setdefault(int(ts // 10), ts)
    return sorted(buckets.values())


def bounded_preentry_objects(root: Path, patterns: Sequence[str], activated_at: float, max_files: int) -> dict[str, list[dict[str, Any]]]:
    candidates: list[tuple[float, Path]] = []
    if not root.exists():
        return {}
    for pattern in patterns:
        for path in root.glob(pattern):
            try:
                st = path.stat()
            except OSError:
                continue
            if path.is_file() and st.st_size <= 5_000_000 and st.st_mtime >= activated_at - 3600:
                candidates.append((st.st_mtime, path))
    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for _mtime, path in sorted(candidates, reverse=True)[:max_files]:
        payload = load_json(path, None)
        if payload is None:
            continue
        for obj in walk(payload):
            pid = position_id(obj)
            if pid:
                enriched = dict(obj)
                enriched["_source_path"] = str(path)
                by_position[pid].append(enriched)
    return dict(by_position)


def event_type(row: Mapping[str, Any]) -> str:
    return str(row.get("event_type") or row.get("type") or "").strip().lower()


def classify_gap(
    close: Mapping[str, Any],
    related_producer: Sequence[Mapping[str, Any]],
    related_preentry: Sequence[Mapping[str, Any]],
    observer_runs: Sequence[float],
) -> dict[str, Any]:
    pid = position_id(close)
    entry = parse_ts(first(close, ENTRY_KEYS))
    exit_ = parse_ts(first(close, EXIT_KEYS))
    if exit_ is None:
        exit_ = parse_ts(close.get("measurement_written_at"))
    runs_between = [ts for ts in observer_runs if entry is not None and exit_ is not None and entry <= ts <= exit_]
    skills = evidence_values([*related_producer, *related_preentry], SKILL_KEYS)
    methods = evidence_values([*related_producer, *related_preentry, close], METHOD_KEYS)
    duration = None if entry is None or exit_ is None else max(0.0, exit_ - entry)

    if entry is None or exit_ is None:
        cause = "TIMESTAMP_UNCERTAIN"
        confidence = "LOW"
    elif not runs_between:
        cause = "MISSED_OPEN_WINDOW_NO_OBSERVER_TICK"
        confidence = "HIGH" if duration is not None and duration < 75 else "MEDIUM"
    elif not skills:
        cause = "OBSERVER_TICK_WITHOUT_EXPLICIT_SKILL"
        confidence = "HIGH"
    else:
        cause = "OBSERVER_TICK_WITH_SKILL_BUT_NO_EVENT"
        confidence = "HIGH"

    return {
        "position_id": pid,
        "strategy_id": close.get("strategy_id"),
        "symbol": close.get("symbol"),
        "side": close.get("side"),
        "entry_ts": iso(entry),
        "exit_ts": iso(exit_),
        "duration_sec": None if duration is None else round(duration, 3),
        "observer_run_count_between": len(runs_between),
        "observer_runs_between": [iso(ts) for ts in runs_between],
        "producer_evidence_rows": len(related_producer),
        "preentry_evidence_rows": len(related_preentry),
        "explicit_skill_values": skills,
        "method_values": methods,
        "cause": cause,
        "confidence": confidence,
        "action": "hold",
    }


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    activation = load_json(args.activation, {})
    checkpoint = load_json(args.checkpoint, {})
    integrity = load_json(args.integrity, {})
    activation_ts = parse_ts(activation.get("activated_at"))
    if activation_ts is None:
        raise RuntimeError("ACTIVATION_TIMESTAMP_REQUIRED")
    baseline_rows = int(activation.get("baseline_ledger_rows") or 0)

    formal_rows, formal_errors = read_jsonl(args.formal_ledger)
    skill_rows, skill_errors = read_jsonl(args.skill_events)
    producer_rows, producer_errors = read_jsonl(args.producer_ledger)
    observer_runs = journal_run_timestamps(args.observer_journal)
    preentry = bounded_preentry_objects(
        args.runtime_root,
        args.preentry_glob,
        activation_ts,
        args.preentry_max_files,
    )

    post_closes = formal_rows[baseline_rows:]
    lineage_by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in skill_rows:
        pid = position_id(row)
        if pid and event_type(row) in {"skill_triggered", "skill_blocked", "close_outcome_joined"}:
            lineage_by_position[pid].append(row)

    producer_by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in producer_rows:
        pid = position_id(row)
        if pid:
            producer_by_position[pid].append(row)

    gaps: list[dict[str, Any]] = []
    covered = 0
    for close in post_closes:
        pid = position_id(close)
        initial_events = [r for r in lineage_by_position.get(pid, []) if event_type(r) in {"skill_triggered", "skill_blocked"}]
        if initial_events:
            covered += 1
            continue
        gaps.append(classify_gap(close, producer_by_position.get(pid, []), preentry.get(pid, []), observer_runs))

    cause_counts = Counter(row["cause"] for row in gaps)
    checkpoint_count = checkpoint.get("current_closed_count")
    ledger_count = len(formal_rows)
    checkpoint_ts = parse_ts(checkpoint.get("generated_at"))
    ledger_mtime = args.formal_ledger.stat().st_mtime if args.formal_ledger.exists() else None
    count_gap_classification = "NONE"
    if isinstance(checkpoint_count, int) and checkpoint_count != ledger_count:
        if checkpoint_ts is not None and ledger_mtime is not None and checkpoint_ts <= ledger_mtime:
            count_gap_classification = "ASYNC_SNAPSHOT_LAG"
        else:
            count_gap_classification = "COUNT_MISMATCH_UNRESOLVED"

    severe_gap_count = sum(
        count for cause, count in cause_counts.items()
        if cause in {"OBSERVER_TICK_WITH_SKILL_BUT_NO_EVENT", "TIMESTAMP_UNCERTAIN"}
    )
    state = "HOLD" if gaps or formal_errors or skill_errors else "PASS"
    verdict = "LINEAGE_GAP_ROOT_CAUSE_CLASSIFIED" if gaps and severe_gap_count == 0 else (
        "LINEAGE_GAP_REQUIRES_CODE_PATH_DIAGNOSIS" if gaps else "LINEAGE_GAP_NOT_PRESENT"
    )

    return {
        "schema": "q4r3_exact25_lineage_gap_root_cause_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "activation_ts": iso(activation_ts),
        "activation_baseline_ledger_rows": baseline_rows,
        "formal_ledger_rows": ledger_count,
        "post_activation_close_count": len(post_closes),
        "covered_close_count": covered,
        "gap_close_count": len(gaps),
        "coverage_pct": round(100.0 * covered / len(post_closes), 4) if post_closes else 100.0,
        "cause_counts": dict(sorted(cause_counts.items())),
        "checkpoint_current_closed_count": checkpoint_count,
        "checkpoint_generated_at": checkpoint.get("generated_at"),
        "count_gap_classification": count_gap_classification,
        "observer_run_timestamp_count": len(observer_runs),
        "observer_first_run": iso(observer_runs[0]) if observer_runs else None,
        "observer_last_run": iso(observer_runs[-1]) if observer_runs else None,
        "parse_errors": {
            "formal_ledger": formal_errors,
            "skill_events": skill_errors,
            "producer_ledger": producer_errors,
        },
        "integrity_snapshot": {
            "state": integrity.get("state"),
            "verdict": integrity.get("verdict"),
            "violation_count": integrity.get("violation_count"),
            "integrity_gate_locked": integrity.get("integrity_gate_locked"),
        },
        "gaps": gaps,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "historical_backfill_performed": False,
        "formal_ledger_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "observer_modified": False,
        "automatic_patch_allowed": False,
        "action": "hold",
    }


def render_report(result: Mapping[str, Any]) -> str:
    lines = [
        "ZEL Exact25 Skill Lineage Gap Root-Cause Audit",
        f"generated_at={result.get('generated_at')}",
        f"state={result.get('state')}",
        f"verdict={result.get('verdict')}",
        f"formal_ledger_rows={result.get('formal_ledger_rows')}",
        f"post_activation_close_count={result.get('post_activation_close_count')}",
        f"covered_close_count={result.get('covered_close_count')}",
        f"gap_close_count={result.get('gap_close_count')}",
        f"coverage_pct={result.get('coverage_pct')}",
        f"count_gap_classification={result.get('count_gap_classification')}",
        f"cause_counts={json.dumps(result.get('cause_counts'), ensure_ascii=False, sort_keys=True)}",
        "",
        "PER_POSITION",
    ]
    for row in result.get("gaps", []):
        lines.append(
            " | ".join([
                str(row.get("position_id")),
                f"cause={row.get('cause')}",
                f"confidence={row.get('confidence')}",
                f"duration_sec={row.get('duration_sec')}",
                f"observer_runs={row.get('observer_run_count_between')}",
                f"producer_rows={row.get('producer_evidence_rows')}",
                f"preentry_rows={row.get('preentry_evidence_rows')}",
                f"skills={','.join(row.get('explicit_skill_values') or []) or '<none>'}",
                f"methods={','.join(row.get('method_values') or []) or '<none>'}",
            ])
        )
    lines.extend(["", "NO MUTATION PERFORMED", "action=hold"])
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--activation", type=Path, required=True)
    p.add_argument("--formal-ledger", type=Path, required=True)
    p.add_argument("--skill-events", type=Path, required=True)
    p.add_argument("--producer-ledger", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--integrity", type=Path, required=True)
    p.add_argument("--observer-journal", type=Path, required=True)
    p.add_argument("--runtime-root", type=Path, required=True)
    p.add_argument("--preentry-glob", action="append", default=[
        "exact25_edge_v1/**/*preentry*.json",
        "exact25_edge_v1/**/*method*context*.json",
        "exact25_edge_v1/**/*entry*context*.json",
    ])
    p.add_argument("--preentry-max-files", type=int, default=800)
    p.add_argument("--json-out", type=Path, required=True)
    p.add_argument("--report-out", type=Path, required=True)
    return p


def main() -> int:
    args = parser().parse_args()
    result = analyze(args)
    atomic_json(args.json_out, result)
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(render_report(result), encoding="utf-8")
    print(f"ROOT_CAUSE_JSON={args.json_out}")
    print(f"ROOT_CAUSE_REPORT={args.report_out}")
    print(f"STATE={result['state']}")
    print(f"VERDICT={result['verdict']}")
    print(f"GAP_CLOSE_COUNT={result['gap_close_count']}")
    print(f"CAUSE_COUNTS={json.dumps(result['cause_counts'], sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
