#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-sgrade-readiness-v1}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

AUDIT="$WT/tools/q4r3_team_advisor_sgrade_readiness_audit.py"
TEST="$WT/tests/test_q4r3_team_advisor_sgrade_readiness_audit.py"
SSOT="$WT/backend/config/q4r3_team_advisor_sgrade_readiness_ssot_v1.json"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
EVIDENCE_REL="evidence/q4r3_team_advisor_sgrade_readiness_latest.json"
EVIDENCE="$WT/$EVIDENCE_REL"
UNITS="$(mktemp /tmp/q4r3_sgrade_units.XXXXXX.json)"
PREFIX="$(mktemp /tmp/q4r3_sgrade_ledger_prefix.XXXXXX)"

cleanup() { rm -f "$UNITS" "$PREFIX"; }
trap cleanup EXIT

for required in "$AUDIT" "$TEST" "$SSOT" "$LEDGER"; do
  [[ -f "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
[[ "$WRITER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
cp --reflink=auto "$LEDGER" "$PREFIX"
PREFIX_SIZE="$(stat -c %s "$PREFIX")"

"$PY" -m py_compile "$AUDIT"
PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST"

"$PY" - "$UNITS" <<'PY'
import json,re,subprocess,sys
from pathlib import Path
out=Path(sys.argv[1])
pattern=re.compile(r'(lbot|mbot|obot|sbot|zbot|zico|lico|zlice|team|advisor|exact25)',re.I)
listed=subprocess.run(
    ['systemctl','list-unit-files','--no-legend','--no-pager'],
    capture_output=True,text=True,check=False,
).stdout.splitlines()
units=[]
for line in listed:
    parts=line.split()
    if not parts:
        continue
    name=parts[0]
    if not pattern.search(name):
        continue
    show=subprocess.run(
        ['systemctl','show',name,'-p','Id','-p','ActiveState','-p','SubState','-p','MainPID','-p','FragmentPath','-p','ExecStart','--no-pager'],
        capture_output=True,text=True,check=False,
    ).stdout.splitlines()
    row={'unit':name}
    for item in show:
        if '=' in item:
            key,value=item.split('=',1)
            row[key]=value
    units.append(row)
out.write_text(json.dumps(units,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
PY

mkdir -p "$(dirname "$EVIDENCE")"
"$PY" "$AUDIT" \
  --root "$ROOT" \
  --ssot "$SSOT" \
  --units "$UNITS" \
  --output "$EVIDENCE"

PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_AFTER" == "$PRODUCER_PID_BEFORE" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$WRITER_PID_AFTER" == "$WRITER_PID_BEFORE" ]] || { echo WRITER_PID_CHANGED; exit 1; }
[[ "$(stat -c %s "$LEDGER")" -ge "$PREFIX_SIZE" ]]
cmp -n "$PREFIX_SIZE" "$PREFIX" "$LEDGER"

"$PY" - "$EVIDENCE" <<'PY'
import json,sys
payload=json.load(open(sys.argv[1],encoding='utf-8'))
assert payload.get('schema')=='q4r3_team_advisor_sgrade_readiness_audit_v1', payload
assert payload.get('current_s_grade_claim_allowed') is False, payload
policy=payload.get('policy') or {}
assert policy.get('paper_enabled') is False, policy
assert policy.get('live_enabled') is False, policy
assert policy.get('order_enabled') is False, policy
assert policy.get('order_authority')=='blocked', policy
assert policy.get('execution_authority')=='none', policy
assert payload.get('scan',{}).get('excluded_contamination_count',-1)>=0, payload
print('TEAM_ADVISOR_SGRADE_READINESS_EVIDENCE_GATE=PASS')
PY

git -C "$WT" add "$EVIDENCE_REL"
if ! git -C "$WT" diff --cached --quiet; then
  git -C "$WT" -c user.name="ZEL Runtime Evidence" -c user.email="zel-runtime-evidence@localhost" \
    commit -m "Record Team Advisor S-grade readiness evidence"
  git -C "$WT" push origin "HEAD:refs/heads/$TARGET_BRANCH"
else
  echo EVIDENCE_UNCHANGED
fi

echo Q4R3_TEAM_ADVISOR_SGRADE_READINESS_AUDIT_AND_PUBLISH_PASS
echo "EVIDENCE=$EVIDENCE_REL"
echo "PRODUCER_PID=$PRODUCER_PID_AFTER"
echo "WRITER_PID=$WRITER_PID_AFTER"
