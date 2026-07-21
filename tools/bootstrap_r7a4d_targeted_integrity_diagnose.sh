#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"

printf '%s\n' \
  'R7A4D_DIAG_START' \
  'MODE=READ_ONLY_EXISTING_3600_RESULT_INTEGRITY_DIAGNOSE' \
  'HISTORICAL_SIMULATION_REEXECUTION_ALLOWED=false' \
  'CANONICAL_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

python3 - "$ROOT" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

root = Path(sys.argv[1]).resolve()
base = root / "runtime/r7a4d_historical_simulation_3600"
status_path = base / "status_latest.json"
proof_path = base / "simulation_proof.json"
aggregate_path = base / "aggregate_results_v1.json"
results_path = base / "scenario_results_3600_v1.jsonl"


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"JSON_READ_FAILED:{path}:{type(exc).__name__}:{exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_NOT_OBJECT:{path}")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


blockers: list[str] = []
try:
    status = load_object(status_path)
    proof = load_object(proof_path)
    aggregate = load_object(aggregate_path)
except Exception as exc:
    print("STATE=HOLD")
    print("BLOCKER_COUNT=1")
    print("BLOCKERS=" + json.dumps([str(exc)], ensure_ascii=False))
    print("RC=2")
    raise SystemExit(2)

if not results_path.is_file() or results_path.is_symlink():
    blockers.append("SCENARIO_RESULTS_FILE_INVALID")
    rows: list[dict[str, Any]] = []
    actual_sha = ""
else:
    actual_sha = file_sha256(results_path)
    rows = []
    try:
        with results_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    blockers.append(f"EMPTY_RESULT_LINE:{line_number}")
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    blockers.append(f"RESULT_LINE_NOT_OBJECT:{line_number}")
                    continue
                rows.append(value)
    except Exception as exc:
        blockers.append(f"RESULTS_READ_FAILED:{type(exc).__name__}:{exc}")

expected_sha_values = {
    str(status.get("scenario_results_sha256") or ""),
    str(proof.get("scenario_results_sha256") or ""),
    str(aggregate.get("scenario_results_sha256") or ""),
}
expected_sha_values.discard("")
if len(expected_sha_values) != 1:
    blockers.append(f"RECORDED_RESULT_SHA_DISAGREEMENT:{sorted(expected_sha_values)}")
elif actual_sha not in expected_sha_values:
    blockers.append(f"RESULT_SHA_MISMATCH:{actual_sha}:{sorted(expected_sha_values)}")

completed = sum(1 for row in rows if row.get("completed") is True)
failed = len(rows) - completed
unique_ids = len({str(row.get("scenario_id")) for row in rows})
if len(rows) != 3600:
    blockers.append(f"RESULT_ROW_COUNT_INVALID:{len(rows)}")
if completed != 3600 or failed != 0:
    blockers.append(f"RESULT_COMPLETION_INVALID:{completed}:{failed}")
if unique_ids != 3600:
    blockers.append(f"RESULT_SCENARIO_ID_UNIQUENESS_INVALID:{unique_ids}")

required_status = {
    "historical_simulation_execution_count": 3600,
    "completed_scenario_count": 3600,
    "failed_scenario_count": 0,
    "side_effect_attempt_count": 0,
    "canonical_mutation_count": 0,
    "router_mutation_count": 0,
    "service_mutation_count": 0,
    "shadow_start_count": 0,
    "paper_live_order_count": 0,
}
for key, expected in required_status.items():
    if status.get(key) != expected:
        blockers.append(f"STATUS_CONTRACT_MISMATCH:{key}:{status.get(key)}:{expected}")

mutation_paths = [str(item) for item in proof.get("mutation_paths", []) if str(item)]
dynamic_display_paths = {
    str(root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json"),
    str(root / "runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json"),
}
static_critical_paths = {
    str(root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"),
    "/etc/caddy/Caddyfile",
}
dynamic_mutations = sorted(path for path in mutation_paths if path in dynamic_display_paths)
static_mutations = sorted(path for path in mutation_paths if path in static_critical_paths)
unknown_mutations = sorted(path for path in mutation_paths if path not in dynamic_display_paths | static_critical_paths)

mutation_metadata: list[dict[str, Any]] = []
for value in mutation_paths:
    path = Path(value)
    item: dict[str, Any] = {"path": value, "exists": path.exists(), "is_file": path.is_file(), "is_symlink": path.is_symlink()}
    try:
        stat = path.stat()
        item.update({"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
        if path.is_file() and not path.is_symlink():
            item["current_sha256"] = file_sha256(path)
    except Exception as exc:
        item["metadata_error"] = f"{type(exc).__name__}:{exc}"
    mutation_metadata.append(item)

if static_mutations:
    blockers.append("STATIC_CRITICAL_PROTECTED_MUTATION")
if unknown_mutations:
    blockers.append("UNKNOWN_PROTECTED_MUTATION")
if len(mutation_paths) != 1:
    blockers.append(f"MUTATION_PATH_COUNT_NOT_ONE:{len(mutation_paths)}")

artifact_integrity_ok = not any(
    blocker.startswith((
        "SCENARIO_RESULTS_", "RESULT", "RECORDED_RESULT", "RESULTS_READ", "EMPTY_RESULT", "STATUS_CONTRACT"
    ))
    for blocker in blockers
)
ambient_dynamic_candidate = bool(
    artifact_integrity_ok
    and len(mutation_paths) == 1
    and len(dynamic_mutations) == 1
    and not static_mutations
    and not unknown_mutations
)

if ambient_dynamic_candidate:
    state = "HOLD_OWNER_VERIFY"
    next_stage = "R7.A4D_DYNAMIC_WRITER_OWNER_VERIFY"
    rc = 2
elif not blockers and not mutation_paths:
    state = "PASS"
    next_stage = "R7.A4E_EVENT_REPLAY_2880_INPUT_SELECTION"
    rc = 0
else:
    state = "HOLD"
    next_stage = "R7.A4D_TARGETED_DIAGNOSE"
    rc = 2

print(f"STATE={state}")
print(f"ARTIFACT_INTEGRITY_OK={str(artifact_integrity_ok).lower()}")
print(f"SCENARIO_RESULT_ROW_COUNT={len(rows)}")
print(f"COMPLETED_SCENARIO_COUNT={completed}")
print(f"FAILED_SCENARIO_COUNT={failed}")
print(f"UNIQUE_SCENARIO_ID_COUNT={unique_ids}")
print(f"SCENARIO_RESULTS_SHA256={actual_sha}")
print("RECORDED_RESULT_SHA256=" + json.dumps(sorted(expected_sha_values), ensure_ascii=False))
print(f"MUTATION_PATH_COUNT={len(mutation_paths)}")
print("MUTATION_PATHS=" + json.dumps(mutation_paths, ensure_ascii=False))
print("DYNAMIC_DISPLAY_MUTATIONS=" + json.dumps(dynamic_mutations, ensure_ascii=False))
print("STATIC_CRITICAL_MUTATIONS=" + json.dumps(static_mutations, ensure_ascii=False))
print("UNKNOWN_MUTATIONS=" + json.dumps(unknown_mutations, ensure_ascii=False))
print("MUTATION_METADATA=" + json.dumps(mutation_metadata, ensure_ascii=False, sort_keys=True))
print(f"AMBIENT_DYNAMIC_CANDIDATE={str(ambient_dynamic_candidate).lower()}")
print(f"BLOCKER_COUNT={len(blockers)}")
print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
print(f"NEXT_STAGE={next_stage}")
print(f"RC={rc}")
raise SystemExit(rc)
PY
RC=$?

echo 'R7A4D_DIAG_COMPLETE'
echo "RC=$RC"
exit "$RC"
