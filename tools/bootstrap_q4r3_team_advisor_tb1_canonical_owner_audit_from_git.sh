#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
SHA="${Q4R3_TB1_SHA:?Q4R3_TB1_SHA_REQUIRED}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-tb1-canonical-owner-audit-v1}"
WT="/tmp/q4r3_team_advisor_tb1_${SHA:0:12}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
CADENCE_STATUS="$ROOT/runtime/exact25_edge_v1/lineage_cadence_repair/status_latest.json"
EVIDENCE_REL="evidence/q4r3_team_advisor_tb1_canonical_owner_audit_latest.json"
EVIDENCE="${WT}/${EVIDENCE_REL}"
LEDGER_PREFIX="$(mktemp /tmp/q4r3_tb1_ledger_prefix.XXXXXX)"

cleanup() {
  local code="$?"
  rm -f "$LEDGER_PREFIX"
  if [[ "$code" -eq 0 ]]; then
    git -C "$ROOT" -c safe.directory="$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  else
    echo "WORKTREE_PRESERVED_FOR_DIAGNOSIS=$WT"
  fi
}
trap cleanup EXIT

[[ -d "$ROOT/.git" || -f "$ROOT/.git" ]] || { echo "GIT_REPO_MISSING=$ROOT"; exit 1; }
[[ -f "$LEDGER" ]] || { echo "FORMAL_LEDGER_MISSING=$LEDGER"; exit 1; }

PRODUCER_PID_BEFORE="$(systemctl show q4r3-exact25-shadow-producer.service -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show q4r3-exact25-persistent-single-event-writer.service -p MainPID --value)"
[[ "$PRODUCER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
[[ "$WRITER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
cp --reflink=auto "$LEDGER" "$LEDGER_PREFIX"
LEDGER_SIZE_BEFORE="$(stat -c %s "$LEDGER_PREFIX")"

if [[ -e "$WT" ]]; then
  git -C "$ROOT" -c safe.directory="$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"
fi

git -C "$ROOT" -c safe.directory="$ROOT" fetch --no-tags origin "$SHA"
git -C "$ROOT" -c safe.directory="$ROOT" worktree add --detach "$WT" "$SHA"

"$PY" -m py_compile "$WT/tools/q4r3_team_advisor_tb1_canonical_owner_audit.py"
PYTHONPATH="$WT" "$PY" -m pytest -q "$WT/tests/test_q4r3_team_advisor_tb1_canonical_owner_audit.py"

mkdir -p "$(dirname "$EVIDENCE")"
"$PY" "$WT/tools/q4r3_team_advisor_tb1_canonical_owner_audit.py" \
  --root "$ROOT" \
  --output "$EVIDENCE"

"$PY" - "$EVIDENCE" "$CADENCE_STATUS" "$PRODUCER_PID_BEFORE" "$WRITER_PID_BEFORE" <<'PY'
import json, os, sys
from pathlib import Path

evidence_path=Path(sys.argv[1])
cadence_path=Path(sys.argv[2])
payload=json.loads(evidence_path.read_text(encoding="utf-8"))
cadence={}
if cadence_path.is_file():
    raw=json.loads(cadence_path.read_text(encoding="utf-8"))
    for key in (
        "state", "verdict", "observer_interval_sec", "post_repair_close_count",
        "post_repair_lineage_covered_count", "post_repair_uncovered_count",
        "post_repair_coverage_pct", "remaining_to_canary", "violation_count",
    ):
        cadence[key]=raw.get(key)
payload["parallel_lineage_cadence_repair"]=cadence
payload["protected_runtime"]={
    "producer_pid_before":int(sys.argv[3]),
    "writer_pid_before":int(sys.argv[4]),
    "producer_writer_restart_performed":False,
    "formal_ledger_mutation_performed":False,
}
temporary=evidence_path.with_suffix(evidence_path.suffix+".tmp")
temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
os.replace(temporary,evidence_path)
PY

PRODUCER_PID_AFTER="$(systemctl show q4r3-exact25-shadow-producer.service -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show q4r3-exact25-persistent-single-event-writer.service -p MainPID --value)"
[[ "$PRODUCER_PID_AFTER" == "$PRODUCER_PID_BEFORE" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$WRITER_PID_AFTER" == "$WRITER_PID_BEFORE" ]] || { echo WRITER_PID_CHANGED; exit 1; }
LEDGER_SIZE_AFTER="$(stat -c %s "$LEDGER")"
[[ "$LEDGER_SIZE_AFTER" -ge "$LEDGER_SIZE_BEFORE" ]]
cmp -n "$LEDGER_SIZE_BEFORE" "$LEDGER_PREFIX" "$LEDGER"

"$PY" - "$EVIDENCE" "$PRODUCER_PID_AFTER" "$WRITER_PID_AFTER" <<'PY'
import json, os, sys
from pathlib import Path
path=Path(sys.argv[1])
payload=json.loads(path.read_text(encoding="utf-8"))
payload["protected_runtime"]["producer_pid_after"]=int(sys.argv[2])
payload["protected_runtime"]["writer_pid_after"]=int(sys.argv[3])
payload["protected_runtime"]["pid_preserved"]=True
payload["protected_runtime"]["formal_ledger_prefix_preserved"]=True
tmp=path.with_suffix(path.suffix+".tmp")
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
os.replace(tmp,path)
PY

git -C "$WT" add "$EVIDENCE_REL"
git -C "$WT" -c user.name="ZEL Runtime Evidence" -c user.email="zel-runtime-evidence@localhost" \
  commit -m "Record Team Advisor TB1 canonical owner audit evidence"
git -C "$WT" push origin "HEAD:refs/heads/$TARGET_BRANCH"

echo Q4R3_TEAM_ADVISOR_TB1_AUDIT_AND_PUBLISH_PASS
echo "EVIDENCE=$EVIDENCE_REL"
echo "PRODUCER_PID=$PRODUCER_PID_AFTER"
echo "WRITER_PID=$WRITER_PID_AFTER"
