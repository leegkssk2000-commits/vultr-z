from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

VERSION = "ZEL_EVENT_SOURCED_EXACT25_CUTOVER_PREFLIGHT_V1"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob(path: Path) -> str:
    result = subprocess.run(["git", "hash-object", str(path)], text=True, capture_output=True, timeout=20)
    if result.returncode != 0:
        return ""
    return result.stdout.strip().lower()


def audit(
    producer_source: Path,
    expected_blob_sha: str,
    state_path: Path,
    status_path: Path,
    formal_ledger: Path,
    event_db: Path,
    event_jsonl: Path,
) -> dict[str, Any]:
    blockers: list[str] = []
    source_blob = git_blob(producer_source) if producer_source.is_file() else ""
    if source_blob != expected_blob_sha.lower():
        blockers.append("PRODUCER_SOURCE_BLOB_MISMATCH")
    state = read_json(state_path) if state_path.is_file() else {}
    status = read_json(status_path) if status_path.is_file() else {}
    positions = state.get("positions") if isinstance(state.get("positions"), dict) else {}
    if not state:
        blockers.append("PRODUCER_STATE_MISSING")
    if positions:
        blockers.append("OPEN_POSITIONS_MUST_BE_ZERO_AT_CUTOVER")
    if not status:
        blockers.append("PRODUCER_STATUS_MISSING")
    for key, expected in {
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "private_credentials_used": False,
        "historical_backfill_allowed": False,
    }.items():
        if status.get(key) != expected:
            blockers.append(f"STATUS_SAFETY_MISMATCH:{key}")
    if not formal_ledger.is_file():
        blockers.append("FORMAL_LEDGER_MISSING")
    if event_db.exists() and event_db.stat().st_size > 0:
        blockers.append("EVENT_DB_ALREADY_NONEMPTY")
    if event_jsonl.exists() and event_jsonl.stat().st_size > 0:
        blockers.append("EVENT_JSONL_ALREADY_NONEMPTY")
    return {
        "schema_version": "zel.event_source_cutover_preflight.v1",
        "version": VERSION,
        "state": "PASS_P1_EVENT_SOURCE_CUTOVER_READY" if not blockers else "HOLD_P1_EVENT_SOURCE_CUTOVER",
        "blockers": blockers,
        "producer_source": str(producer_source),
        "producer_blob_sha": source_blob,
        "expected_producer_blob_sha": expected_blob_sha.lower(),
        "producer_state_sha256": sha256(state_path) if state_path.is_file() else "",
        "producer_status_sha256": sha256(status_path) if status_path.is_file() else "",
        "formal_ledger_sha256": sha256(formal_ledger) if formal_ledger.is_file() else "",
        "open_position_count": len(positions),
        "event_db_empty": not event_db.exists() or event_db.stat().st_size == 0,
        "event_jsonl_empty": not event_jsonl.exists() or event_jsonl.stat().st_size == 0,
        "mutation_count": 0,
        "runtime_binding_allowed": not blockers,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--producer-source", type=Path, required=True)
    parser.add_argument("--expected-producer-blob-sha", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--formal-ledger", type=Path, required=True)
    parser.add_argument("--event-db", type=Path, required=True)
    parser.add_argument("--event-jsonl", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        args.producer_source, args.expected_producer_blob_sha, args.state, args.status,
        args.formal_ledger, args.event_db, args.event_jsonl,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["state"])
    print(f"EVIDENCE={args.out}")
    return 0 if result["state"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
