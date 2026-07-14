from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, optional: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if optional:
            return {}
        raise
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def immutable_json(path: Path, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
    except FileExistsError:
        current = path.read_bytes()
        if current != encoded:
            raise RuntimeError(f"IMMUTABLE_SNAPSHOT_MISMATCH:{path}")
        return "EXISTS_IDENTICAL"
    with os.fdopen(fd, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return "CREATED"


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except Exception as exc:
                errors.append(f"line={lineno}:{type(exc).__name__}")
                continue
            if not isinstance(value, dict):
                errors.append(f"line={lineno}:NON_OBJECT")
                continue
            rows.append(value)
    return rows, errors


def strategy_files(root: Path, ssot: Mapping[str, Any]) -> list[Path]:
    found: list[Path] = []
    for relative in ssot.get("protected_strategy_roots", []):
        base = (root / str(relative)).resolve()
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".json"} and "__pycache__" not in path.parts:
                found.append(path)
    return found


def hash_map(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(set(path.resolve() for path in paths)):
        try:
            key = str(path.relative_to(root.resolve()))
        except ValueError:
            key = str(path)
        result[key] = sha256_file(path)
    return result


def safe_flags(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: payload.get(key) for key in ("paper_enabled", "live_enabled", "order_enabled")}


def milestone_state(total: int, milestones: list[int]) -> dict[str, Any]:
    reached = [value for value in milestones if total >= value]
    next_values = [value for value in milestones if total < value]
    return {
        "reached": reached,
        "highest_reached": max(reached) if reached else 0,
        "next": min(next_values) if next_values else None,
        "remaining_to_next": (min(next_values) - total) if next_values else 0,
    }


def run(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    ssot = load_json(args.ssot)
    manifest = load_json(args.manifest)
    producer = load_json(args.producer_status)
    writer = load_json(args.writer_status)
    rows, parse_errors = read_jsonl(args.ledger)

    event_ids = [str(row.get("event_id") or "") for row in rows if row.get("event_id")]
    duplicate_ids = sorted(key for key, count in Counter(event_ids).items() if count > 1)
    strategy_counts = Counter(str(row.get("strategy_id") or "unknown") for row in rows)
    expected_count = int(ssot.get("expected_strategy_count", 25))
    manifest_strategies = manifest.get("strategies", [])
    if isinstance(manifest_strategies, list):
        strategy_names = sorted(
            str(item.get("strategy_id"))
            for item in manifest_strategies
            if isinstance(item, dict) and item.get("strategy_id")
        )
    else:
        strategy_names = []
    if not strategy_names:
        strategy_names = sorted(strategy_counts)

    protected = strategy_files(root, ssot)
    surface_hashes = hash_map(root, [args.manifest, args.ssot, *protected])
    baseline = load_json(args.baseline, optional=True)
    baseline_hashes = baseline.get("protected_surface_hashes", {}) if baseline else {}
    surface_changes = {
        key: {"baseline": baseline_hashes.get(key), "current": value}
        for key, value in surface_hashes.items()
        if baseline_hashes and baseline_hashes.get(key) != value
    }
    removed_surfaces = sorted(key for key in baseline_hashes if key not in surface_hashes)
    if not baseline:
        atomic_json(args.baseline, {
            "schema": "q4r3_exact25_protected_surface_baseline_v1",
            "created_at": now_iso(),
            "protected_surface_hashes": surface_hashes,
            "strategy_file_count": len(protected),
            "observer_only": True,
        })

    milestones = sorted({int(value) for value in ssot.get("milestones", [20, 100, 200, 300])})
    state = milestone_state(len(rows), milestones)
    preview_min = int(ssot.get("per_strategy_preview_min", 30))
    final_min = int(ssot.get("per_strategy_final_min", 50))
    counts = {name: int(strategy_counts.get(name, 0)) for name in strategy_names}
    preview_ready = bool(counts) and all(value >= preview_min for value in counts.values())
    final_ready = bool(counts) and all(value >= final_min for value in counts.values())

    issues: list[dict[str, Any]] = []
    if parse_errors:
        issues.append({"code": "FORMAL_LEDGER_PARSE_ERROR", "severity": "C", "detail": parse_errors[:10]})
    if duplicate_ids:
        issues.append({"code": "DUPLICATE_EVENT_ID", "severity": "C", "detail": duplicate_ids[:20]})
    if strategy_names and len(strategy_names) != expected_count:
        issues.append({"code": "STRATEGY_COUNT_MISMATCH", "severity": "M", "detail": f"manifest={len(strategy_names)} expected={expected_count}"})
    for name, payload in (("producer", producer), ("writer", writer)):
        for key, required in ssot.get("required_safe_flags", {}).items():
            if payload.get(key) not in (required, None):
                issues.append({"code": "UNSAFE_RUNTIME_FLAG", "severity": "C", "detail": f"{name}.{key}={payload.get(key)}"})
    if surface_changes or removed_surfaces:
        issues.append({
            "code": "PROTECTED_SURFACE_DRIFT",
            "severity": "C",
            "detail": {"changed": surface_changes, "removed": removed_surfaces},
        })

    ledger_hash = sha256_file(args.ledger)
    evidence = {
        "schema": "q4r3_exact25_immutable_evidence_snapshot_v1",
        "generated_at": now_iso(),
        "epoch_id": ssot.get("expected_epoch"),
        "formal_ledger_row_count": len(rows),
        "formal_ledger_sha256": ledger_hash,
        "manifest_sha256": sha256_file(args.manifest),
        "ssot_sha256": sha256_file(args.ssot),
        "producer_status_sha256": sha256_file(args.producer_status),
        "writer_status_sha256": sha256_file(args.writer_status),
        "protected_surface_hashes": surface_hashes,
        "strategy_file_count": len(protected),
        "strategy_counts": counts,
        "duplicate_event_count": len(duplicate_ids),
        "parse_error_count": len(parse_errors),
        "milestone_state": state,
        "producer_safe_flags": safe_flags(producer),
        "writer_safe_flags": safe_flags(writer),
        "observer_only": True,
        "action": "hold",
    }

    created: list[str] = []
    for value in state["reached"]:
        path = args.snapshot_dir / f"milestone_{value:04d}_{ledger_hash[:12]}.json"
        marker = args.snapshot_dir / f"milestone_{value:04d}_latest.json"
        if not marker.exists():
            immutable_json(path, evidence)
            atomic_json(marker, {
                "schema": "q4r3_exact25_milestone_pointer_v1",
                "milestone": value,
                "snapshot": path.name,
                "ledger_rows": len(rows),
                "ledger_sha256": ledger_hash,
                "created_at": now_iso(),
            })
            created.append(path.name)

    if bool(ssot.get("daily_snapshot_enabled", True)):
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        daily = args.snapshot_dir / f"daily_{day}_{ledger_hash[:12]}.json"
        daily_marker = args.snapshot_dir / f"daily_{day}_latest.json"
        if not daily_marker.exists():
            immutable_json(daily, evidence)
            atomic_json(daily_marker, {
                "schema": "q4r3_exact25_daily_evidence_pointer_v1",
                "snapshot": daily.name,
                "ledger_rows": len(rows),
                "ledger_sha256": ledger_hash,
                "created_at": now_iso(),
            })
            created.append(daily.name)

    gate = {
        "schema": "q4r3_exact25_epoch_milestone_gate_lock_v1",
        "generated_at": now_iso(),
        "epoch_id": ssot.get("expected_epoch"),
        "formal_ledger_row_count": len(rows),
        "milestone_state": state,
        "integrity_checkpoint_20_due": len(rows) >= 20,
        "integrity_checkpoint_100_due": len(rows) >= 100,
        "full_audit_checkpoint_200_due": len(rows) >= 200,
        "freeze_checkpoint_300_due": len(rows) >= 300,
        "per_strategy_preview_min": preview_min,
        "per_strategy_final_min": final_min,
        "preview_sample_ready": preview_ready,
        "final_sample_ready": final_ready,
        "insufficient_preview_strategies": sorted(name for name, count in counts.items() if count < preview_min),
        "insufficient_final_strategies": sorted(name for name, count in counts.items() if count < final_min),
        "strategy_mutation_allowed": False,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "repair_fork_creation_allowed": bool(len(rows) >= 300 and preview_ready and not issues),
        "final_candidate_decision_allowed": bool(len(rows) >= 300 and final_ready and not issues),
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "action": "hold",
    }
    status = {
        "schema": "q4r3_exact25_evidence_milestone_lock_status_v1",
        "generated_at": now_iso(),
        "state": "CLEAR" if not issues else "VIOLATION",
        "violation_count": len(issues),
        "violation_severity": "C" if any(item["severity"] == "C" for item in issues) else ("M" if issues else None),
        "issues": issues,
        "formal_ledger_row_count": len(rows),
        "formal_ledger_sha256": ledger_hash,
        "snapshot_created": created,
        "milestone_next": state["next"],
        "remaining_to_next": state["remaining_to_next"],
        "protected_surface_drift": bool(surface_changes or removed_surfaces),
        "observer_only": True,
        "action": "hold",
    }
    atomic_json(args.evidence_latest, evidence)
    atomic_json(args.gate_latest, gate)
    atomic_json(args.status, status)
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--root", type=Path, required=True)
    value.add_argument("--ledger", type=Path, required=True)
    value.add_argument("--manifest", type=Path, required=True)
    value.add_argument("--producer-status", type=Path, required=True)
    value.add_argument("--writer-status", type=Path, required=True)
    value.add_argument("--ssot", type=Path, required=True)
    value.add_argument("--baseline", type=Path, required=True)
    value.add_argument("--snapshot-dir", type=Path, required=True)
    value.add_argument("--evidence-latest", type=Path, required=True)
    value.add_argument("--gate-latest", type=Path, required=True)
    value.add_argument("--status", type=Path, required=True)
    return value


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
