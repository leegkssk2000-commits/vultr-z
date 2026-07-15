#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || PY=python3

UNIT=zico-ceo-canonical-adapter.service
SOURCE=/opt/zico-ceo-canonical-adapter/adapter.py
EXPECTED_SHA=d8259ed38e89412e25de8a3a48265a81c6db34266a1c274965eddb9aa41d7779
EXPECTED_CONTRACT=zico-ceo-adapter/7.3.3.0
DEST="$WT/canonical/zico/adapter.py"
MANIFEST="$WT/canonical/zico/manifest.json"
EVIDENCE="$WT/evidence/q4r3_team_advisor_r02_zico_secure_mirror_latest.json"
MODULE="$WT/tools/q4r3_team_advisor_r02_zico_secure_mirror.py"
TEST="$WT/tests/test_q4r3_team_advisor_r02_zico_secure_mirror.py"
R01="$ROOT/runtime/exact25_edge_v1/team_advisor_r01_owner_adjudication/status_latest.json"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
PREFIX="$(mktemp /tmp/q4r3_r02_zico_ledger_prefix.XXXXXX)"
trap 'rm -f "$PREFIX"' EXIT

for required in "$SOURCE" "$MODULE" "$TEST" "$R01" "$LEDGER"; do
  [[ -f "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

systemctl is-active --quiet "$UNIT"
EXEC_START="$(systemctl show "$UNIT" -p ExecStart --value)"
[[ "$EXEC_START" == *"$SOURCE"* ]] || { echo ZICO_EXECSTART_SOURCE_MISMATCH; exit 1; }
ZICO_PID_BEFORE="$(systemctl show "$UNIT" -p MainPID --value)"
[[ "$ZICO_PID_BEFORE" =~ ^[1-9][0-9]*$ ]] || { echo ZICO_MAINPID_INVALID; exit 1; }

systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
[[ "$WRITER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]

"$PY" - "$R01" "$SOURCE" "$EXPECTED_SHA" "$EXPECTED_CONTRACT" <<'PY'
import hashlib,json,sys
path,source,expected_sha,expected_contract=sys.argv[1:]
data=json.load(open(path,encoding="utf-8"))
component=data.get("components",{}).get("Zico",{})
assert data.get("verdict")=="R01_OWNER_ADJUDICATION_PLAN_READY", data.get("verdict")
assert component.get("adjudication_route")=="MIRROR_ACTIVE_RUNTIME_TO_GIT", component
raw=open(source,"rb").read()
assert hashlib.sha256(raw).hexdigest()==expected_sha
assert expected_contract.encode() in raw
print("R02_ZICO_PREFLIGHT=PASS")
PY

cp --reflink=auto "$LEDGER" "$PREFIX"
LEDGER_SIZE_BEFORE="$(stat -c %s "$PREFIX")"
SOURCE_SHA_BEFORE="$(sha256sum "$SOURCE" | awk '{print $1}')"
SOURCE_MTIME_BEFORE="$(stat -c %Y "$SOURCE")"

"$PY" -m py_compile "$MODULE"
PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST"

"$PY" "$MODULE" \
  --source "$SOURCE" \
  --destination "$DEST" \
  --manifest "$MANIFEST" \
  --evidence "$EVIDENCE" \
  --unit "$UNIT" \
  --expected-sha256 "$EXPECTED_SHA" \
  --expected-contract-version "$EXPECTED_CONTRACT"

"$PY" -m py_compile "$DEST"
cmp "$SOURCE" "$DEST"
[[ "$(sha256sum "$DEST" | awk '{print $1}')" == "$EXPECTED_SHA" ]]

ZICO_PID_AFTER="$(systemctl show "$UNIT" -p MainPID --value)"
PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$ZICO_PID_AFTER" == "$ZICO_PID_BEFORE" ]] || { echo ZICO_PID_CHANGED; exit 1; }
[[ "$PRODUCER_PID_AFTER" == "$PRODUCER_PID_BEFORE" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$WRITER_PID_AFTER" == "$WRITER_PID_BEFORE" ]] || { echo WRITER_PID_CHANGED; exit 1; }
[[ "$(sha256sum "$SOURCE" | awk '{print $1}')" == "$SOURCE_SHA_BEFORE" ]] || { echo ZICO_SOURCE_CHANGED; exit 1; }
[[ "$(stat -c %Y "$SOURCE")" == "$SOURCE_MTIME_BEFORE" ]] || { echo ZICO_SOURCE_MTIME_CHANGED; exit 1; }
LEDGER_SIZE_AFTER="$(stat -c %s "$LEDGER")"
[[ "$LEDGER_SIZE_AFTER" -ge "$LEDGER_SIZE_BEFORE" ]]
cmp -n "$LEDGER_SIZE_BEFORE" "$PREFIX" "$LEDGER"

"$PY" - "$EVIDENCE" "$MANIFEST" <<'PY'
import json,sys
result=json.load(open(sys.argv[1],encoding="utf-8"))
manifest=json.load(open(sys.argv[2],encoding="utf-8"))
assert result.get("state")=="PASS", result
assert result.get("verdict")=="R02_ZICO_SECURE_MIRROR_READY", result
assert result.get("mirror_written") is True, result
assert not result.get("blockers"), result
assert manifest.get("canonical_name")=="Zico", manifest
assert manifest.get("byte_parity") is True, manifest
assert manifest.get("runtime_mutation_performed") is False, manifest
assert manifest.get("systemd_mutation_performed") is False, manifest
print("R02_ZICO_SECURE_MIRROR_GATE=PASS")
PY

echo Q4R3_TEAM_ADVISOR_R02_ZICO_SECURE_MIRROR_COMPLETE
echo "EVIDENCE=$EVIDENCE"
echo "MIRROR=$DEST"
echo "ZICO_PID=$ZICO_PID_AFTER"
echo "PRODUCER_PID=$PRODUCER_PID_AFTER"
echo "WRITER_PID=$WRITER_PID_AFTER"
