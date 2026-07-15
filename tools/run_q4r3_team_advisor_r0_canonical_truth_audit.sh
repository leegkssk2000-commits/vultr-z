#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
OUT="$ROOT/runtime/exact25_edge_v1/team_advisor_r0_canonical_truth"
STATUS="$OUT/status_latest.json"
UNITS="$OUT/units_latest.json"
CANDIDATES="$OUT/candidates_latest.json"
JOB="$ROOT/runtime/q4r3_team_advisor_r0_canonical_truth_job_latest.json"
SSOT="$WT/backend/config/q4r3_team_advisor_canonical_truth_ssot_v1.json"
ALIASES="$WT/backend/config/q4r3_r0_candidate_aliases_v1.json"
AUDIT="$WT/tools/q4r3_team_advisor_r0_canonical_truth_audit_strict.py"
BASE_AUDIT="$WT/tools/q4r3_team_advisor_r0_canonical_truth_audit.py"
TESTS=(
  "$WT/tests/test_q4r3_team_advisor_r0_canonical_truth_audit.py"
  "$WT/tests/test_q4r3_team_advisor_r0_strict_bindings.py"
)
PREFIX="$(mktemp /tmp/q4r3_r0_ledger_prefix.XXXXXX)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cleanup() { rm -f "$PREFIX"; }
trap cleanup EXIT

write_job() {
  local state="$1" reason="$2"
  mkdir -p "$(dirname "$JOB")"
  "$PY" - "$JOB" "$state" "$reason" "$STARTED_AT" "$STATUS" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
path=Path(sys.argv[1])
payload={
  "schema":"q4r3_team_advisor_r0_canonical_truth_job_v1",
  "state":sys.argv[2],
  "reason":sys.argv[3],
  "started_at":sys.argv[4],
  "updated_at":datetime.now(timezone.utc).isoformat(),
  "status_path":sys.argv[5],
  "canonical_names":{"zico":"Zico","lico":"Lico"},
  "runtime_mutation_performed":False,
  "producer_modified":False,
  "writer_modified":False,
  "formal_ledger_modified":False,
  "strategy_modified":False,
  "method_modified":False,
  "skill_registry_modified":False,
  "paper_enabled":False,
  "live_enabled":False,
  "order_enabled":False,
  "order_authority":"blocked",
  "execution_authority":"none",
  "action":"hold",
}
tmp=path.with_suffix(path.suffix+".tmp")
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
os.replace(tmp,path)
PY
}

on_error() {
  local line="$1" command="$2" code="$3"
  write_job FAILED "line=${line} exit=${code} command=${command}"
  exit "$code"
}
trap 'on_error "$LINENO" "$BASH_COMMAND" "$?"' ERR

[[ -f "$LEDGER" ]] || { echo "LEDGER_MISSING=$LEDGER"; exit 1; }
for required in "$SSOT" "$ALIASES" "$AUDIT" "$BASE_AUDIT" "${TESTS[@]}"; do
  [[ -f "$required" ]] || { echo "REQUIRED_FILE_MISSING=$required"; exit 1; }
done

systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
[[ "$WRITER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]

cp --reflink=auto "$LEDGER" "$PREFIX"
LEDGER_SIZE_BEFORE="$(stat -c %s "$PREFIX")"
LEDGER_ROWS_BEFORE="$(wc -l < "$PREFIX")"

"$PY" -m py_compile "$BASE_AUDIT" "$AUDIT"
PYTHONPATH="$WT" "$PY" -m pytest -q "${TESTS[@]}"

mkdir -p "$OUT"
"$PY" "$AUDIT" \
  --root "$ROOT" \
  --ssot "$SSOT" \
  --aliases "$ALIASES" \
  --output "$STATUS" \
  --units-output "$UNITS" \
  --candidates-output "$CANDIDATES"

"$PY" - "$STATUS" <<'PY'
import json,sys
status=json.load(open(sys.argv[1],encoding="utf-8"))
assert status.get("state") in {"PASS","HOLD"}, status
assert status.get("verdict") in {"R0_CANONICAL_TRUTH_LOCK_PASS","R0_CANONICAL_TRUTH_UNRESOLVED"}, status
scope=status.get("scope") or []
assert "Zico" in scope and "Lico" in scope, scope
assert "ZICO" not in scope and "LiCo" not in scope and "LICO" not in scope, scope
assert set(status.get("owner_matrix") or {}) == set(scope), status.get("owner_matrix")
authority=status.get("authority") or {}
assert authority.get("runtime_mutation_performed") is False, authority
assert authority.get("paper_enabled") is False, authority
assert authority.get("live_enabled") is False, authority
assert authority.get("order_enabled") is False, authority
assert authority.get("order_authority")=="blocked", authority
assert authority.get("execution_authority")=="none", authority
print("R0_STATUS_SCHEMA=PASS")
PY

systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_AFTER" == "$PRODUCER_PID_BEFORE" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$WRITER_PID_AFTER" == "$WRITER_PID_BEFORE" ]] || { echo WRITER_PID_CHANGED; exit 1; }
LEDGER_SIZE_AFTER="$(stat -c %s "$LEDGER")"
[[ "$LEDGER_SIZE_AFTER" -ge "$LEDGER_SIZE_BEFORE" ]]
cmp -n "$LEDGER_SIZE_BEFORE" "$PREFIX" "$LEDGER"

AUDIT_STATE="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["state"])' "$STATUS")"
write_job PASS "R0_AUDIT_COMPLETED_${AUDIT_STATE}"

echo Q4R3_TEAM_ADVISOR_R0_AUDIT_COMPLETED
echo "AUDIT_STATE=$AUDIT_STATE"
echo "STATUS=$STATUS"
echo "UNITS=$UNITS"
echo "CANDIDATES=$CANDIDATES"
echo "LEDGER_ROWS_BEFORE=$LEDGER_ROWS_BEFORE"
echo "PRODUCER_PID=$PRODUCER_PID_AFTER"
echo "WRITER_PID=$WRITER_PID_AFTER"
