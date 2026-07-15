#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-tb11-owner-narrowing-v1}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

AUDIT_ORIGINAL="$WT/tools/q4r3_team_advisor_tb11_owner_narrowing_audit.py"
AUDIT="$WT/tools/q4r3_team_advisor_tb11_owner_narrowing_audit_fixed.py"
TEST="$WT/tests/test_q4r3_team_advisor_tb11_owner_narrowing_audit.py"
EVIDENCE_REL="evidence/q4r3_team_advisor_tb11_owner_narrowing_latest.json"
EVIDENCE="$WT/$EVIDENCE_REL"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
PREFIX="$(mktemp /tmp/q4r3_tb11_ledger_prefix.XXXXXX)"

cleanup() { rm -f "$PREFIX"; }
trap cleanup EXIT

for required in "$AUDIT_ORIGINAL" "$AUDIT" "$TEST" "$LEDGER"; do
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

"$PY" -m py_compile "$AUDIT_ORIGINAL" "$AUDIT"
PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST"

mkdir -p "$(dirname "$EVIDENCE")"
"$PY" "$AUDIT" --root "$ROOT" --output "$EVIDENCE"

PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_AFTER" == "$PRODUCER_PID_BEFORE" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$WRITER_PID_AFTER" == "$WRITER_PID_BEFORE" ]] || { echo WRITER_PID_CHANGED; exit 1; }
[[ "$(stat -c %s "$LEDGER")" -ge "$PREFIX_SIZE" ]]
cmp -n "$PREFIX_SIZE" "$PREFIX" "$LEDGER"

"$PY" - "$EVIDENCE" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
assert p.get("schema")=="q4r3_team_advisor_tb11_owner_narrowing_audit_v1", p
assert p.get("policy",{}).get("observer_only") is True, p
assert p.get("policy",{}).get("team_advisor_binding_enabled") is False, p
assert p.get("policy",{}).get("paper_enabled") is False, p
assert p.get("policy",{}).get("live_enabled") is False, p
assert p.get("policy",{}).get("order_enabled") is False, p
assert p.get("policy",{}).get("order_authority")=="blocked", p
assert p.get("policy",{}).get("execution_authority")=="none", p
assert p.get("scan_stats",{}).get("capped") is False, p.get("scan_stats")
assert "frontend" in p.get("excluded_surfaces",[]), p.get("excluded_surfaces")
print("TB11_EVIDENCE_GATE=PASS")
PY

git -C "$WT" add "$EVIDENCE_REL"
if ! git -C "$WT" diff --cached --quiet; then
  git -C "$WT" -c user.name="ZEL Runtime Evidence" -c user.email="zel-runtime-evidence@localhost" \
    commit -m "Record Team Advisor TB1.1 owner narrowing evidence"
  git -C "$WT" push origin "HEAD:refs/heads/$TARGET_BRANCH"
else
  echo EVIDENCE_UNCHANGED
fi

echo Q4R3_TEAM_ADVISOR_TB11_AUDIT_AND_PUBLISH_PASS
echo "EVIDENCE=$EVIDENCE_REL"
echo "PRODUCER_PID=$PRODUCER_PID_AFTER"
echo "WRITER_PID=$WRITER_PID_AFTER"
