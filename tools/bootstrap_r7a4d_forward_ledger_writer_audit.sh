#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
TARGET="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
PROOF="$ROOT/runtime/r7a4d_historical_simulation_3600/simulation_proof.json"
STATUS="$ROOT/runtime/r7a4d_historical_simulation_3600/status_latest.json"
RESULTS="$ROOT/runtime/r7a4d_historical_simulation_3600/scenario_results_3600_v1.jsonl"
TMP="$(mktemp -d /tmp/r7a4d-ledger-owner.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

printf '%s\n' \
  'R7A4D_LEDGER_OWNER_AUDIT_START' \
  'MODE=READ_ONLY_FORWARD_LEDGER_WRITER_OWNER_AUDIT' \
  'HISTORICAL_SIMULATION_REEXECUTION_ALLOWED=false' \
  'CANONICAL_MUTATION_ALLOWED=false' \
  'LEDGER_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

python3 - "$TARGET" "$PROOF" "$STATUS" "$RESULTS" <<'PY'
from __future__ import annotations
import hashlib
import json
import os
import sys
from pathlib import Path

target, proof_path, status_path, results_path = map(Path, sys.argv[1:])
blockers: list[str] = []

def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        blockers.append(f"READ_FAILED:{path}:{type(exc).__name__}:{exc}")
        return {}

proof = load(proof_path)
status = load(status_path)
mutation_paths = [str(x) for x in proof.get("mutation_paths", []) if isinstance(x, str)]
expected_hash = str(status.get("scenario_results_sha256") or proof.get("scenario_results_sha256") or "")
row_count = 0
completed_count = 0
failed_count = 0
actual_hash = ""
if results_path.is_file():
    digest = hashlib.sha256()
    with results_path.open("rb") as handle:
        for raw in handle:
            digest.update(raw)
            if not raw.strip():
                continue
            row_count += 1
            try:
                row = json.loads(raw)
                if row.get("completed") is True:
                    completed_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
    actual_hash = digest.hexdigest()
else:
    blockers.append("RESULTS_FILE_MISSING")

artifact_ok = (
    row_count == 3600
    and completed_count == 3600
    and failed_count == 0
    and bool(expected_hash)
    and actual_hash == expected_hash
)
if not artifact_ok:
    blockers.append("A4D_ARTIFACT_INTEGRITY_FAILED")
if mutation_paths != [str(target)]:
    blockers.append("MUTATION_PATH_SET_NOT_EXACT_FORWARD_LEDGER")

metadata = {}
try:
    stat = target.stat()
    metadata = {
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "inode": stat.st_ino,
        "uid": stat.st_uid,
        "gid": stat.st_gid,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "is_symlink": target.is_symlink(),
    }
except Exception as exc:
    metadata = {"exists": False, "error": f"{type(exc).__name__}:{exc}"}
    blockers.append("TARGET_LEDGER_STAT_FAILED")

print("ARTIFACT_INTEGRITY_OK=" + str(artifact_ok).lower())
print("SCENARIO_RESULT_ROW_COUNT=" + str(row_count))
print("COMPLETED_SCENARIO_COUNT=" + str(completed_count))
print("FAILED_SCENARIO_COUNT=" + str(failed_count))
print("SCENARIO_RESULTS_SHA256=" + actual_hash)
print("MUTATION_PATHS=" + json.dumps(mutation_paths, ensure_ascii=False))
print("TARGET_LEDGER_METADATA=" + json.dumps(metadata, ensure_ascii=False, sort_keys=True))
print("PRE_AUDIT_BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
PY

scan_roots=(
  /etc/systemd/system
  /lib/systemd/system
  /usr/lib/systemd/system
  /etc/cron.d
  /var/spool/cron
  "$ROOT"
)

: > "$TMP/reference_hits.txt"
for scan_root in "${scan_roots[@]}"; do
  [[ -e "$scan_root" ]] || continue
  if [[ -f "$scan_root" ]]; then
    grep -nH -F -e "$TARGET" -e 'forward_r_ledger.jsonl' -e 'formal_exact5_measurement' "$scan_root" 2>/dev/null >> "$TMP/reference_hits.txt" || true
  else
    grep -RInH -F \
      --include='*.service' --include='*.timer' --include='*.path' --include='*.sh' --include='*.py' --include='*.pl' --include='*.rb' --include='*.js' --include='*.ts' --include='*.json' --include='crontab' \
      --exclude-dir='.git' --exclude-dir='runtime' --exclude-dir='_backups' --exclude-dir='venv' --exclude-dir='.venv' --exclude-dir='node_modules' --exclude-dir='__pycache__' \
      -e "$TARGET" -e 'forward_r_ledger.jsonl' -e 'formal_exact5_measurement' "$scan_root" 2>/dev/null >> "$TMP/reference_hits.txt" || true
  fi
done
sort -u "$TMP/reference_hits.txt" -o "$TMP/reference_hits.txt"

systemctl list-timers --all --no-pager --no-legend 2>/dev/null | grep -Ei 'exact5|formal|ledger|measurement|shadow' > "$TMP/timer_hits.txt" || true
systemctl list-units --type=service --all --no-pager --no-legend 2>/dev/null | grep -Ei 'exact5|formal|ledger|measurement|shadow' > "$TMP/service_hits.txt" || true
ps -eo pid=,etimes=,lstart=,args= 2>/dev/null | grep -Ei 'forward_r_ledger|formal_exact5_measurement|exact5.*measure|measure.*exact5' | grep -v -E 'grep -E|writer_audit' > "$TMP/process_hits.txt" || true
if command -v lsof >/dev/null 2>&1; then
  lsof -- "$TARGET" > "$TMP/lsof_hits.txt" 2>/dev/null || true
else
  : > "$TMP/lsof_hits.txt"
fi

python3 - "$TMP/reference_hits.txt" "$TMP/timer_hits.txt" "$TMP/service_hits.txt" "$TMP/process_hits.txt" "$TMP/lsof_hits.txt" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

paths = [Path(x) for x in sys.argv[1:]]

def lines(path: Path, limit: int = 80) -> list[str]:
    try:
        return [line.rstrip("\n") for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()][:limit]
    except Exception:
        return []

references, timers, services, processes, lsof = [lines(path) for path in paths]
owner_evidence_count = len(references) + len(timers) + len(services) + len(processes) + len(lsof)
print("OWNER_REFERENCE_COUNT=" + str(len(references)))
print("OWNER_REFERENCE_SAMPLE=" + json.dumps(references, ensure_ascii=False))
print("MATCHING_TIMER_COUNT=" + str(len(timers)))
print("MATCHING_TIMER_SAMPLE=" + json.dumps(timers, ensure_ascii=False))
print("MATCHING_SERVICE_COUNT=" + str(len(services)))
print("MATCHING_SERVICE_SAMPLE=" + json.dumps(services, ensure_ascii=False))
print("MATCHING_PROCESS_COUNT=" + str(len(processes)))
print("MATCHING_PROCESS_SAMPLE=" + json.dumps(processes, ensure_ascii=False))
print("LSOF_MATCH_COUNT=" + str(len(lsof)))
print("LSOF_MATCH_SAMPLE=" + json.dumps(lsof, ensure_ascii=False))
print("OWNER_EVIDENCE_COUNT=" + str(owner_evidence_count))
print("EXTERNAL_WRITER_CANDIDATE_FOUND=" + str(owner_evidence_count > 0).lower())
print("STATE=HOLD")
print("BLOCKER_COUNT=1")
print("BLOCKERS=[\"FORWARD_LEDGER_EXTERNAL_WRITER_CAUSALITY_NOT_YET_PROVEN\"]")
print("NEXT_STAGE=" + ("R7.A4D_LEDGER_AMBIENT_WRITE_OBSERVE" if owner_evidence_count > 0 else "R7.A4D_LEDGER_WRITER_DISCOVERY"))
print("RC=2")
PY

echo 'R7A4D_LEDGER_OWNER_AUDIT_COMPLETE'
exit 2
