#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
BRANCH="q4r3-exact25-skill-trigger-lineage-observer"
WT="/tmp/q4r3-exact25-skill-trigger-lineage-observer"
PYTHON_BIN="${Q4R3_PYTHON_BIN:-$ROOT/venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" && -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi

UNIT="q4r3-exact25-skill-trigger-lineage-observer"
PRODUCER_UNIT="q4r3-exact25-shadow-producer.service"
WRITER_UNIT="q4r3-exact25-persistent-single-event-writer.service"
OUT="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer"
BUNDLE="$OUT/bundle"
ACTIVATION="$OUT/activation.json"
EVENTS="$OUT/skill_events.jsonl"
COVERAGE="$OUT/coverage_latest.json"
VIOLATIONS="$OUT/violations_latest.json"
STATUS="$OUT/status_latest.json"
JOB_STATUS="$ROOT/runtime/q4r3_exact25_skill_trigger_lineage_observer_job_latest.json"
AUDIT_RESULT="$ROOT/runtime/exact25_edge_v1/skill_active_lineage_audit/q4r3_exact25_skill_active_lineage_audit_latest.json"
MATRIX="$ROOT/runtime/exact25_edge_v1/skill_active_lineage_audit/q4r3_exact25_skill_compatibility_matrix_latest.csv"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
OPEN="$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/open_positions_latest.json"
STORAGE_STATUS="$ROOT/runtime/q4r3_storage_regrowth_guard/status_latest.json"
SERVICE_PATH="/etc/systemd/system/$UNIT.service"
TIMER_PATH="/etc/systemd/system/$UNIT.timer"
BACKUP="$ROOT/runtime/q4r3_exact25_skill_trigger_lineage_observer_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
CURRENT_STAGE="preflight"
INSTALLED=false

write_job_status() {
  local state="$1"
  local reason="$2"
  local tmp="${JOB_STATUS}.tmp"
  mkdir -p "$(dirname "$JOB_STATUS")"
  cat >"$tmp" <<JSON
{
  "job": "q4r3_exact25_skill_trigger_lineage_observer",
  "state": "$state",
  "current_stage": "$CURRENT_STAGE",
  "reason": $("$PYTHON_BIN" -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$reason"),
  "started_at": "$STARTED_AT",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "branch": "$BRANCH",
  "status_path": "$STATUS",
  "events_path": "$EVENTS",
  "coverage_path": "$COVERAGE",
  "violations_path": "$VIOLATIONS",
  "action": "hold",
  "order_authority": "blocked",
  "execution_authority": "none",
  "paper_enabled": false,
  "live_enabled": false,
  "order_enabled": false,
  "strategy_modified": false,
  "trade_method_modified": false,
  "skill_registry_modified": false,
  "producer_modified": false,
  "writer_modified": false,
  "formal_ledger_modified": false,
  "historical_backfill_allowed": false
}
JSON
  mv -f "$tmp" "$JOB_STATUS"
}

rollback() {
  systemctl stop "$UNIT.timer" "$UNIT.service" 2>/dev/null || true
  if [[ -f "$BACKUP/$UNIT.service" ]]; then cp -f "$BACKUP/$UNIT.service" "$SERVICE_PATH"; else rm -f "$SERVICE_PATH"; fi
  if [[ -f "$BACKUP/$UNIT.timer" ]]; then cp -f "$BACKUP/$UNIT.timer" "$TIMER_PATH"; else rm -f "$TIMER_PATH"; fi
  systemctl daemon-reload || true
  if [[ -f "$BACKUP/$UNIT.timer" ]]; then systemctl enable --now "$UNIT.timer" 2>/dev/null || true; fi
  if [[ -d "$BACKUP/bundle" ]]; then rm -rf "$BUNDLE"; cp -a "$BACKUP/bundle" "$BUNDLE"; fi
}

on_error() {
  local line="$1" command="$2" code="$3"
  if [[ "$INSTALLED" == true ]]; then rollback; fi
  write_job_status "FAILED" "line=${line} exit=${code} command=${command} rollback=${INSTALLED}"
  git -c safe.directory="$ROOT" -C "$ROOT" worktree remove --force "$WT" 2>/dev/null || true
  rm -rf "$WT"
  exit "$code"
}
trap 'on_error "$LINENO" "$BASH_COMMAND" "$?"' ERR

[[ "$(id -u)" -eq 0 ]] || { echo RUN_AS_ROOT; exit 1; }
[[ -d "$ROOT/.git" ]] || { echo ROOT_REPOSITORY_MISSING; exit 1; }
[[ -x "$PYTHON_BIN" ]] || { echo PYTHON_MISSING; exit 1; }
for path in "$AUDIT_RESULT" "$MATRIX" "$LEDGER" "$OPEN" "$STORAGE_STATUS"; do
  [[ -f "$path" ]] || { echo "REQUIRED_INPUT_MISSING=$path"; exit 1; }
done

CURRENT_STAGE="safety_preflight"
systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
systemctl is-active --quiet q4r3-storage-regrowth-guard.timer
PRODUCER_PID_BEFORE="$(systemctl show -p MainPID --value "$PRODUCER_UNIT")"
WRITER_PID_BEFORE="$(systemctl show -p MainPID --value "$WRITER_UNIT")"
[[ "$PRODUCER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
[[ "$WRITER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
AVAILABLE_KB="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
(( AVAILABLE_KB >= 8388608 )) || { echo "INSUFFICIENT_FREE_SPACE_KB=$AVAILABLE_KB"; exit 1; }

"$PYTHON_BIN" - "$AUDIT_RESULT" "$STORAGE_STATUS" "$MATRIX" <<'PY'
import csv, json, sys
from pathlib import Path

audit=json.load(open(sys.argv[1],encoding='utf-8'))
storage=json.load(open(sys.argv[2],encoding='utf-8'))
with Path(sys.argv[3]).open(encoding='utf-8',newline='') as handle:
    matrix_rows=sum(1 for _ in csv.DictReader(handle))
assert audit.get('state')=='PASS', audit
assert str(audit.get('verdict') or '').startswith('ACTIVE_IMPORT_CALL_SURFACE_PASS'), audit
assert audit.get('strategy_import_pass_count')==25, audit
assert audit.get('strategy_empty_call_pass_count')==25, audit
assert audit.get('method_declaration_count')==6, audit
assert audit.get('resolver_pass_count')==18, audit
assert audit.get('compatibility_matrix_rows')==2700, audit
assert matrix_rows==2700, matrix_rows
assert storage.get('state')=='PASS', storage
assert storage.get('verdict')=='STORAGE_REGROWTH_GUARD_HEALTHY', storage
print('PREFLIGHT_CONTRACT=PASS')
PY

PROTECTED=(
  "$ROOT/backend/contracts/ZOS_SKILL_REGISTRY_v1.json"
  "$ROOT/backend/engine/skill_resolver.py"
  "$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
  "$ROOT/backend/trade_methods/policy.py"
  "$ROOT/backend/trade_methods/profiles.py"
  "$ROOT/tools/q4r3_exact25_dedicated_shadow_producer.py"
  "$LEDGER"
)
for path in "${PROTECTED[@]}"; do [[ -f "$path" ]] || { echo "PROTECTED_INPUT_MISSING=$path"; exit 1; }; done
HASH_BEFORE="$(sha256sum "${PROTECTED[@]}")"

CURRENT_STAGE="prepare_pinned_worktree"
cd "$ROOT"
git -c safe.directory="$ROOT" fetch origin "$BRANCH"
EXPECTED_HEAD="$(git -c safe.directory="$ROOT" rev-parse "origin/$BRANCH")"
git -c safe.directory="$ROOT" worktree remove --force "$WT" 2>/dev/null || true
rm -rf "$WT"
git -c safe.directory="$ROOT" worktree add --detach "$WT" "origin/$BRANCH"
ACTUAL_HEAD="$(git -c safe.directory="$WT" -C "$WT" rev-parse HEAD)"
[[ "$ACTUAL_HEAD" == "$EXPECTED_HEAD" ]] || { echo BRANCH_HEAD_MISMATCH; exit 1; }

CURRENT_STAGE="compile_and_tests"
cd "$WT"
PYTHONPATH="$WT" "$PYTHON_BIN" -m py_compile tools/q4r3_exact25_skill_trigger_lineage_observer.py
PYTHONPATH="$WT" "$PYTHON_BIN" -m pytest -q tests/test_q4r3_exact25_skill_trigger_lineage_observer.py

CURRENT_STAGE="backup_existing_observer"
mkdir -p "$BACKUP"
[[ -f "$SERVICE_PATH" ]] && cp -f "$SERVICE_PATH" "$BACKUP/$UNIT.service" || true
[[ -f "$TIMER_PATH" ]] && cp -f "$TIMER_PATH" "$BACKUP/$UNIT.timer" || true
[[ -d "$BUNDLE" ]] && cp -a "$BUNDLE" "$BACKUP/bundle" || true

CURRENT_STAGE="install_readonly_observer"
mkdir -p "$BUNDLE"
cp -f "$WT/tools/q4r3_exact25_skill_trigger_lineage_observer.py" "$BUNDLE/observer.py"
cp -f "$WT/backend/config/q4r3_exact25_skill_trigger_lineage_ssot_v1.json" "$BUNDLE/ssot.json"
cp -f "$WT/backend/contracts/ZOS_SKILL_REGISTRY_v2_candidate.json" "$BUNDLE/registry.json"
cp -f "$WT/backend/contracts/ZOS_SKILL_EVENT_CONTRACT_v1.json" "$BUNDLE/contract.json"
chmod 0555 "$BUNDLE/observer.py"
chmod 0444 "$BUNDLE/ssot.json" "$BUNDLE/registry.json" "$BUNDLE/contract.json"
printf '%s\n' "$EXPECTED_HEAD" > "$BUNDLE/SOURCE_HEAD"
chmod 0444 "$BUNDLE/SOURCE_HEAD"

if [[ ! -f "$ACTIVATION" ]]; then
  "$PYTHON_BIN" - "$OPEN" "$LEDGER" "$ACTIVATION" "$EXPECTED_HEAD" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

open_path, ledger_path, output_path, source_head=map(Path,sys.argv[1:4])+[sys.argv[4]] if False else (Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4])
try:
    payload=json.loads(open_path.read_text(encoding='utf-8'))
except Exception:
    payload={}
positions=payload.get('positions') if isinstance(payload,dict) else []
position_ids=sorted({str(row.get('position_id')) for row in positions or [] if isinstance(row,dict) and row.get('position_id')})
ledger_rows=sum(1 for line in ledger_path.read_text(encoding='utf-8',errors='replace').splitlines() if line.strip())
value={
    'schema':'q4r3_exact25_skill_trigger_lineage_activation_v1',
    'activated_at':datetime.now(timezone.utc).isoformat(),
    'baseline_ledger_rows':ledger_rows,
    'baseline_position_ids':position_ids,
    'source_head':source_head,
    'historical_backfill_allowed':False,
    'action':'hold',
}
output_path.parent.mkdir(parents=True,exist_ok=True)
tmp=output_path.with_suffix('.tmp')
tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
os.replace(tmp,output_path)
PY
fi

cat >"$SERVICE_PATH" <<EOF
[Unit]
Description=Q4R3 Exact25 Forward Skill Trigger Lineage Observer
After=$PRODUCER_UNIT $WRITER_UNIT
Requires=$PRODUCER_UNIT $WRITER_UNIT

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PYTHON_BIN $BUNDLE/observer.py --root $ROOT --ssot $BUNDLE/ssot.json --registry $BUNDLE/registry.json --contract $BUNDLE/contract.json --audit-result $AUDIT_RESULT --matrix $MATRIX --activation $ACTIVATION --events $EVENTS --coverage $COVERAGE --violations $VIOLATIONS --status $STATUS
User=root
Group=root
Nice=15
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$ROOT
ReadWritePaths=$OUT
LockPersonality=true
RestrictSUIDSGID=true
RestrictRealtime=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

[Install]
WantedBy=multi-user.target
EOF

cat >"$TIMER_PATH" <<EOF
[Unit]
Description=Q4R3 Exact25 Skill Trigger Lineage Observer Timer

[Timer]
OnBootSec=60s
OnUnitActiveSec=60s
AccuracySec=5s
Persistent=true
Unit=$UNIT.service

[Install]
WantedBy=timers.target
EOF

INSTALLED=true
systemctl daemon-reload
systemctl enable --now "$UNIT.timer"
systemctl start "$UNIT.service" || {
  code="$?"
  [[ "$code" -eq 2 && -f "$STATUS" ]] || exit "$code"
}

CURRENT_STAGE="post_install_verification"
systemctl is-active --quiet "$UNIT.timer"
[[ -f "$STATUS" && -f "$COVERAGE" && -f "$VIOLATIONS" ]]
PRODUCER_PID_AFTER="$(systemctl show -p MainPID --value "$PRODUCER_UNIT")"
WRITER_PID_AFTER="$(systemctl show -p MainPID --value "$WRITER_UNIT")"
[[ "$PRODUCER_PID_AFTER" == "$PRODUCER_PID_BEFORE" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$WRITER_PID_AFTER" == "$WRITER_PID_BEFORE" ]] || { echo WRITER_PID_CHANGED; exit 1; }
HASH_AFTER="$(sha256sum "${PROTECTED[@]}")"
[[ "$HASH_AFTER" == "$HASH_BEFORE" ]] || { echo PROTECTED_HASH_CHANGED; exit 1; }

VERDICT="$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["verdict"])' "$STATUS")"
CURRENT_STAGE="complete"
write_job_status "PASS" "SKILL_TRIGGER_LINEAGE_OBSERVER_INSTALLED:${VERDICT}"

git -c safe.directory="$ROOT" -C "$ROOT" worktree remove --force "$WT" 2>/dev/null || true
rm -rf "$WT"

echo Q4R3_EXACT25_SKILL_TRIGGER_LINEAGE_OBSERVER_INSTALLED
echo "STATUS=$STATUS"
echo "EVENTS=$EVENTS"
echo "COVERAGE=$COVERAGE"
echo "VIOLATIONS=$VIOLATIONS"
